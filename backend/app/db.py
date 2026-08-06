from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from .config import settings


SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

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
);

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
    embedding VECTOR(384) NOT NULL,
    UNIQUE(document_id, ordinal)
);

CREATE INDEX IF NOT EXISTS chunks_content_tsv_idx ON chunks USING GIN(content_tsv);
CREATE INDEX IF NOT EXISTS chunks_document_idx ON chunks(document_id, ordinal);
CREATE INDEX IF NOT EXISTS chunks_embedding_idx
    ON chunks USING hnsw (embedding vector_cosine_ops);
"""


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
        conn.execute(SCHEMA_SQL)
        conn.commit()
