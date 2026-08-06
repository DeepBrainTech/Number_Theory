from __future__ import annotations

from collections import defaultdict

from .db import connection
from .embedding import as_pgvector, embed, lexical_query


def search(query: str, limit: int = 5) -> list[dict]:
    fts_query = lexical_query(query)
    vector = as_pgvector(embed(query))
    candidate_limit = max(limit * 4, 20)

    with connection() as conn:
        lexical = conn.execute(
            """
            SELECT id, block_type, heading, content, pdf_page, printed_page,
                   ts_rank_cd(content_tsv, websearch_to_tsquery('english', %s)) AS raw_score
            FROM chunks
            WHERE content_tsv @@ websearch_to_tsquery('english', %s)
            ORDER BY raw_score DESC, id
            LIMIT %s
            """,
            (fts_query, fts_query, candidate_limit),
        ).fetchall()
        vector_hits = conn.execute(
            """
            SELECT id, block_type, heading, content, pdf_page, printed_page,
                   1 - (embedding <=> %s::vector) AS raw_score
            FROM chunks
            ORDER BY embedding <=> %s::vector, id
            LIMIT %s
            """,
            (vector, vector, candidate_limit),
        ).fetchall()

    by_id: dict[int, dict] = {}
    fused: defaultdict[int, float] = defaultdict(float)
    for rank, row in enumerate(lexical, start=1):
        chunk_id = row["id"]
        by_id[chunk_id] = dict(row)
        fused[chunk_id] += 1.4 / (60 + rank)
    for rank, row in enumerate(vector_hits, start=1):
        chunk_id = row["id"]
        by_id[chunk_id] = dict(row)
        fused[chunk_id] += 1.0 / (60 + rank)

    ordered_ids = sorted(fused, key=lambda chunk_id: fused[chunk_id], reverse=True)[:limit]
    results: list[dict] = []
    for chunk_id in ordered_ids:
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
            }
        )
    return results
