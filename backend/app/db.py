from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from .config import settings
from .embedding import DIMENSIONS, MODEL_NAME


SCHEMA_STATEMENTS = [
    "CREATE EXTENSION IF NOT EXISTS vector",
    """
    CREATE TABLE IF NOT EXISTS documents (
        id TEXT PRIMARY KEY,
        filename TEXT NOT NULL,
        title TEXT NOT NULL,
        author TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        page_start INTEGER NOT NULL,
        page_end INTEGER NOT NULL,
        embedding_model TEXT NOT NULL,
        ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    f"""
    CREATE TABLE IF NOT EXISTS chunks (
        id BIGSERIAL PRIMARY KEY,
        document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        ordinal INTEGER NOT NULL,
        pdf_page INTEGER NOT NULL,
        printed_page INTEGER,
        chapter TEXT NOT NULL,
        section TEXT,
        block_type TEXT NOT NULL,
        heading TEXT,
        content TEXT NOT NULL,
        content_tsv TSVECTOR GENERATED ALWAYS AS (
            to_tsvector('english', coalesce(heading, '') || ' ' || content)
        ) STORED,
        embedding VECTOR({DIMENSIONS}) NOT NULL,
        UNIQUE(document_id, ordinal)
    )
    """,
    "CREATE INDEX IF NOT EXISTS chunks_content_tsv_idx ON chunks USING GIN(content_tsv)",
    "CREATE INDEX IF NOT EXISTS chunks_document_idx ON chunks(document_id, ordinal)",
    """
    CREATE INDEX IF NOT EXISTS chunks_embedding_idx
        ON chunks USING hnsw (embedding vector_cosine_ops)
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


def _embedding_dimension(conn: psycopg.Connection) -> int | None:
    row = conn.execute(
        """
        SELECT format_type(a.atttypid, a.atttypmod) AS typ
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relname = 'chunks'
          AND a.attname = 'embedding'
          AND NOT a.attisdropped
        """
    ).fetchone()
    if not row or not row["typ"]:
        return None
    text = str(row["typ"])
    if text.startswith("vector(") and text.endswith(")"):
        try:
            return int(text[len("vector(") : -1])
        except ValueError:
            return None
    return None


def _ensure_embedding_schema(conn: psycopg.Connection) -> None:
    exists = conn.execute(
        "SELECT to_regclass('public.chunks') IS NOT NULL AS present"
    ).fetchone()
    if not exists or not exists["present"]:
        return

    dims = _embedding_dimension(conn)
    stale_models = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM documents
        WHERE embedding_model NOT IN (%s, %s)
        """,
        (MODEL_NAME, settings.openai_embedding_model),
    ).fetchone()
    needs_rebuild = dims != DIMENSIONS or (stale_models and stale_models["count"] > 0)
    if not needs_rebuild:
        return

    # Dimension or embedding model changed: wipe derived data so ingest can rebuild.
    conn.execute("DROP TABLE IF EXISTS chunks CASCADE")
    conn.execute("DROP TABLE IF EXISTS documents CASCADE")


def initialize_database() -> None:
    wait_for_database()
    with connection() as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        _ensure_embedding_schema(conn)
        for statement in SCHEMA_STATEMENTS:
            conn.execute(statement)
        conn.commit()
