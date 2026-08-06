from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=20)


class SearchHit(BaseModel):
    chunk_id: int
    score: float
    block_type: str
    heading: str | None
    content: str
    pdf_page: int
    printed_page: int | None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=5, ge=1, le=10)


class ChatResponse(BaseModel):
    answer: str
    mode: str
    verification: str
    retrieved_chunks: int
    tool_results: list[dict[str, Any]] = Field(default_factory=list)


class SageRequest(BaseModel):
    operation: str
    arguments: list[str]
    split: int | None = None


class LeanRequest(BaseModel):
    code: str = Field(min_length=1, max_length=12000)


class LibraryStats(BaseModel):
    documents: int
    chunks: int
    page_start: int | None
    page_end: int | None
    block_types: dict[str, int]
