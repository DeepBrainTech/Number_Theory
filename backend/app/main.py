from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from .chat import _legacy_verification, answer, suggest_title
from .config import settings
from .conversations import (
    add_message,
    create_conversation,
    delete_conversation,
    ensure_uuid,
    get_conversation,
    list_conversations,
    list_messages,
    message_count,
    recent_history,
    rename_conversation,
    touch_conversation,
)
from .db import connection, initialize_database
from .memory import (
    create_memory,
    delete_memory,
    extract_and_store_memories,
    list_memories,
    memory_texts,
)
from .retrieval import search
from .schemas import (
    ChatRequest,
    ChatResponse,
    ConversationCreate,
    ConversationOut,
    ConversationRename,
    LibraryStats,
    MemoryCreate,
    MemoryOut,
    MessageOut,
    SearchHit,
    SearchRequest,
    SageRequest,
    LeanRequest,
)
from .verification import call_lean, call_sage, verifier_status


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="Number Theory Agent API",
    version="0.3.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    with connection() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok"}


@app.get("/api/library/stats", response_model=LibraryStats)
def library_stats() -> LibraryStats:
    with connection() as conn:
        totals = conn.execute(
            """
            SELECT COUNT(DISTINCT d.id) AS documents,
                   COUNT(c.id) AS chunks,
                   MIN(d.page_start) AS page_start,
                   MAX(d.page_end) AS page_end,
                   MAX(d.embedding_model) AS embedding_model
            FROM documents d
            LEFT JOIN chunks c ON c.document_id = d.id
            """
        ).fetchone()
        rows = conn.execute(
            "SELECT block_type, COUNT(*) AS count FROM chunks GROUP BY block_type"
        ).fetchall()
    return LibraryStats(
        documents=totals["documents"],
        chunks=totals["chunks"],
        page_start=totals["page_start"],
        page_end=totals["page_end"],
        block_types={row["block_type"]: row["count"] for row in rows},
        embedding_model=totals["embedding_model"],
    )


@app.get("/api/conversations", response_model=list[ConversationOut])
def conversations_list(client_id: str = Query(min_length=8, max_length=64)) -> list[ConversationOut]:
    return [ConversationOut(**row) for row in list_conversations(client_id)]


@app.post("/api/conversations", response_model=ConversationOut)
def conversations_create(request: ConversationCreate) -> ConversationOut:
    return ConversationOut(**create_conversation(request.client_id, request.title))


@app.patch("/api/conversations/{conversation_id}", response_model=ConversationOut)
def conversations_rename(conversation_id: str, request: ConversationRename) -> ConversationOut:
    ensure_uuid(conversation_id)
    return ConversationOut(
        **rename_conversation(conversation_id, request.client_id, request.title)
    )


@app.delete("/api/conversations/{conversation_id}")
def conversations_delete(
    conversation_id: str,
    client_id: str = Query(min_length=8, max_length=64),
) -> dict[str, str]:
    ensure_uuid(conversation_id)
    delete_conversation(conversation_id, client_id)
    return {"status": "deleted"}


@app.get("/api/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def conversations_messages(
    conversation_id: str,
    client_id: str = Query(min_length=8, max_length=64),
) -> list[MessageOut]:
    ensure_uuid(conversation_id)
    return [MessageOut(**row) for row in list_messages(conversation_id, client_id)]


@app.get("/api/memories", response_model=list[MemoryOut])
def memories_list(client_id: str = Query(min_length=8, max_length=64)) -> list[MemoryOut]:
    return [MemoryOut(**row) for row in list_memories(client_id)]


@app.post("/api/memories", response_model=MemoryOut)
def memories_create(request: MemoryCreate) -> MemoryOut:
    return MemoryOut(**create_memory(request.client_id, request.content))


@app.delete("/api/memories/{memory_id}")
def memories_delete(
    memory_id: int,
    client_id: str = Query(min_length=8, max_length=64),
) -> dict[str, str]:
    delete_memory(memory_id, client_id)
    return {"status": "deleted"}


@app.post("/api/search", response_model=list[SearchHit])
def search_api(request: SearchRequest) -> list[SearchHit]:
    return [SearchHit(**hit) for hit in search(request.query, request.limit)]


@app.post("/api/chat", response_model=ChatResponse)
async def chat_api(request: ChatRequest) -> ChatResponse:
    if request.conversation_id:
        conversation_id = ensure_uuid(request.conversation_id)
        get_conversation(conversation_id, request.client_id)
    else:
        conversation = create_conversation(request.client_id)
        conversation_id = conversation["id"]

    history = recent_history(conversation_id, limit=12)
    memories = memory_texts(request.client_id)
    is_first_turn = message_count(conversation_id) == 0

    add_message(conversation_id, "user", request.message)

    hits = search(request.message, request.limit)
    content, mode, gate, tool_results = await answer(
        request.message,
        hits,
        history=history,
        memories=memories,
    )

    add_message(
        conversation_id,
        "assistant",
        content,
        verification_level=gate.level,
        verification_label=gate.label,
        verification_notes=gate.notes,
        tool_results=tool_results,
    )

    if is_first_turn:
        touch_conversation(conversation_id, title=suggest_title(request.message))
    else:
        touch_conversation(conversation_id)

    new_memories = await extract_and_store_memories(
        request.client_id,
        conversation_id,
        request.message,
        content,
    )

    return ChatResponse(
        answer=content,
        mode=mode,
        verification=_legacy_verification(gate.level),
        verification_level=gate.level,
        verification_label=gate.label,
        verification_notes=gate.notes,
        lean_aligned=gate.lean_aligned,
        premise_ok=gate.premise_ok,
        retrieved_chunks=len(hits),
        tool_results=tool_results,
        conversation_id=conversation_id,
        new_memories=new_memories,
    )


@app.get("/api/tools/status")
async def tools_status() -> dict:
    status = await verifier_status()
    status["embedding"] = {
        "model": settings.openai_embedding_model,
        "configured": bool(settings.openai_api_key),
        "dimensions": 1536,
    }
    return status


@app.post("/api/tools/sage")
async def sage_api(request: SageRequest) -> dict:
    return await call_sage(request.model_dump())


@app.post("/api/tools/lean")
async def lean_api(request: LeanRequest) -> dict:
    return await call_lean(request.model_dump())
