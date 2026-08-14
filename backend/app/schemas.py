from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class GoogleAuthRequest(BaseModel):
    id_token: str = Field(min_length=20, max_length=10000)


class UserOut(BaseModel):
    id: str
    email: str | None = None
    name: str | None = None
    picture: str | None = None


class ChatDocument(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    content: str = Field(min_length=1, max_length=60_000)


class ChatRequest(BaseModel):
    message: str = Field(default="", max_length=4000)
    images: list[str] = Field(default_factory=list, max_length=4)
    documents: list[ChatDocument] = Field(default_factory=list, max_length=4)
    client_id: str = Field(default="", max_length=64)
    conversation_id: str | None = None
    answer_mode: Literal["auto", "general", "teach", "solve", "physics", "research"] = "auto"
    teach_depth: Literal["hint", "socratic", "full"] = "full"

    @model_validator(mode="after")
    def require_text_or_images(self) -> ChatRequest:
        if not self.message.strip() and not self.images and not self.documents:
            raise ValueError("message, images, or documents required")
        return self


class GuestHistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=12000)


class GuestChatRequest(BaseModel):
    """A browser-only chat request. It is never written to PostgreSQL."""

    message: str = Field(default="", max_length=4000)
    images: list[str] = Field(default_factory=list, max_length=4)
    documents: list[ChatDocument] = Field(default_factory=list, max_length=4)
    answer_mode: Literal["auto", "general", "teach", "solve", "physics", "research"] = "auto"
    teach_depth: Literal["hint", "socratic", "full"] = "full"
    history: list[GuestHistoryMessage] = Field(default_factory=list, max_length=12)
    memories: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def require_text_or_images(self) -> GuestChatRequest:
        if not self.message.strip() and not self.images and not self.documents:
            raise ValueError("message, images, or documents required")
        return self


class ChatResponse(BaseModel):
    answer: str
    mode: str
    answer_mode: Literal["general", "teach", "solve", "physics", "research", "retrieval"]
    verification: str
    verification_level: str
    verification_label: str
    verification_notes: list[str] = Field(default_factory=list)
    lean_aligned: bool | None = None
    premise_ok: bool = False
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    conversation_id: str
    new_memories: list[dict[str, Any]] = Field(default_factory=list)
    teach_depth: Literal["hint", "socratic", "full"] = "full"


class ConversationCreate(BaseModel):
    client_id: str = Field(default="", max_length=64)
    title: str = Field(default="New chat", max_length=80)


class ConversationRename(BaseModel):
    client_id: str = Field(default="", max_length=64)
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
    client_id: str = Field(default="", max_length=64)
    content: str = Field(min_length=1, max_length=200)


class MemoryOut(BaseModel):
    id: int
    content: str
    source_conversation_id: str | None = None
    created_at: datetime
    updated_at: datetime


class ClientQuery(BaseModel):
    client_id: str = Field(default="", max_length=64)


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


class LeanWorkbenchStateRequest(BaseModel):
    question: str = Field(default="", max_length=4000)
    method: str = Field(default="", max_length=4000)
    statement: str = Field(default="", max_length=8000)
    explanation: str = Field(default="", max_length=8000)
    caveats: list[str] = Field(default_factory=list, max_length=20)
    code: str = Field(default="", max_length=12000)
    result: dict[str, Any] | None = None


class AutoProveReference(BaseModel):
    """Extracted reference material supplied with an Auto Prove run."""

    name: str = Field(min_length=1, max_length=180)
    content: str = Field(min_length=1, max_length=60_000)


class AutoProveRequest(BaseModel):
    """A bounded QED-style proof search request.

    Separate from chat: several model calls with tools, a three-level retry
    loop, and no unbounded conversation history.
    """

    problem: str = Field(min_length=1, max_length=8000)
    guidance: str = Field(default="", max_length=4000)
    references: list[AutoProveReference] = Field(default_factory=list, max_length=4)
    depth: Literal["quick", "deep"] = "quick"
    formalize: bool = False
    run_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{12}$")
    resume: bool = False


class AutoProveGuidanceRequest(BaseModel):
    guidance: str = Field(min_length=1, max_length=4000)


class AutoProveRunOut(BaseModel):
    run_id: str
    problem: str
    guidance: str = ""
    depth: str = "quick"
    formalize: bool = False
    status: str
    phase: str = ""
    difficulty: str | None = None
    passed: bool | None = None
    proof_attempts: int = 0
    revisions: int = 0
    decompositions: int = 0
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class AutoProveResponse(BaseModel):
    ok: bool
    proof: str | None = None
    plan: str | None = None
    review: list[str] = Field(default_factory=list)
    revisions: int = 0
    proof_attempts: int = 0
    decompositions: int = 0
    difficulty: str | None = None
    related_work: str | None = None
    passed: bool | None = None
    run_id: str | None = None
    run_dir: str | None = None
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
    client_id: str = Field(default="", max_length=64)
    content: str = Field(min_length=1, max_length=20000)
    verification_level: str = Field(default="V0", max_length=32)
    verification_label: str = Field(default="", max_length=200)
    verification_notes: list[str] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)


class NotebookCreate(BaseModel):
    client_id: str = Field(default="", max_length=64)
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


