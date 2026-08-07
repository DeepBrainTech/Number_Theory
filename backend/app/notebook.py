"""Persistent experiment notebook: experiments, conjectures, counterexamples."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from psycopg.types.json import Json

from .db import connection

EntryKind = Literal["experiment", "conjecture", "counterexample"]


def list_entries(client_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT id, kind, title, content, payload, created_at
            FROM notebook_entries
            WHERE client_id = %s
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            (client_id, limit),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if item.get("payload") is None:
            item["payload"] = {}
        out.append(item)
    return out


def create_entry(
    client_id: str,
    kind: EntryKind,
    title: str,
    content: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if kind not in {"experiment", "conjecture", "counterexample"}:
        raise ValueError(f"invalid kind: {kind}")
    title = title.strip()[:160] or kind
    content = content.strip()
    if not content:
        raise ValueError("content is required")
    with connection() as conn:
        row = conn.execute(
            """
            INSERT INTO notebook_entries (client_id, kind, title, content, payload)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, kind, title, content, payload, created_at
            """,
            (client_id, kind, title, content, Json(payload or {})),
        ).fetchone()
        conn.commit()
    result = dict(row)
    if result.get("payload") is None:
        result["payload"] = {}
    return result


def delete_entry(entry_id: int, client_id: str) -> None:
    with connection() as conn:
        conn.execute(
            "DELETE FROM notebook_entries WHERE id = %s AND client_id = %s",
            (entry_id, client_id),
        )
        conn.commit()


def export_notebook(client_id: str) -> dict[str, Any]:
    entries = list_entries(client_id, limit=500)
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "client_id": client_id,
        "count": len(entries),
        "entries": [
            {
                "id": item["id"],
                "kind": item["kind"],
                "title": item["title"],
                "content": item["content"],
                "payload": item["payload"] or {},
                "created_at": item["created_at"].isoformat(),
            }
            for item in entries
        ],
    }
