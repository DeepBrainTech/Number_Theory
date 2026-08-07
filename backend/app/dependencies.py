"""Chunk dependency edges: uses_definition / uses_lemma / uses_theorem / proves.

Two sources:
1. Structural: proof chunks with parent_ordinal → proves(target=theorem).
2. LLM-assisted: for theorem/proof chunks, pick nearby definition/theorem/lemma
   chunks in the same document that the text likely depends on.

Edges live in chunk_deps and are used as a soft retrieval boost.
"""

from __future__ import annotations

import argparse
import json
import re
from typing import Any

from openai import OpenAI

from .config import settings
from .db import connection, initialize_database


RELATIONS = ("uses_definition", "uses_lemma", "uses_theorem", "proves")

EXTRACT_PROMPT = (
    "You link a number-theory chunk to the definitions/lemmas/theorems it uses. "
    "Candidates are numbered. Output JSON only: "
    '{"links":[{"candidate_index":int,"relation":"uses_definition|uses_lemma|uses_theorem"}]} '
    "with at most 4 links. Only link candidates that are clearly used; prefer empty over guessing."
)


def _client() -> OpenAI:
    return OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)


def sync_structural_proves() -> int:
    """Insert proves edges from proof.parent_ordinal → theorem chunk."""
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT p.id AS source_id, t.id AS target_id
            FROM chunks p
            JOIN chunks t
              ON t.document_id = p.document_id
             AND t.ordinal = p.parent_ordinal
            WHERE p.block_type = 'proof'
              AND p.parent_ordinal IS NOT NULL
              AND t.block_type IN ('theorem', 'definition')
            """
        ).fetchall()
        inserted = 0
        for row in rows:
            result = conn.execute(
                """
                INSERT INTO chunk_deps (source_chunk_id, target_chunk_id, relation, confidence)
                VALUES (%s, %s, 'proves', 1.0)
                ON CONFLICT (source_chunk_id, target_chunk_id, relation) DO NOTHING
                RETURNING id
                """,
                (row["source_id"], row["target_id"]),
            ).fetchone()
            if result:
                inserted += 1
        conn.commit()
    return inserted


def _candidate_pool(conn, document_id: str, ordinal: int, limit: int = 12) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT id, ordinal, block_type, heading, LEFT(content, 280) AS snippet
        FROM chunks
        WHERE document_id = %s
          AND block_type IN ('definition', 'theorem')
          AND ordinal < %s
        ORDER BY ordinal DESC
        LIMIT %s
        """,
        (document_id, ordinal, limit),
    ).fetchall()


def _llm_links(source_text: str, candidates: list[dict[str, Any]]) -> list[tuple[int, str]]:
    if not settings.openai_api_key or not candidates:
        return []
    payload = {
        "source": source_text[:1200],
        "candidates": [
            {
                "index": index,
                "block_type": row["block_type"],
                "heading": row["heading"],
                "text": row["snippet"],
            }
            for index, row in enumerate(candidates)
        ],
    }
    try:
        response = _client().responses.create(
            model=settings.openai_model,
            instructions=EXTRACT_PROMPT,
            input=json.dumps(payload, ensure_ascii=False),
        )
        text = (response.output_text or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL)
        data = json.loads(text)
        links = data.get("links") if isinstance(data, dict) else None
        if not isinstance(links, list):
            return []
        out: list[tuple[int, str]] = []
        for item in links[:4]:
            if not isinstance(item, dict):
                continue
            index = item.get("candidate_index")
            relation = item.get("relation")
            if (
                isinstance(index, int)
                and 0 <= index < len(candidates)
                and relation in {"uses_definition", "uses_lemma", "uses_theorem"}
            ):
                # lemmas are stored as theorem block_type in our chunker
                if relation == "uses_lemma" and candidates[index]["block_type"] != "theorem":
                    relation = "uses_definition"
                if relation == "uses_definition" and candidates[index]["block_type"] == "theorem":
                    relation = "uses_theorem"
                out.append((index, relation))
        return out
    except Exception:  # noqa: BLE001 - extraction is best-effort
        return []


def extract_for_document(document_id: str, *, limit: int = 40) -> int:
    """LLM-extract dependency edges for theorem/proof chunks in one document."""
    with connection() as conn:
        sources = conn.execute(
            """
            SELECT id, ordinal, block_type, heading, content
            FROM chunks
            WHERE document_id = %s
              AND block_type IN ('theorem', 'proof')
            ORDER BY ordinal
            LIMIT %s
            """,
            (document_id, limit),
        ).fetchall()
        inserted = 0
        for source in sources:
            candidates = _candidate_pool(conn, document_id, source["ordinal"])
            if not candidates:
                continue
            source_text = " ".join(
                filter(None, [source["heading"], source["content"]])
            )
            for index, relation in _llm_links(source_text, candidates):
                target = candidates[index]
                result = conn.execute(
                    """
                    INSERT INTO chunk_deps
                        (source_chunk_id, target_chunk_id, relation, confidence)
                    VALUES (%s, %s, %s, 0.7)
                    ON CONFLICT (source_chunk_id, target_chunk_id, relation) DO NOTHING
                    RETURNING id
                    """,
                    (source["id"], target["id"], relation),
                ).fetchone()
                if result:
                    inserted += 1
        conn.commit()
    return inserted


def extract_all(*, per_document: int = 40) -> dict[str, int]:
    initialize_database()
    structural = sync_structural_proves()
    with connection() as conn:
        docs = conn.execute("SELECT id FROM documents ORDER BY id").fetchall()
    llm_total = 0
    for doc in docs:
        llm_total += extract_for_document(doc["id"], limit=per_document)
    return {"structural_proves": structural, "llm_links": llm_total, "documents": len(docs)}


def neighbor_boost_ids(chunk_ids: list[int]) -> dict[int, float]:
    """Return {related_chunk_id: boost} for chunks linked to any of chunk_ids."""
    if not chunk_ids:
        return {}
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT target_chunk_id AS id, MAX(confidence) AS conf
            FROM chunk_deps
            WHERE source_chunk_id = ANY(%s)
            GROUP BY target_chunk_id
            UNION
            SELECT source_chunk_id AS id, MAX(confidence) AS conf
            FROM chunk_deps
            WHERE target_chunk_id = ANY(%s)
            GROUP BY source_chunk_id
            """,
            (chunk_ids, chunk_ids),
        ).fetchall()
    return {int(row["id"]): float(row["conf"]) * 0.15 for row in rows}


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract chunk dependency edges")
    parser.add_argument("--document", help="Only process one document_id")
    parser.add_argument("--per-document", type=int, default=40)
    parser.add_argument("--structural-only", action="store_true")
    args = parser.parse_args()
    initialize_database()
    if args.structural_only:
        print({"structural_proves": sync_structural_proves()})
        return
    if args.document:
        structural = sync_structural_proves()
        llm = extract_for_document(args.document, limit=args.per_document)
        print({"structural_proves": structural, "llm_links": llm, "document": args.document})
        return
    print(extract_all(per_document=args.per_document))


if __name__ == "__main__":
    main()
