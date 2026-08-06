from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .db import connection, initialize_database
from .embedding import MODEL_NAME, as_pgvector, embed_texts


DEFAULT_FILENAME = "1017984325-Introduction-to-Number-Theory-2026 (1).pdf"


@dataclass
class Chunk:
    ordinal: int
    pdf_page: int
    printed_page: int
    section: str | None
    block_type: str
    heading: str | None
    content: str


def extract_page(pdf_path: Path, page: int) -> str:
    result = subprocess.run(
        [
            "pdftotext",
            "-f",
            str(page),
            "-l",
            str(page),
            "-layout",
            "-enc",
            "UTF-8",
            str(pdf_path),
            "-",
        ],
        check=True,
        capture_output=True,
    )
    return result.stdout.decode("utf-8", errors="replace")


def clean_page(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\x0c", "").splitlines()]
    filtered: list[str] = []
    for line in lines:
        stripped = line.strip()
        if re.fullmatch(r"\d+", stripped):
            continue
        if stripped in {"Introduction to Number Theory", "Euclid’s Algorithm"}:
            continue
        filtered.append(line)
    return "\n".join(filtered).strip()


def classify(text: str) -> tuple[str, str | None]:
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if re.match(r"^(Theorem|Lemma|Corollary|Proposition)\b", first):
        return "theorem", first
    if re.match(r"^Proof\b", first, re.IGNORECASE):
        return "proof", first
    example = re.search(r"\bExample\.", text[:500])
    if example:
        return "example", text[example.start() :].split(".", 1)[0] + "."
    if re.match(r"^Exercise\b", first):
        return "exercise", first
    if re.match(r"^Definition\b", first) or first.endswith("Axioms."):
        return "definition", first
    if "Hints for Some Exercises" in first:
        return "hint", first
    return "exposition", None


def split_long_paragraph(paragraph: str, max_chars: int = 1800) -> list[str]:
    if len(paragraph) <= max_chars:
        return [paragraph]
    sentences = re.split(r"(?<=[.!?□])\s+(?=[A-Z(])", paragraph)
    parts: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > max_chars:
            parts.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def build_chunks(pdf_path: Path, start_page: int, end_page: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    ordinal = 0
    current_section: str | None = None
    section_pattern = re.compile(r"^(1\.\d+)\s+(.+)$")

    for pdf_page in range(start_page, end_page + 1):
        page_text = clean_page(extract_page(pdf_path, pdf_page))
        paragraphs = [
            re.sub(r"[ \t]+", " ", paragraph.replace("\n", " ")).strip()
            for paragraph in re.split(r"\n\s*\n", page_text)
            if paragraph.strip()
        ]
        for paragraph in paragraphs:
            section_match = section_pattern.match(paragraph)
            if section_match and len(paragraph) < 140:
                current_section = f"{section_match.group(1)} {section_match.group(2).title()}"
                continue
            if paragraph.startswith("Chapter 1") or paragraph == "Euclid’s Algorithm":
                continue
            for part in split_long_paragraph(paragraph):
                if len(part) < 40:
                    continue
                block_type, heading = classify(part)
                chunks.append(
                    Chunk(
                        ordinal=ordinal,
                        pdf_page=pdf_page,
                        printed_page=pdf_page - 15,
                        section=current_section,
                        block_type=block_type,
                        heading=heading,
                        content=part,
                    )
                )
                ordinal += 1
    return chunks


def ingest(pdf_path: Path, start_page: int, end_page: int) -> tuple[str, int]:
    resolved = pdf_path.resolve(strict=True)
    if resolved.suffix.lower() != ".pdf":
        raise ValueError("Only PDF files can be ingested")
    digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    document_id = f"hill-intro-nt-{digest[:12]}-ch1"
    chunks = build_chunks(resolved, start_page, end_page)
    if not chunks:
        raise RuntimeError("No chunks were extracted")

    initialize_database()
    texts = [" ".join(filter(None, [chunk.heading, chunk.content])) for chunk in chunks]
    vectors = [as_pgvector(values) for values in embed_texts(texts)]

    with connection() as conn:
        conn.execute("DELETE FROM documents WHERE id = %s", (document_id,))
        conn.execute(
            """
            INSERT INTO documents
                (id, filename, title, author, sha256, page_start, page_end, embedding_model)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                document_id,
                resolved.name,
                "Introduction to Number Theory — Chapter 1: Euclid’s Algorithm",
                "Richard Michael Hill",
                digest,
                start_page,
                end_page,
                MODEL_NAME,
            ),
        )
        for chunk, vector in zip(chunks, vectors, strict=True):
            conn.execute(
                """
                INSERT INTO chunks
                    (document_id, ordinal, pdf_page, printed_page, chapter, section,
                     block_type, heading, content, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
                """,
                (
                    document_id,
                    chunk.ordinal,
                    chunk.pdf_page,
                    chunk.printed_page,
                    "1 Euclid’s Algorithm",
                    chunk.section,
                    chunk.block_type,
                    chunk.heading,
                    chunk.content,
                    vector,
                ),
            )
        conn.commit()
    return document_id, len(chunks)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest a PDF page range")
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--start-page", type=int, default=16)
    parser.add_argument("--end-page", type=int, default=41)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    document_id, count = ingest(args.pdf, args.start_page, args.end_page)
    print(f"Ingested document={document_id} chunks={count}")


if __name__ == "__main__":
    main()
