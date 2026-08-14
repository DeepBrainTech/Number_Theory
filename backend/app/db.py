from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from .config import settings


SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        google_sub TEXT UNIQUE NOT NULL,
        email TEXT,
        name TEXT,
        picture TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS conversations (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        client_id TEXT NOT NULL,
        title TEXT NOT NULL DEFAULT 'New chat',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS conversations_client_updated_idx
        ON conversations(client_id, updated_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        id BIGSERIAL PRIMARY KEY,
        conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
        content TEXT NOT NULL,
        verification_level TEXT,
        verification_label TEXT,
        verification_notes JSONB,
        tool_results JSONB,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS messages_conversation_idx
        ON messages(conversation_id, id)
    """,
    """
    ALTER TABLE messages
        ADD COLUMN IF NOT EXISTS attachments JSONB NOT NULL DEFAULT '[]'::jsonb
    """,
    """
    CREATE TABLE IF NOT EXISTS user_memories (
        id BIGSERIAL PRIMARY KEY,
        client_id TEXT NOT NULL,
        content TEXT NOT NULL,
        source_conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS user_memories_client_idx
        ON user_memories(client_id, updated_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS notebook_entries (
        id BIGSERIAL PRIMARY KEY,
        client_id TEXT NOT NULL,
        kind TEXT NOT NULL
            CHECK (kind IN ('experiment', 'conjecture', 'counterexample')),
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS notebook_entries_client_idx
        ON notebook_entries(client_id, created_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS auto_prove_runs (
        run_id TEXT PRIMARY KEY,
        client_id TEXT NOT NULL,
        problem TEXT NOT NULL,
        guidance TEXT NOT NULL DEFAULT '',
        depth TEXT NOT NULL DEFAULT 'quick',
        formalize BOOLEAN NOT NULL DEFAULT FALSE,
        status TEXT NOT NULL DEFAULT 'running',
        phase TEXT NOT NULL DEFAULT '',
        current_tool TEXT NOT NULL DEFAULT '',
        difficulty TEXT,
        passed BOOLEAN,
        proof_attempts INT NOT NULL DEFAULT 0,
        revisions INT NOT NULL DEFAULT 0,
        decompositions INT NOT NULL DEFAULT 0,
        error TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS auto_prove_runs_client_idx
        ON auto_prove_runs(client_id, updated_at DESC)
    """,
    """
    ALTER TABLE auto_prove_runs
        ADD COLUMN IF NOT EXISTS current_tool TEXT NOT NULL DEFAULT ''
    """,
    """
    CREATE TABLE IF NOT EXISTS lean_workbench_states (
        client_id TEXT PRIMARY KEY,
        question TEXT NOT NULL DEFAULT '',
        method TEXT NOT NULL DEFAULT '',
        statement TEXT NOT NULL DEFAULT '',
        explanation TEXT NOT NULL DEFAULT '',
        caveats JSONB NOT NULL DEFAULT '[]'::jsonb,
        code TEXT NOT NULL DEFAULT '',
        result JSONB,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS lean_workbench_runs (
        id BIGSERIAL PRIMARY KEY,
        client_id TEXT NOT NULL,
        question TEXT NOT NULL,
        method TEXT NOT NULL DEFAULT '',
        statement TEXT NOT NULL DEFAULT '',
        explanation TEXT NOT NULL DEFAULT '',
        caveats JSONB NOT NULL DEFAULT '[]'::jsonb,
        code TEXT NOT NULL,
        result JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS lean_workbench_runs_client_idx
        ON lean_workbench_runs(client_id, created_at DESC)
    """,
]


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        yield conn


def wait_for_database(attempts: int = 30, delay_seconds: float = 1.0) -> None:
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            with connection() as conn:
                conn.execute("SELECT 1")
            return
        except psycopg.OperationalError as exc:
            last_error = exc
            time.sleep(delay_seconds)
    raise RuntimeError("Database did not become ready") from last_error


def initialize_database() -> None:
    wait_for_database()
    with connection() as conn:
        conn.execute("DROP TABLE IF EXISTS chunk_deps CASCADE")
        conn.execute("DROP TABLE IF EXISTS chunks CASCADE")
        conn.execute("DROP TABLE IF EXISTS documents CASCADE")
        for statement in SCHEMA_STATEMENTS:
            conn.execute(statement)
        conn.commit()
