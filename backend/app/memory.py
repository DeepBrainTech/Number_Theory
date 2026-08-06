from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from openai import AsyncOpenAI

from .config import settings
from .db import connection


MEMORY_EXTRACT_PROMPT = """Extract durable user facts worth remembering across chats.
Keep only stable information such as learning goals, preferred style/language, weak topics, or current chapter focus.
Do not store concrete exercise steps, temporary calculations, or one-off questions.
If nothing durable should be remembered, return an empty array.
Output JSON only: {"memories":["fact 1","fact 2"]}, each fact under 80 characters, at most 3 items, in English."""


def list_memories(client_id: str, limit: int = 30) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                content,
                source_conversation_id::text AS source_conversation_id,
                created_at,
                updated_at
            FROM user_memories
            WHERE client_id = %s
            ORDER BY updated_at DESC
            LIMIT %s
            """,
            (client_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def memory_texts(client_id: str, limit: int = 20) -> list[str]:
    return [row["content"] for row in list_memories(client_id, limit=limit)]


def create_memory(
    client_id: str,
    content: str,
    source_conversation_id: str | None = None,
) -> dict[str, Any]:
    text = content.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Memory content cannot be empty")
    with connection() as conn:
        row = conn.execute(
            """
            INSERT INTO user_memories (client_id, content, source_conversation_id)
            VALUES (%s, %s, %s::uuid)
            RETURNING
                id, content,
                source_conversation_id::text AS source_conversation_id,
                created_at, updated_at
            """,
            (client_id, text[:200], source_conversation_id),
        ).fetchone()
        conn.commit()
    return dict(row)


def delete_memory(memory_id: int, client_id: str) -> None:
    with connection() as conn:
        row = conn.execute(
            """
            DELETE FROM user_memories
            WHERE id = %s AND client_id = %s
            RETURNING id
            """,
            (memory_id, client_id),
        ).fetchone()
        conn.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Memory not found")


def format_memory_block(memories: list[str]) -> str:
    if not memories:
        return ""
    lines = "\n".join(f"- {item}" for item in memories)
    return (
        "\n\nKnown long-term user information (valid across chats; use when relevant):\n"
        f"{lines}"
    )


def _is_duplicate(candidate: str, existing: list[str]) -> bool:
    normalized = candidate.strip().lower()
    for item in existing:
        other = item.strip().lower()
        if normalized == other or normalized in other or other in normalized:
            return True
    return False


async def extract_and_store_memories(
    client_id: str,
    conversation_id: str,
    user_message: str,
    assistant_message: str,
) -> list[dict[str, Any]]:
    if not settings.openai_api_key:
        return []

    existing = memory_texts(client_id)
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )
    try:
        response = await client.responses.create(
            model=settings.openai_model,
            instructions=MEMORY_EXTRACT_PROMPT,
            input=(
                f"Existing memories:\n{json.dumps(existing, ensure_ascii=False)}\n\n"
                f"User: {user_message}\n\nAssistant: {assistant_message[:1200]}"
            ),
        )
        raw = (response.output_text or "").strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:].strip()
        data = json.loads(raw)
        candidates = data.get("memories", []) if isinstance(data, dict) else []
    except Exception:
        return []

    stored: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if len(text) < 4 or _is_duplicate(text, existing):
            continue
        memory = create_memory(client_id, text, conversation_id)
        existing.append(text)
        stored.append(memory)
        if len(stored) >= 3:
            break
    return stored
