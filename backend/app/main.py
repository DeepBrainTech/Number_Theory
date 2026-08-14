from __future__ import annotations

import asyncio
import json
import zipfile
from io import BytesIO
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from typing import Any
from xml.etree import ElementTree

from fastapi import Depends, FastAPI, File, HTTPException, Response, UploadFile
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
from .auth import (
    clear_session_cookie,
    current_user,
    set_session_cookie,
    upsert_google_user,
    verify_google_id_token,
)
from .config import settings
from .formalize import generate_proof_draft, propose_statement, verify_statement
from .lean_workspace import create_run as create_lean_run, get_run as get_lean_run, get_workspace, list_runs as list_lean_runs, save_workspace
from .auto_prove import (
    add_human_guidance,
    delete_run_artifacts,
    mark_run_cancelled,
    request_cancel,
    run_artifacts,
    run_auto_prove,
    subscribe_run_events,
    unsubscribe_run_events,
)
from .prove_runs import delete_run, get_run, list_runs, owned_run_id
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
from .schemas import (
    ChatRequest,
    ChatDocument,
    GuestChatRequest,
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
    LeanWorkbenchStateRequest,
    AutoProveGuidanceRequest,
    AutoProveReference,
    AutoProveRequest,
    AutoProveResponse,
    AutoProveRunOut,
    GoogleAuthRequest,
    UserOut,
    MemoryCreate,
    MemoryOut,
    MessageOut,
    NotebookCreate,
    NotebookEntryOut,
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
    title="Proof Lab API",
    version="0.5.0",
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


def _owned(payload: Any, user: dict[str, Any]) -> Any:
    if hasattr(payload, "client_id"):
        payload.client_id = user["id"]
    return payload


@app.get("/api/auth/me", response_model=UserOut)
def auth_me(user: dict[str, Any] = Depends(current_user)) -> UserOut:
    return UserOut(**user)


@app.post("/api/auth/google", response_model=UserOut)
def auth_google(request: GoogleAuthRequest, response: Response) -> UserOut:
    info = verify_google_id_token(request.id_token)
    user = upsert_google_user(
        sub=str(info["sub"]),
        email=info.get("email"),
        name=info.get("name"),
        picture=info.get("picture"),
    )
    set_session_cookie(response, user["id"])
    return UserOut(**user)


@app.post("/api/auth/logout")
def auth_logout(response: Response) -> dict[str, str]:
    clear_session_cookie(response)
    return {"status": "signed_out"}


@app.get("/api/conversations", response_model=list[ConversationOut])
def conversations_list(user: dict[str, Any] = Depends(current_user)) -> list[ConversationOut]:
    return [ConversationOut(**row) for row in list_conversations(user["id"])]


@app.post("/api/conversations", response_model=ConversationOut)
def conversations_create(
    request: ConversationCreate,
    user: dict[str, Any] = Depends(current_user),
) -> ConversationOut:
    _owned(request, user)
    return ConversationOut(**create_conversation(request.client_id, request.title))


@app.patch("/api/conversations/{conversation_id}", response_model=ConversationOut)
def conversations_rename(
    conversation_id: str,
    request: ConversationRename,
    user: dict[str, Any] = Depends(current_user),
) -> ConversationOut:
    ensure_uuid(conversation_id)
    _owned(request, user)
    return ConversationOut(
        **rename_conversation(conversation_id, request.client_id, request.title)
    )


@app.delete("/api/conversations/{conversation_id}")
def conversations_delete(
    conversation_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, str]:
    ensure_uuid(conversation_id)
    delete_conversation(conversation_id, user["id"])
    return {"status": "deleted"}


@app.get("/api/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def conversations_messages(
    conversation_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> list[MessageOut]:
    ensure_uuid(conversation_id)
    return [MessageOut(**row) for row in list_messages(conversation_id, user["id"])]


@app.get("/api/memories", response_model=list[MemoryOut])
def memories_list(user: dict[str, Any] = Depends(current_user)) -> list[MemoryOut]:
    return [MemoryOut(**row) for row in list_memories(user["id"])]


@app.post("/api/memories", response_model=MemoryOut)
def memories_create(
    request: MemoryCreate,
    user: dict[str, Any] = Depends(current_user),
) -> MemoryOut:
    _owned(request, user)
    return MemoryOut(**create_memory(request.client_id, request.content))


@app.delete("/api/memories/{memory_id}")
def memories_delete(
    memory_id: int,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, str]:
    delete_memory(memory_id, user["id"])
    return {"status": "deleted"}


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
    user_text = request.message.strip() or "\n".join(
        f"[Attached document: {document.name}]" for document in request.documents
    )
    add_message(conversation_id, "user", user_text, attachments=images)
    return conversation_id, history, memories, images, user_text, is_first_turn


def _chat_response(
    *,
    content: str,
    mode: str,
    gate: Any,
    tool_results: list[dict[str, Any]],
    conversation_id: str,
    teach_depth: str,
    new_memories: list[dict[str, Any]] | None = None,
) -> ChatResponse:
    answer_mode = mode if mode in {"general", "teach", "solve", "physics", "research", "retrieval"} else "general"
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

    content, mode, gate, tool_results = await answer(
        user_text,
        history=history,
        memories=memories,
        answer_mode=request.answer_mode,
        teach_depth=request.teach_depth,
        images=images or None,
        documents=[document.model_dump() for document in request.documents] or None,
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
        tool_results=tool_results,
        conversation_id=conversation_id,
        teach_depth=request.teach_depth,
        new_memories=[],
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat_api(
    request: ChatRequest,
    user: dict[str, Any] = Depends(current_user),
) -> ChatResponse:
    return await execute_chat(_owned(request, user))


@app.post("/api/chat/stream")
async def chat_stream_api(
    request: ChatRequest,
    user: dict[str, Any] = Depends(current_user),
) -> StreamingResponse:
    _owned(request, user)

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

                content, mode, tool_results, structure_notes = await generate_answer(
                    user_text,
                    history=history,
                    memories=memories,
                    answer_mode=request.answer_mode,
                    teach_depth=request.teach_depth,
                    images=images or None,
                    documents=[document.model_dump() for document in request.documents] or None,
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
                    tool_results=tool_results,
                    conversation_id=conversation_id,
                    teach_depth=request.teach_depth,
                )
                await emit({"type": "done", **response.model_dump(mode="json")})

                await on_status("gating", None)
                final_gate = await gate_answer(
                    user_text, content, tool_results, lean_code=None
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
        stream_finished = False
        try:
            while True:
                item = await queue.get()
                if item is None:
                    stream_finished = True
                    break
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
        finally:
            if not stream_finished and not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/formalize/statement", response_model=FormalizeStatementResponse)
async def formalize_statement_api(
    request: FormalizeStatementRequest,
    _user: dict[str, Any] = Depends(current_user),
) -> FormalizeStatementResponse:
    result = await propose_statement(request.question, request.method)
    return FormalizeStatementResponse(**result)


@app.get("/api/lean-workbench")
async def lean_workbench_get_api(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return get_workspace(user["id"]) or {}


@app.put("/api/lean-workbench")
async def lean_workbench_save_api(
    request: LeanWorkbenchStateRequest,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return save_workspace(user["id"], request.model_dump())


@app.get("/api/lean-workbench/runs")
async def lean_workbench_runs_api(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    return list_lean_runs(user["id"])


@app.get("/api/lean-workbench/runs/{run_id}")
async def lean_workbench_run_api(run_id: int, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    run = get_lean_run(run_id, user["id"])
    if run is None:
        raise HTTPException(status_code=404, detail="Lean workbench run not found")
    return run


@app.post("/api/lean-workbench/runs")
async def lean_workbench_run_create_api(
    request: LeanWorkbenchStateRequest,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return create_lean_run(user["id"], request.model_dump())


@app.post("/api/formalize/proof", response_model=FormalizeProofResponse)
async def formalize_proof_api(
    request: FormalizeProofRequest,
    _user: dict[str, Any] = Depends(current_user),
) -> FormalizeProofResponse:
    result = await generate_proof_draft(
        request.statement,
        question=request.question,
        method=request.method,
    )
    return FormalizeProofResponse(**result)


@app.post("/api/formalize/verify", response_model=FormalizeVerifyResponse)
async def formalize_verify_api(
    request: FormalizeVerifyRequest,
    _user: dict[str, Any] = Depends(current_user),
) -> FormalizeVerifyResponse:
    result = await verify_statement(
        request.question,
        request.statement,
        request.code,
        method=request.method,
    )
    return FormalizeVerifyResponse(**result)


_active_auto_prove_tasks: set[asyncio.Task[Any]] = set()
_SSE_KEEPALIVE_SECONDS = 15


def _sse_data(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _sse_from_queue(queue: asyncio.Queue[dict[str, Any] | None]):
    """Yield SSE packets, with keepalives so proxies do not drop idle runs."""
    while True:
        try:
            item = await asyncio.wait_for(queue.get(), timeout=_SSE_KEEPALIVE_SECONDS)
        except asyncio.TimeoutError:
            yield ": keepalive\n\n"
            continue
        if item is None:
            break
        yield _sse_data(item)
        if item.get("type") == "result":
            break


def _serialize_run(row: dict[str, Any]) -> AutoProveRunOut:
    return AutoProveRunOut(
        run_id=row["run_id"],
        problem=row["problem"],
        guidance=row.get("guidance") or "",
        depth=row.get("depth") or "quick",
        formalize=bool(row.get("formalize")),
        status=row["status"],
        phase=row.get("phase") or "",
        current_tool=row.get("current_tool") or "",
        difficulty=row.get("difficulty"),
        passed=row.get("passed"),
        proof_attempts=int(row.get("proof_attempts") or 0),
        revisions=int(row.get("revisions") or 0),
        decompositions=int(row.get("decompositions") or 0),
        error=row.get("error"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


_REFERENCE_FILE_LIMIT = 3 * 1024 * 1024
_REFERENCE_TEXT_LIMIT = 60_000
_REFERENCE_EXTENSIONS = {".txt", ".md", ".tex", ".bib", ".csv", ".json", ".pdf"}
_CHAT_DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


def _extract_chat_document(name: str, raw: bytes) -> str:
    suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(raw))
        content = "\n\n".join(page.extract_text() or "" for page in reader.pages)
    elif suffix == ".docx":
        with zipfile.ZipFile(BytesIO(raw)) as document:
            root = ElementTree.fromstring(document.read("word/document.xml"))
        content = "\n".join(text.strip() for text in root.itertext() if text.strip())
    else:
        content = raw.decode("utf-8", errors="replace")
    content = content.strip()
    if not content:
        raise ValueError("No readable text was found")
    return content[:_REFERENCE_TEXT_LIMIT]


@app.post("/api/chat/attachments/extract", response_model=ChatDocument)
async def chat_attachment_extract_api(file: UploadFile = File(...)) -> ChatDocument:
    """Extract bounded text from a document for the next chat turn."""
    name = (file.filename or "attachment").replace("\\", "/").split("/")[-1]
    suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if suffix not in _CHAT_DOCUMENT_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Use a PDF, Word (.docx), TXT, or Markdown file")
    raw = await file.read(_REFERENCE_FILE_LIMIT + 1)
    if len(raw) > _REFERENCE_FILE_LIMIT:
        raise HTTPException(status_code=413, detail="Each attachment must be 3 MB or smaller")
    try:
        content = _extract_chat_document(name, raw)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="This attachment could not be read as text") from exc
    return ChatDocument(name=name[:180], content=content)


@app.post("/api/auto-prove/references/extract", response_model=AutoProveReference)
async def auto_prove_reference_extract_api(
    file: UploadFile = File(...),
    _user: dict[str, Any] = Depends(current_user),
) -> AutoProveReference:
    """Extract a bounded, readable reference for inclusion in one proof run."""
    name = (file.filename or "reference").replace("\\", "/").split("/")[-1]
    suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if suffix not in _REFERENCE_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Use a PDF, TXT, Markdown, LaTeX, BibTeX, CSV, or JSON file")
    raw = await file.read(_REFERENCE_FILE_LIMIT + 1)
    if len(raw) > _REFERENCE_FILE_LIMIT:
        raise HTTPException(status_code=413, detail="Each reference file must be 3 MB or smaller")
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(raw))
            chunks: list[str] = []
            used = 0
            for page in reader.pages:
                text = page.extract_text() or ""
                remaining = _REFERENCE_TEXT_LIMIT - used
                if remaining <= 0:
                    break
                chunks.append(text[:remaining])
                used += len(chunks[-1])
            content = "\n\n".join(chunks).strip()
        except Exception as exc:
            raise HTTPException(status_code=422, detail="This PDF could not be read as text. Upload a text-based PDF or paste a link/summary.") from exc
    else:
        content = raw.decode("utf-8", errors="replace").strip()
    if not content:
        raise HTTPException(status_code=422, detail="No readable text was found in this reference")
    if len(content) > _REFERENCE_TEXT_LIMIT:
        content = content[:_REFERENCE_TEXT_LIMIT] + "\n\n[Reference truncated after 60,000 characters.]"
    return AutoProveReference(name=name[:180], content=content)


@app.get("/api/auto-prove/runs", response_model=list[AutoProveRunOut])
def auto_prove_runs_list(user: dict[str, Any] = Depends(current_user)) -> list[AutoProveRunOut]:
    return [_serialize_run(row) for row in list_runs(user["id"])]


@app.get("/api/auto-prove/runs/{run_id}")
async def auto_prove_run_api(
    run_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    meta = get_run(run_id, user["id"])
    if meta is None:
        raise HTTPException(status_code=404, detail="Auto Prove run not found")
    report = run_artifacts(run_id) or {"run_id": run_id, "files": []}
    return {**report, "meta": _serialize_run(meta).model_dump(mode="json")}


@app.delete("/api/auto-prove/runs/{run_id}")
async def auto_prove_run_delete_api(
    run_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, bool]:
    meta = get_run(run_id, user["id"])
    if meta is None:
        raise HTTPException(status_code=404, detail="Auto Prove run not found")
    if meta["status"] == "running":
        raise HTTPException(status_code=409, detail="Cancel a running Auto Prove run before deleting it")
    try:
        delete_run_artifacts(run_id)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not delete Auto Prove artifacts: {exc}") from exc
    if not delete_run(run_id, user["id"]):
        raise HTTPException(status_code=404, detail="Auto Prove run not found")
    return {"ok": True}


@app.post("/api/auto-prove/runs/{run_id}/guidance")
async def auto_prove_guidance_api(
    run_id: str,
    request: AutoProveGuidanceRequest,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, bool]:
    if not owned_run_id(run_id, user["id"]):
        raise HTTPException(status_code=404, detail="Auto Prove run not found")
    if not add_human_guidance(run_id, request.guidance):
        raise HTTPException(status_code=404, detail="Auto Prove run not found")
    return {"ok": True}


@app.post("/api/auto-prove/runs/{run_id}/cancel")
async def auto_prove_cancel_api(
    run_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    meta = get_run(run_id, user["id"])
    if meta is None:
        raise HTTPException(status_code=404, detail="Auto Prove run not found")
    if meta["status"] != "running":
        return {"ok": True, "cancelled": False, "status": meta["status"]}
    # Persist cancellation before waiting for a model/network call to unwind, so
    # the UI and account history reflect the user's action immediately.
    request_cancel(run_id)
    mark_run_cancelled(run_id, owner_id=user["id"])
    return {"ok": True, "cancelled": True, "status": "cancelled"}


@app.post("/api/auto-prove", response_model=AutoProveResponse)
async def auto_prove_api(
    request: AutoProveRequest,
    user: dict[str, Any] = Depends(current_user),
) -> AutoProveResponse:
    if request.resume and request.run_id and not owned_run_id(request.run_id, user["id"]):
        raise HTTPException(status_code=404, detail="Auto Prove run not found")
    result = await run_auto_prove(
        request.problem,
        request.guidance,
        request.depth,
        request.formalize,
        run_id=request.run_id,
        resume=request.resume,
        owner_id=user["id"],
        references=[reference.model_dump() for reference in request.references],
    )
    return AutoProveResponse(**result)


@app.post("/api/auto-prove/stream")
async def auto_prove_stream_api(
    request: AutoProveRequest,
    user: dict[str, Any] = Depends(current_user),
) -> StreamingResponse:
    if request.resume and request.run_id and not owned_run_id(request.run_id, user["id"]):
        raise HTTPException(status_code=404, detail="Auto Prove run not found")
    owner_id = user["id"]

    async def event_stream():
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def emit(phase: str, details: dict[str, Any]) -> None:
            await queue.put({"type": "status", "phase": phase, **details})

        async def worker() -> None:
            try:
                result = await run_auto_prove(
                    request.problem,
                    request.guidance,
                    request.depth,
                    request.formalize,
                    emit,
                    request.run_id,
                    request.resume,
                    owner_id=owner_id,
                    references=[reference.model_dump() for reference in request.references],
                )
                await queue.put({"type": "result", **result})
            finally:
                await queue.put(None)
                _active_auto_prove_tasks.discard(task)

        task = asyncio.create_task(worker())
        _active_auto_prove_tasks.add(task)
        try:
            async for packet in _sse_from_queue(queue):
                yield packet
        finally:
            # Closing a browser tab must not throw away a potentially long
            # research run. Its checkpoint and artifacts remain queryable.
            pass

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/api/auto-prove/runs/{run_id}/events")
async def auto_prove_run_events_api(
    run_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> StreamingResponse:
    """Resubscribe to an in-flight Auto Prove run after the original tab closed."""
    meta = get_run(run_id, user["id"])
    if meta is None:
        raise HTTPException(status_code=404, detail="Auto Prove run not found")
    owner_id = user["id"]

    async def event_stream():
        latest = get_run(run_id, owner_id)
        if latest is None:
            yield _sse_data({"type": "result", "ok": False, "error": "Auto Prove run not found", "run_id": run_id})
            return
        snapshot = {
            "type": "snapshot",
            "run_id": run_id,
            **_serialize_run(latest).model_dump(mode="json"),
        }
        yield _sse_data(snapshot)
        if latest["status"] != "running":
            report = run_artifacts(run_id) or {}
            result = report.get("result") or {
                "ok": latest["status"] != "failed",
                "error": latest.get("error"),
                "run_id": run_id,
            }
            yield _sse_data({"type": "result", **result, "run_id": run_id})
            return

        queue = subscribe_run_events(run_id)
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=_SSE_KEEPALIVE_SECONDS)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    current = get_run(run_id, owner_id)
                    if current is None or current["status"] != "running":
                        if current is not None:
                            yield _sse_data({
                                "type": "snapshot",
                                "run_id": run_id,
                                **_serialize_run(current).model_dump(mode="json"),
                            })
                        report = run_artifacts(run_id) or {}
                        result = report.get("result") or {
                            "ok": bool(current) and current["status"] == "complete",
                            "error": (current or {}).get("error"),
                            "run_id": run_id,
                        }
                        yield _sse_data({"type": "result", **result, "run_id": run_id})
                        break
                    yield _sse_data({
                        "type": "snapshot",
                        "run_id": run_id,
                        **_serialize_run(current).model_dump(mode="json"),
                    })
                    continue
                yield _sse_data(item)
                if item.get("type") == "result":
                    break
        finally:
            unsubscribe_run_events(run_id, queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/api/chat/guest/stream")
async def guest_chat_stream_api(request: GuestChatRequest) -> StreamingResponse:
    """Run a chat for a guest without creating conversations, messages, or memories in the database."""

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
                content, mode, tool_results, structure_notes = await generate_answer(
                    request.message.strip(),
                    history=[item.model_dump() for item in request.history],
                    memories=request.memories,
                    answer_mode=request.answer_mode,
                    teach_depth=request.teach_depth,
                    images=validate_images(request.images) or None,
                    documents=[document.model_dump() for document in request.documents] or None,
                    status_emitter=on_status,
                    delta_emitter=on_delta,
                    reset_emitter=on_reset,
                )
                gate = _apply_structure_notes(provisional_gate(), structure_notes)
                final_content = f"{gate.answer_prefix}{content}" if gate.answer_prefix else content
                if final_content != content:
                    await on_reset()
                    await on_delta(final_content)
                await emit(
                    {
                        "type": "done",
                        "answer": final_content,
                        "mode": mode,
                        "answer_mode": mode,
                        "verification": _legacy_verification(gate.level),
                        "verification_level": gate.level,
                        "verification_label": gate.label,
                        "verification_notes": gate.notes,
                        "tool_results": tool_results,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                await emit({"type": "error", "message": str(exc)})
            finally:
                await queue.put(None)

        task = asyncio.create_task(worker())
        stream_finished = False
        try:
            while True:
                item = await queue.get()
                if item is None:
                    stream_finished = True
                    break
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
        finally:
            if not stream_finished and not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/api/latex/from-image", response_model=LatexFromImageResponse)
async def latex_from_image_api(
    request: LatexFromImageRequest,
    _user: dict[str, Any] = Depends(current_user),
) -> LatexFromImageResponse:
    result = await image_to_latex(request.image)
    return LatexFromImageResponse(**result)


@app.post("/api/conversations/{conversation_id}/attach-verification", response_model=MessageOut)
def attach_verification(
    conversation_id: str,
    request: AttachVerificationRequest,
    user: dict[str, Any] = Depends(current_user),
) -> MessageOut:
    """Attach a Lean-workbench verification result to an existing chat transcript."""
    ensure_uuid(conversation_id)
    _owned(request, user)
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
    user: dict[str, Any] = Depends(current_user),
) -> Response:
    """Downloadable JSON log: every message with its gate level, notes, and tool calls."""
    ensure_uuid(conversation_id)
    conversation = get_conversation(conversation_id, user["id"])
    rows = list_messages(conversation_id, user["id"])
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
def notebook_list(user: dict[str, Any] = Depends(current_user)) -> list[NotebookEntryOut]:
    return [NotebookEntryOut(**row) for row in list_entries(user["id"])]


@app.get("/api/notebook/export")
def notebook_export(user: dict[str, Any] = Depends(current_user)) -> Response:
    payload = export_notebook(user["id"])
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="notebook-export.json"'},
    )


@app.post("/api/notebook", response_model=NotebookEntryOut)
def notebook_create(
    request: NotebookCreate,
    user: dict[str, Any] = Depends(current_user),
) -> NotebookEntryOut:
    _owned(request, user)
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
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, str]:
    delete_entry(entry_id, user["id"])
    return {"status": "deleted"}


@app.get("/api/tools/status")
async def tools_status() -> dict:
    status = await verifier_status()
    return status


@app.post("/api/tools/sage")
async def sage_api(request: SageRequest) -> dict:
    return await call_sage(request.model_dump())


@app.post("/api/tools/lean")
async def lean_api(request: LeanRequest) -> dict:
    return await call_lean(request.model_dump())
