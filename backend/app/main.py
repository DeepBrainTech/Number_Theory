from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .chat import (
    StatusEmitter,
    _apply_structure_notes,
    _legacy_verification,
    answer,
    generate_answer,
    provisional_gate,
    suggest_title,
    validate_images,
)
from .config import settings
from .formalize import generate_proof_draft, propose_statement, verify_statement
from .gating import gate_answer
from .latex_ocr import image_to_latex
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
    update_message,
)
from .db import connection, initialize_database
from .memory import (
    create_memory,
    delete_memory,
    extract_and_store_memories,
    list_memories,
    memory_texts,
)
from .notebook import create_entry, delete_entry, export_notebook, list_entries
from .retrieval import search
from .schemas import (
    ChatRequest,
    ChatResponse,
    ConversationCreate,
    ConversationOut,
    ConversationRename,
    AttachVerificationRequest,
    FormalizeProofRequest,
    FormalizeProofResponse,
    FormalizeStatementRequest,
    FormalizeStatementResponse,
    FormalizeVerifyRequest,
    FormalizeVerifyResponse,
    LibraryStats,
    MemoryCreate,
    MemoryOut,
    MessageOut,
    NotebookCreate,
    NotebookEntryOut,
    SearchHit,
    SearchRequest,
    SageRequest,
    LeanRequest,
    LatexFromImageRequest,
    LatexFromImageResponse,
)
from .verification import call_lean, call_sage, verifier_status


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="Number Theory Agent API",
    version="0.4.0",
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


def _prepare_chat(request: ChatRequest) -> tuple[str, list[dict[str, str]], list[str], list[str], str, bool]:
    if request.conversation_id:
        conversation_id = ensure_uuid(request.conversation_id)
        get_conversation(conversation_id, request.client_id)
    else:
        conversation = create_conversation(request.client_id)
        conversation_id = conversation["id"]

    history = recent_history(conversation_id, limit=12)
    memories = memory_texts(request.client_id)
    is_first_turn = message_count(conversation_id) == 0
    images = validate_images(request.images)
    user_text = request.message.strip()
    add_message(conversation_id, "user", user_text, attachments=images)
    return conversation_id, history, memories, images, user_text, is_first_turn


def _chat_response(
    *,
    content: str,
    mode: str,
    gate: Any,
    hits_count: int,
    tool_results: list[dict[str, Any]],
    conversation_id: str,
    teach_depth: str,
    new_memories: list[dict[str, Any]] | None = None,
) -> ChatResponse:
    answer_mode = mode if mode in {"teach", "solve", "research", "retrieval"} else "teach"
    return ChatResponse(
        answer=content,
        mode=mode,
        answer_mode=answer_mode,
        verification=_legacy_verification(gate.level),
        verification_level=gate.level,
        verification_label=gate.label,
        verification_notes=gate.notes,
        lean_aligned=gate.lean_aligned,
        premise_ok=gate.premise_ok,
        retrieved_chunks=hits_count,
        tool_results=tool_results,
        conversation_id=conversation_id,
        new_memories=new_memories or [],
        teach_depth=teach_depth,  # type: ignore[arg-type]
    )


async def _store_memories_background(
    client_id: str,
    conversation_id: str,
    user_message: str,
    assistant_message: str,
) -> None:
    try:
        await extract_and_store_memories(
            client_id,
            conversation_id,
            user_message,
            assistant_message,
        )
    except Exception:  # noqa: BLE001 - background task must not raise
        return


async def execute_chat(request: ChatRequest, status_emitter: StatusEmitter | None = None) -> ChatResponse:
    conversation_id, history, memories, images, user_text, is_first_turn = _prepare_chat(request)

    search_query = user_text or "number theory mathematics"
    if status_emitter is not None:
        await status_emitter("retrieving", None)
    hits = await asyncio.to_thread(search, search_query, request.limit)
    content, mode, gate, tool_results = await answer(
        user_text,
        hits,
        history=history,
        memories=memories,
        answer_mode=request.answer_mode,
        teach_depth=request.teach_depth,
        images=images or None,
        status_emitter=status_emitter,
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
        touch_conversation(conversation_id, title=suggest_title(user_text or "Image message"))
    else:
        touch_conversation(conversation_id)

    # Memory extraction must not delay the HTTP response.
    asyncio.create_task(
        _store_memories_background(
            request.client_id,
            conversation_id,
            request.message or user_text,
            content,
        )
    )

    return _chat_response(
        content=content,
        mode=mode,
        gate=gate,
        hits_count=len(hits),
        tool_results=tool_results,
        conversation_id=conversation_id,
        teach_depth=request.teach_depth,
        new_memories=[],
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat_api(request: ChatRequest) -> ChatResponse:
    return await execute_chat(request)


@app.post("/api/chat/stream")
async def chat_stream_api(request: ChatRequest) -> StreamingResponse:
    async def event_stream():
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def emit(event: dict[str, Any]) -> None:
            await queue.put(event)

        async def on_status(phase: str, detail: str | None = None) -> None:
            await emit({"type": "status", "phase": phase, "detail": detail})

        async def on_delta(text: str) -> None:
            await emit({"type": "delta", "text": text})

        async def on_reset() -> None:
            await emit({"type": "reset"})

        async def worker() -> None:
            try:
                conversation_id, history, memories, images, user_text, is_first_turn = _prepare_chat(
                    request
                )
                search_query = user_text or "number theory mathematics"
                await on_status("retrieving", None)
                hits = await asyncio.to_thread(search, search_query, request.limit)

                content, mode, tool_results, structure_notes = await generate_answer(
                    user_text,
                    hits,
                    history=history,
                    memories=memories,
                    answer_mode=request.answer_mode,
                    teach_depth=request.teach_depth,
                    images=images or None,
                    status_emitter=on_status,
                    delta_emitter=on_delta,
                    reset_emitter=on_reset,
                )

                # Return the answer immediately; gate LLM calls continue afterwards.
                gate = _apply_structure_notes(provisional_gate(), structure_notes)
                provisional_content = (
                    f"{gate.answer_prefix}{content}" if gate.answer_prefix else content
                )
                if provisional_content != content:
                    await on_reset()
                    await on_delta(provisional_content)

                stored = add_message(
                    conversation_id,
                    "assistant",
                    provisional_content,
                    verification_level=gate.level,
                    verification_label=gate.label,
                    verification_notes=gate.notes,
                    tool_results=tool_results,
                )

                if is_first_turn:
                    touch_conversation(
                        conversation_id, title=suggest_title(user_text or "Image message")
                    )
                else:
                    touch_conversation(conversation_id)

                response = _chat_response(
                    content=provisional_content,
                    mode=mode,
                    gate=gate,
                    hits_count=len(hits),
                    tool_results=tool_results,
                    conversation_id=conversation_id,
                    teach_depth=request.teach_depth,
                )
                await emit({"type": "done", **response.model_dump(mode="json")})

                await on_status("gating", None)
                final_gate = await gate_answer(
                    search_query, content, tool_results, lean_code=None
                )
                final_gate = _apply_structure_notes(final_gate, structure_notes)
                final_content = (
                    f"{final_gate.answer_prefix}{content}"
                    if final_gate.answer_prefix
                    else content
                )
                update_message(
                    stored["id"],
                    content=final_content,
                    verification_level=final_gate.level,
                    verification_label=final_gate.label,
                    verification_notes=final_gate.notes,
                )
                await emit(
                    {
                        "type": "gate",
                        "answer": final_content,
                        "verification": _legacy_verification(final_gate.level),
                        "verification_level": final_gate.level,
                        "verification_label": final_gate.label,
                        "verification_notes": final_gate.notes,
                        "lean_aligned": final_gate.lean_aligned,
                        "premise_ok": final_gate.premise_ok,
                        "message_id": stored["id"],
                    }
                )

                asyncio.create_task(
                    _store_memories_background(
                        request.client_id,
                        conversation_id,
                        request.message or user_text,
                        final_content,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                await emit({"type": "error", "message": str(exc)})
            finally:
                await queue.put(None)

        task = asyncio.create_task(worker())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
        finally:
            await task

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/formalize/statement", response_model=FormalizeStatementResponse)
async def formalize_statement_api(request: FormalizeStatementRequest) -> FormalizeStatementResponse:
    result = await propose_statement(request.question, request.method)
    return FormalizeStatementResponse(**result)


@app.post("/api/formalize/proof", response_model=FormalizeProofResponse)
async def formalize_proof_api(request: FormalizeProofRequest) -> FormalizeProofResponse:
    result = await generate_proof_draft(
        request.statement,
        question=request.question,
        method=request.method,
    )
    return FormalizeProofResponse(**result)


@app.post("/api/formalize/verify", response_model=FormalizeVerifyResponse)
async def formalize_verify_api(request: FormalizeVerifyRequest) -> FormalizeVerifyResponse:
    result = await verify_statement(
        request.question,
        request.statement,
        request.code,
        method=request.method,
    )
    return FormalizeVerifyResponse(**result)


@app.post("/api/latex/from-image", response_model=LatexFromImageResponse)
async def latex_from_image_api(request: LatexFromImageRequest) -> LatexFromImageResponse:
    result = await image_to_latex(request.image)
    return LatexFromImageResponse(**result)


@app.post("/api/conversations/{conversation_id}/attach-verification", response_model=MessageOut)
def attach_verification(
    conversation_id: str,
    request: AttachVerificationRequest,
) -> MessageOut:
    """Attach a Lean-workbench verification result to an existing chat transcript."""
    ensure_uuid(conversation_id)
    get_conversation(conversation_id, request.client_id)
    add_message(
        conversation_id,
        "assistant",
        request.content,
        verification_level=request.verification_level,
        verification_label=request.verification_label or request.verification_level,
        verification_notes=request.verification_notes,
        tool_results=request.tool_results,
    )
    touch_conversation(conversation_id)
    rows = list_messages(conversation_id, request.client_id)
    return MessageOut(**rows[-1])


@app.get("/api/conversations/{conversation_id}/verification-log")
def verification_log(
    conversation_id: str,
    client_id: str = Query(min_length=8, max_length=64),
) -> Response:
    """Downloadable JSON log: every message with its gate level, notes, and tool calls."""
    ensure_uuid(conversation_id)
    conversation = get_conversation(conversation_id, client_id)
    rows = list_messages(conversation_id, client_id)
    payload = {
        "conversation_id": conversation_id,
        "title": conversation["title"],
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "messages": [
            {
                "id": row["id"],
                "role": row["role"],
                "content": row["content"],
                "verification_level": row.get("verification_level"),
                "verification_label": row.get("verification_label"),
                "verification_notes": row.get("verification_notes") or [],
                "tool_results": row.get("tool_results") or [],
                "created_at": row["created_at"].isoformat(),
            }
            for row in rows
        ],
    }
    filename = f"verification-log-{conversation_id[:8]}.json"
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/notebook", response_model=list[NotebookEntryOut])
def notebook_list(client_id: str = Query(min_length=8, max_length=64)) -> list[NotebookEntryOut]:
    return [NotebookEntryOut(**row) for row in list_entries(client_id)]


@app.get("/api/notebook/export")
def notebook_export(client_id: str = Query(min_length=8, max_length=64)) -> Response:
    payload = export_notebook(client_id)
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="notebook-export.json"'},
    )


@app.post("/api/notebook", response_model=NotebookEntryOut)
def notebook_create(request: NotebookCreate) -> NotebookEntryOut:
    return NotebookEntryOut(
        **create_entry(
            request.client_id,
            request.kind,
            request.title,
            request.content,
            request.payload,
        )
    )


@app.delete("/api/notebook/{entry_id}")
def notebook_delete(
    entry_id: int,
    client_id: str = Query(min_length=8, max_length=64),
) -> dict[str, str]:
    delete_entry(entry_id, client_id)
    return {"status": "deleted"}


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
