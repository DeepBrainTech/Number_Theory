from __future__ import annotations

from datetime import datetime
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
    client_id: str = Field(min_length=8, max_length=64)
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    answer: str
    mode: str
    verification: str
    verification_level: str
    verification_label: str
    verification_notes: list[str] = Field(default_factory=list)
    lean_aligned: bool | None = None
    premise_ok: bool = False
    retrieved_chunks: int
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    conversation_id: str
    new_memories: list[dict[str, Any]] = Field(default_factory=list)


class ConversationCreate(BaseModel):
    client_id: str = Field(min_length=8, max_length=64)
    title: str = Field(default="New chat", max_length=80)


class ConversationRename(BaseModel):
    client_id: str = Field(min_length=8, max_length=64)
    title: str = Field(min_length=1, max_length=80)


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    id: int
    conversation_id: str
    role: str
    content: str
    verification_level: str | None = None
    verification_label: str | None = None
    verification_notes: list[str] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime


class MemoryCreate(BaseModel):
    client_id: str = Field(min_length=8, max_length=64)
    content: str = Field(min_length=1, max_length=200)


class MemoryOut(BaseModel):
    id: int
    content: str
    source_conversation_id: str | None = None
    created_at: datetime
    updated_at: datetime


class ClientQuery(BaseModel):
    client_id: str = Field(min_length=8, max_length=64)


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
    embedding_model: str | None = None
