from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

from openai import OpenAI

from .config import settings
from .embedding import as_pgvector, embed, lexical_query
from .expansion import expand_math_concepts


# Structure-aware boost: definitions and theorem statements are the backbone
# of a math answer, so they outrank surrounding exposition at equal fusion score.
BLOCK_WEIGHTS: dict[str, float] = {
    "definition": 1.30,
    "theorem": 1.25,
    "proof": 1.10,
    "example": 1.05,
    "exercise": 0.90,
    "hint": 0.85,
    "exposition": 1.00,
}

STRUCTURED_BLOCK_TYPES = ("definition", "theorem")

CHUNK_COLUMNS = "id, block_type, heading, content, pdf_page, printed_page, parent_ordinal"

RERANK_PROMPT = (
    "You rerank retrieved number-theory passages for a query. "
    "Prefer passages stating the definitions/theorems the query needs; penalize tangents. "
    'Output JSON only: {"order": [indices best first]} using the given zero-based indices.'
)


def _fts_rows(conn, fts_query: str, limit: int, block_types: tuple[str, ...] | None = None):
    filter_sql = ""
    params: list[Any] = [fts_query, fts_query]
    if block_types:
        filter_sql = "AND block_type = ANY(%s)"
        params.append(list(block_types))
    params.append(limit)
    return conn.execute(
        f"""
        SELECT {CHUNK_COLUMNS},
               ts_rank_cd(content_tsv, websearch_to_tsquery('english', %s)) AS raw_score
        FROM chunks
        WHERE content_tsv @@ websearch_to_tsquery('english', %s)
        {filter_sql}
        ORDER BY raw_score DESC, id
        LIMIT %s
        """,
        params,
    ).fetchall()


def _vector_rows(conn, vector: str, limit: int):
    return conn.execute(
        f"""
        SELECT {CHUNK_COLUMNS},
               1 - (embedding <=> %s::vector) AS raw_score
        FROM chunks
        ORDER BY embedding <=> %s::vector, id
        LIMIT %s
        """,
        (vector, vector, limit),
    ).fetchall()


def fuse_channels(
    channels: list[tuple[list[dict], float]],
    limit: int,
    *,
    rrf_k: int = 60,
) -> list[dict]:
    """Weighted reciprocal-rank fusion with block-type boosting."""
    by_id: dict[int, dict] = {}
    fused: defaultdict[int, float] = defaultdict(float)
    for rows, weight in channels:
        for rank, row in enumerate(rows, start=1):
            chunk_id = row["id"]
            by_id[chunk_id] = dict(row)
            fused[chunk_id] += weight / (rrf_k + rank)

    for chunk_id, row in by_id.items():
        fused[chunk_id] *= BLOCK_WEIGHTS.get(row["block_type"], 1.0)

    ordered = sorted(fused, key=lambda chunk_id: fused[chunk_id], reverse=True)[:limit]
    results: list[dict] = []
    for chunk_id in ordered:
        row = by_id[chunk_id]
        results.append(
            {
                "chunk_id": chunk_id,
                "score": round(fused[chunk_id], 6),
                "block_type": row["block_type"],
                "heading": row["heading"],
                "content": row["content"],
                "pdf_page": row["pdf_page"],
                "printed_page": row["printed_page"],
                "parent_ordinal": row.get("parent_ordinal"),
            }
        )
    return results


def _llm_rerank(query: str, results: list[dict]) -> list[dict]:
    if len(results) < 3:
        return results
    snippets = [
        {
            "index": index,
            "block_type": item["block_type"],
            "heading": item["heading"],
            "text": item["content"][:300],
        }
        for index, item in enumerate(results)
    ]
    client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
    response = client.responses.create(
        model=settings.openai_model,
        instructions=RERANK_PROMPT,
        input=json.dumps({"query": query, "passages": snippets}, ensure_ascii=False),
    )
    text = (response.output_text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL)
    data = json.loads(text)
    order = data.get("order") if isinstance(data, dict) else None
    if not isinstance(order, list):
        return results
    seen: list[int] = []
    for value in order:
        if isinstance(value, int) and 0 <= value < len(results) and value not in seen:
            seen.append(value)
    for index in range(len(results)):
        if index not in seen:
            seen.append(index)
    return [results[index] for index in seen]


def search(query: str, limit: int = 5) -> list[dict]:
    from .db import connection  # local import keeps this module importable without psycopg

    concepts = expand_math_concepts(query)
    concept_text = " ".join(concepts)

    fts_query = lexical_query(query)
    concept_fts = lexical_query(concept_text) if concept_text else ""
    structured_source = " ".join(filter(None, [query, concept_text]))
    structured_fts = lexical_query(structured_source)

    candidate_limit = max(limit * 4, 20)

    with connection() as conn:
        channels: list[tuple[list[dict], float]] = []
        if fts_query:
            channels.append((_fts_rows(conn, fts_query, candidate_limit), 1.4))
        if concept_fts and concept_fts != fts_query:
            channels.append((_fts_rows(conn, concept_fts, candidate_limit), 0.8))
        if structured_fts:
            channels.append(
                (
                    _fts_rows(conn, structured_fts, candidate_limit, STRUCTURED_BLOCK_TYPES),
                    1.0,
                )
            )
        if settings.openai_api_key:
            vector = as_pgvector(embed(structured_source or query))
            channels.append((_vector_rows(conn, vector, candidate_limit), 1.0))

    results = fuse_channels(channels, max(limit * 2, limit))

    # Soft-boost chunks that are dependency-neighbors of the top hits.
    try:
        from .dependencies import neighbor_boost_ids

        boosts = neighbor_boost_ids([item["chunk_id"] for item in results[:8]])
        if boosts:
            by_id = {item["chunk_id"]: item for item in results}
            for chunk_id, boost in boosts.items():
                if chunk_id in by_id:
                    by_id[chunk_id]["score"] = round(by_id[chunk_id]["score"] + boost, 6)
            results = sorted(by_id.values(), key=lambda item: item["score"], reverse=True)
    except Exception:  # noqa: BLE001 - deps table may be empty / unavailable
        pass

    results = results[:limit]

    if settings.rerank_llm and settings.openai_api_key:
        try:
            results = _llm_rerank(query, results)
        except Exception:  # noqa: BLE001 - rerank must never break retrieval
            pass
    return results
