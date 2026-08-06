from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .chat import _legacy_verification, answer
from .config import settings
from .db import connection, initialize_database
from .retrieval import search
from .schemas import (
    ChatRequest,
    ChatResponse,
    LibraryStats,
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
    version="0.2.0",
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


@app.post("/api/search", response_model=list[SearchHit])
def search_api(request: SearchRequest) -> list[SearchHit]:
    return [SearchHit(**hit) for hit in search(request.query, request.limit)]


@app.post("/api/chat", response_model=ChatResponse)
async def chat_api(request: ChatRequest) -> ChatResponse:
    hits = search(request.message, request.limit)
    content, mode, gate, tool_results = await answer(request.message, hits)
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
