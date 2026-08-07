from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from .db import connection


def create_conversation(client_id: str, title: str = "New chat") -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute(
            """
            INSERT INTO conversations (client_id, title)
            VALUES (%s, %s)
            RETURNING id::text AS id, client_id, title, created_at, updated_at
            """,
            (client_id, title),
        ).fetchone()
        conn.commit()
    return dict(row)


def list_conversations(client_id: str, limit: int = 50) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT id::text AS id, title, created_at, updated_at
            FROM conversations
            WHERE client_id = %s
            ORDER BY updated_at DESC
            LIMIT %s
            """,
            (client_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def get_conversation(conversation_id: str, client_id: str) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT id::text AS id, client_id, title, created_at, updated_at
            FROM conversations
            WHERE id = %s::uuid AND client_id = %s
            """,
            (conversation_id, client_id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return dict(row)


def rename_conversation(conversation_id: str, client_id: str, title: str) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute(
            """
            UPDATE conversations
            SET title = %s, updated_at = NOW()
            WHERE id = %s::uuid AND client_id = %s
            RETURNING id::text AS id, title, created_at, updated_at
            """,
            (title.strip()[:80] or "New chat", conversation_id, client_id),
        ).fetchone()
        conn.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return dict(row)


def delete_conversation(conversation_id: str, client_id: str) -> None:
    with connection() as conn:
        row = conn.execute(
            """
            DELETE FROM conversations
            WHERE id = %s::uuid AND client_id = %s
            RETURNING id
            """,
            (conversation_id, client_id),
        ).fetchone()
        conn.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Conversation not found")


def touch_conversation(conversation_id: str, title: str | None = None) -> None:
    with connection() as conn:
        if title:
            conn.execute(
                """
                UPDATE conversations
                SET updated_at = NOW(), title = %s
                WHERE id = %s::uuid
                """,
                (title[:80], conversation_id),
            )
        else:
            conn.execute(
                "UPDATE conversations SET updated_at = NOW() WHERE id = %s::uuid",
                (conversation_id,),
            )
        conn.commit()


def add_message(
    conversation_id: str,
    role: str,
    content: str,
    *,
    attachments: list[str] | None = None,
    verification_level: str | None = None,
    verification_label: str | None = None,
    verification_notes: list[str] | None = None,
    tool_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute(
            """
            INSERT INTO messages (
                conversation_id, role, content, attachments,
                verification_level, verification_label, verification_notes, tool_results
            )
            VALUES (
                %s::uuid, %s, %s, %s::jsonb, %s, %s, %s::jsonb, %s::jsonb
            )
            RETURNING
                id, conversation_id::text AS conversation_id, role, content, attachments,
                verification_level, verification_label, verification_notes, tool_results,
                created_at
            """,
            (
                conversation_id,
                role,
                content,
                json.dumps(attachments or [], ensure_ascii=False),
                verification_level,
                verification_label,
                json.dumps(verification_notes or [], ensure_ascii=False),
                json.dumps(tool_results or [], ensure_ascii=False),
            ),
        ).fetchone()
        conn.commit()
    return _normalize_message(dict(row))


def update_message(
    message_id: int,
    *,
    content: str | None = None,
    verification_level: str | None = None,
    verification_label: str | None = None,
    verification_notes: list[str] | None = None,
) -> dict[str, Any]:
    assignments: list[str] = []
    values: list[Any] = []
    if content is not None:
        assignments.append("content = %s")
        values.append(content)
    if verification_level is not None:
        assignments.append("verification_level = %s")
        values.append(verification_level)
    if verification_label is not None:
        assignments.append("verification_label = %s")
        values.append(verification_label)
    if verification_notes is not None:
        assignments.append("verification_notes = %s::jsonb")
        values.append(json.dumps(verification_notes, ensure_ascii=False))
    if not assignments:
        raise ValueError("No message fields to update")
    values.append(message_id)
    with connection() as conn:
        row = conn.execute(
            f"""
            UPDATE messages
            SET {", ".join(assignments)}
            WHERE id = %s
            RETURNING
                id, conversation_id::text AS conversation_id, role, content, attachments,
                verification_level, verification_label, verification_notes, tool_results,
                created_at
            """,
            tuple(values),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Message not found")
        conn.commit()
    return _normalize_message(dict(row))


def list_messages(conversation_id: str, client_id: str) -> list[dict[str, Any]]:
    get_conversation(conversation_id, client_id)
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT
                id, conversation_id::text AS conversation_id, role, content, attachments,
                verification_level, verification_label, verification_notes, tool_results,
                created_at
            FROM messages
            WHERE conversation_id = %s::uuid
            ORDER BY id ASC
            """,
            (conversation_id,),
        ).fetchall()
    return [_normalize_message(dict(row)) for row in rows]


def recent_history(conversation_id: str, limit: int = 12) -> list[dict[str, str]]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT role, content
            FROM (
                SELECT role, content, id
                FROM messages
                WHERE conversation_id = %s::uuid
                  AND role IN ('user', 'assistant')
                ORDER BY id DESC
                LIMIT %s
            ) recent
            ORDER BY id ASC
            """,
            (conversation_id, limit),
        ).fetchall()
    return [{"role": row["role"], "content": row["content"]} for row in rows]


def message_count(conversation_id: str) -> int:
    with connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM messages WHERE conversation_id = %s::uuid",
            (conversation_id,),
        ).fetchone()
    return int(row["count"]) if row else 0


def ensure_uuid(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid conversation ID") from exc


def _normalize_message(row: dict[str, Any]) -> dict[str, Any]:
    notes = row.get("verification_notes")
    tools = row.get("tool_results")
    attachments = row.get("attachments")
    if isinstance(notes, str):
        notes = json.loads(notes)
    if isinstance(tools, str):
        tools = json.loads(tools)
    if isinstance(attachments, str):
        attachments = json.loads(attachments)
    row["verification_notes"] = notes or []
    row["tool_results"] = tools or []
    row["attachments"] = attachments or []
    return row
