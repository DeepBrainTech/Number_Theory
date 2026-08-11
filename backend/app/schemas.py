from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


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
    parent_ordinal: int | None = None


class ChatRequest(BaseModel):
    message: str = Field(default="", max_length=4000)
    images: list[str] = Field(default_factory=list, max_length=4)
    limit: int = Field(default=5, ge=1, le=10)
    client_id: str = Field(min_length=8, max_length=64)
    conversation_id: str | None = None
    answer_mode: Literal["auto", "teach", "solve", "research"] = "auto"
    teach_depth: Literal["hint", "socratic", "full"] = "full"

    @model_validator(mode="after")
    def require_text_or_images(self) -> ChatRequest:
        if not self.message.strip() and not self.images:
            raise ValueError("message or images required")
        return self


class ChatResponse(BaseModel):
    answer: str
    mode: str
    answer_mode: Literal["teach", "solve", "research", "retrieval"]
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
    teach_depth: Literal["hint", "socratic", "full"] = "full"


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
    attachments: list[str] = Field(default_factory=list)
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


class FormalizeStatementRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    method: str = Field(default="", max_length=4000)


class FormalizeStatementResponse(BaseModel):
    ok: bool
    statement: str | None = None
    display_code: str | None = None
    explanation: str | None = None
    caveats: list[str] = Field(default_factory=list)
    error: str | None = None


class FormalizeProofRequest(BaseModel):
    question: str = Field(default="", max_length=4000)
    statement: str = Field(min_length=1, max_length=8000)
    method: str = Field(default="", max_length=4000)


class FormalizeProofResponse(BaseModel):
    ok: bool
    code: str | None = None
    error: str | None = None


class FormalizeVerifyRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    statement: str = Field(default="", max_length=8000)
    code: str | None = Field(default=None, max_length=12000)
    method: str = Field(default="", max_length=4000)


class FormalizeVerifyResponse(BaseModel):
    ok: bool
    verified: bool = False
    aligned: bool | None = None
    level: str | None = None
    statement: str | None = None
    code: str | None = None
    output: str | None = None
    notes: list[str] = Field(default_factory=list)
    error: str | None = None


class AutoProveRequest(BaseModel):
    """A bounded natural-language proof search request.

    This is deliberately separate from chat: proof search makes several model
    calls and must not inherit an unbounded conversation history.
    """

    problem: str = Field(min_length=1, max_length=8000)
    guidance: str = Field(default="", max_length=4000)
    depth: Literal["quick", "deep"] = "quick"
    formalize: bool = False


class AutoProveResponse(BaseModel):
    ok: bool
    proof: str | None = None
    plan: str | None = None
    review: list[str] = Field(default_factory=list)
    revisions: int = 0
    formalization: dict[str, Any] | None = None
    error: str | None = None


class LatexFromImageRequest(BaseModel):
    image: str = Field(
        min_length=32,
        max_length=6_000_000,
        description="Base64 image bytes or data:image/...;base64,... URL",
    )


class LatexFromImageResponse(BaseModel):
    ok: bool
    latex: str | None = None
    display: bool = False
    wrapped: str | None = None
    confidence: str | None = None
    notes: list[str] = Field(default_factory=list)
    error: str | None = None


class AttachVerificationRequest(BaseModel):
    client_id: str = Field(min_length=8, max_length=64)
    content: str = Field(min_length=1, max_length=20000)
    verification_level: str = Field(default="V0", max_length=32)
    verification_label: str = Field(default="", max_length=200)
    verification_notes: list[str] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)


class NotebookCreate(BaseModel):
    client_id: str = Field(min_length=8, max_length=64)
    kind: Literal["experiment", "conjecture", "counterexample"]
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=8000)
    payload: dict[str, Any] = Field(default_factory=dict)


class NotebookEntryOut(BaseModel):
    id: int
    kind: Literal["experiment", "conjecture", "counterexample"]
    title: str
    content: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class LibraryStats(BaseModel):
    documents: int
    chunks: int
    page_start: int | None
    page_end: int | None
    block_types: dict[str, int]
    embedding_model: str | None = None
