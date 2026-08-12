"""Per-user Auto Prove run index (metadata in Postgres; artifacts on disk)."""

from __future__ import annotations

from typing import Any

from .db import connection


def create_run(
    *,
    run_id: str,
    client_id: str,
    problem: str,
    guidance: str = "",
    depth: str = "quick",
    formalize: bool = False,
) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute(
            """
            INSERT INTO auto_prove_runs (
                run_id, client_id, problem, guidance, depth, formalize, status, phase
            )
            VALUES (%s, %s, %s, %s, %s, %s, 'running', 'starting')
            ON CONFLICT (run_id) DO UPDATE SET
                updated_at = NOW()
            RETURNING
                run_id, client_id, problem, guidance, depth, formalize,
                status, phase, difficulty, passed,
                proof_attempts, revisions, decompositions, error,
                created_at, updated_at
            """,
            (run_id, client_id, problem, guidance, depth, formalize),
        ).fetchone()
        conn.commit()
    return dict(row)


def touch_run(
    run_id: str,
    client_id: str,
    *,
    status: str | None = None,
    phase: str | None = None,
    difficulty: str | None = None,
    passed: bool | None = None,
    proof_attempts: int | None = None,
    revisions: int | None = None,
    decompositions: int | None = None,
    error: str | None = None,
) -> dict[str, Any] | None:
    fields: list[str] = ["updated_at = NOW()"]
    values: list[Any] = []
    if status is not None:
        fields.append("status = %s")
        values.append(status)
    if phase is not None:
        fields.append("phase = %s")
        values.append(phase)
    if difficulty is not None:
        fields.append("difficulty = %s")
        values.append(difficulty)
    if passed is not None:
        fields.append("passed = %s")
        values.append(passed)
    if proof_attempts is not None:
        fields.append("proof_attempts = %s")
        values.append(proof_attempts)
    if revisions is not None:
        fields.append("revisions = %s")
        values.append(revisions)
    if decompositions is not None:
        fields.append("decompositions = %s")
        values.append(decompositions)
    if error is not None:
        fields.append("error = %s")
        values.append(error)
    values.extend([run_id, client_id])
    with connection() as conn:
        row = conn.execute(
            f"""
            UPDATE auto_prove_runs
            SET {", ".join(fields)}
            WHERE run_id = %s AND client_id = %s
            RETURNING
                run_id, client_id, problem, guidance, depth, formalize,
                status, phase, difficulty, passed,
                proof_attempts, revisions, decompositions, error,
                created_at, updated_at
            """,
            values,
        ).fetchone()
        conn.commit()
    return dict(row) if row else None


def get_run(run_id: str, client_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT
                run_id, client_id, problem, guidance, depth, formalize,
                status, phase, difficulty, passed,
                proof_attempts, revisions, decompositions, error,
                created_at, updated_at
            FROM auto_prove_runs
            WHERE run_id = %s AND client_id = %s
            """,
            (run_id, client_id),
        ).fetchone()
    return dict(row) if row else None


def list_runs(client_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT
                run_id, client_id, problem, guidance, depth, formalize,
                status, phase, difficulty, passed,
                proof_attempts, revisions, decompositions, error,
                created_at, updated_at
            FROM auto_prove_runs
            WHERE client_id = %s
            ORDER BY updated_at DESC
            LIMIT %s
            """,
            (client_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def owned_run_id(run_id: str, client_id: str) -> bool:
    return get_run(run_id, client_id) is not None
