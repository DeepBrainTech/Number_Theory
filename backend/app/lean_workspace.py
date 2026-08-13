"""Account-scoped persistence for the Lean workbench draft."""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Json

from .db import connection


def get_workspace(client_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            """SELECT question, method, statement, explanation, caveats, code, result, updated_at
               FROM lean_workbench_states WHERE client_id = %s""",
            (client_id,),
        ).fetchone()
    return dict(row) if row else None


def save_workspace(client_id: str, state: dict[str, Any]) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute(
            """
            INSERT INTO lean_workbench_states
                (client_id, question, method, statement, explanation, caveats, code, result)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (client_id) DO UPDATE SET
                question = EXCLUDED.question, method = EXCLUDED.method,
                statement = EXCLUDED.statement, explanation = EXCLUDED.explanation,
                caveats = EXCLUDED.caveats, code = EXCLUDED.code,
                result = EXCLUDED.result, updated_at = NOW()
            RETURNING question, method, statement, explanation, caveats, code, result, updated_at
            """,
            (
                client_id, state["question"], state["method"], state["statement"],
                state["explanation"], Json(state["caveats"]), state["code"],
                Json(state["result"]) if state["result"] is not None else None,
            ),
        ).fetchone()
        conn.commit()
    return dict(row)


def create_run(client_id: str, state: dict[str, Any]) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute(
            """
            INSERT INTO lean_workbench_runs
                (client_id, question, method, statement, explanation, caveats, code, result)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, question, method, statement, explanation, caveats, code, result, created_at
            """,
            (
                client_id, state["question"], state["method"], state["statement"],
                state["explanation"], Json(state["caveats"]), state["code"],
                Json(state["result"] or {}),
            ),
        ).fetchone()
        conn.commit()
    return dict(row)


def list_runs(client_id: str, limit: int = 50) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """SELECT id, question, statement, result, created_at
               FROM lean_workbench_runs WHERE client_id = %s
               ORDER BY created_at DESC LIMIT %s""",
            (client_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def get_run(run_id: int, client_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            """SELECT id, question, method, statement, explanation, caveats, code, result, created_at
               FROM lean_workbench_runs WHERE id = %s AND client_id = %s""",
            (run_id, client_id),
        ).fetchone()
    return dict(row) if row else None
