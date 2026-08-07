from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from .config import settings
from .db import connection, initialize_database
from .embedding import MODEL_NAME, as_pgvector, embed_texts
from .ingestion import (
    BookSpec,
    ChapterProfile,
    book_to_profiles,
    build_chunks,
    detect_chapters,
    get_book,
    list_books,
    list_profiles,
    resolve_profile,
)
from .ingestion.catalog import SKIPPED_PDFS


DEFAULT_FILENAME = "1017984325-Introduction-to-Number-Theory-2026 (1).pdf"


def ingest_profile(pdf_path: Path, profile: ChapterProfile) -> tuple[str, int]:
    resolved = pdf_path.resolve(strict=True)
    if resolved.suffix.lower() != ".pdf":
        raise ValueError("Only PDF files can be ingested")

    digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    document_id = profile.document_id(digest)
    chunks = build_chunks(resolved, profile)
    if not chunks:
        raise RuntimeError(f"No chunks were extracted for {profile.key}")

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
                profile.document_title,
                profile.author,
                digest,
                profile.start_page,
                profile.end_page,
                MODEL_NAME,
            ),
        )
        for chunk, vector in zip(chunks, vectors, strict=True):
            conn.execute(
                """
                INSERT INTO chunks
                    (document_id, ordinal, pdf_page, printed_page, chapter, section,
                     block_type, heading, content, embedding, parent_ordinal)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s)
                """,
                (
                    document_id,
                    chunk.ordinal,
                    chunk.pdf_page,
                    chunk.printed_page,
                    profile.chapter_label,
                    chunk.section,
                    chunk.block_type,
                    chunk.heading,
                    chunk.content,
                    vector,
                    chunk.parent_ordinal,
                ),
            )
        conn.commit()
    return document_id, len(chunks)


def resolve_book_profiles(pdf_root: Path, book: BookSpec) -> list[ChapterProfile]:
    pdf_path = (pdf_root / book.filename).resolve(strict=True)
    if book.chapters:
        return book_to_profiles(book)
    detected = detect_chapters(pdf_path, book)
    if detected:
        print(
            f"  auto-detected {len(detected)} chapters for {book.key}: "
            + ", ".join(f"{item.number}@{item.start_page}" for item in detected[:12])
            + ("…" if len(detected) > 12 else "")
        )
        return book_to_profiles(book, detected=detected)
    print(f"  no chapter banners found for {book.key}; ingesting as one body document")
    return book_to_profiles(book)


def ingest_book(pdf_root: Path, book: BookSpec) -> list[tuple[str, int]]:
    pdf_path = (pdf_root / book.filename).resolve(strict=True)
    profiles = resolve_book_profiles(pdf_root, book)
    results: list[tuple[str, int]] = []
    for profile in profiles:
        document_id, count = ingest_profile(pdf_path, profile)
        print(
            f"Ingested document={document_id} book={book.key} "
            f"unit={profile.key} chunks={count} quality={book.quality}"
        )
        results.append((document_id, count))
    return results


def ingest(pdf_path: Path, start_page: int, end_page: int) -> tuple[str, int]:
    """Backward-compatible entry point used by older commands/tests."""
    profile = resolve_profile(profile_key=None, start_page=start_page, end_page=end_page)
    return ingest_profile(pdf_path, profile)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest approved number-theory PDFs")
    parser.add_argument("--pdf", type=Path, required=False)
    parser.add_argument("--pdf-root", type=Path, default=None)
    parser.add_argument(
        "--profile",
        help="Single chapter/body profile key (from --list-profiles)",
    )
    parser.add_argument(
        "--book",
        choices=[book.key for book in list_books()],
        help="Ingest one approved book (all chapters)",
    )
    parser.add_argument(
        "--all-approved",
        action="store_true",
        help="Ingest every approved book; skip scan/draft/history PDFs",
    )
    parser.add_argument("--start-page", type=int, default=None)
    parser.add_argument("--end-page", type=int, default=None)
    parser.add_argument("--list-profiles", action="store_true")
    parser.add_argument("--list-books", action="store_true")
    parser.add_argument("--list-skipped", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pdf_root = (args.pdf_root or settings.pdf_root).resolve()

    if args.list_skipped:
        for item in SKIPPED_PDFS:
            print(f"{item.filename}: {item.reason}")
        return

    if args.list_books:
        for book in list_books():
            chapter_info = (
                f"{len(book.chapters)} fixed chapters"
                if book.chapters
                else "auto-detect chapters"
            )
            print(
                f"{book.key}: {book.book_title} · pages {book.body_start}-{book.body_end} · "
                f"{book.quality}/{book.language} · {chapter_info}"
            )
        print("--- skipped ---")
        for item in SKIPPED_PDFS:
            print(f"SKIP {item.filename}: {item.reason}")
        return

    if args.list_profiles:
        for profile in list_profiles():
            print(
                f"{profile.key}: pages {profile.start_page}-{profile.end_page} · "
                f"{profile.chapter_label}"
            )
        return

    if args.all_approved:
        missing = [
            book.filename
            for book in list_books()
            if not (pdf_root / book.filename).exists()
        ]
        if missing:
            raise SystemExit("Missing PDF files:\n- " + "\n- ".join(missing))
        total_docs = 0
        total_chunks = 0
        for book in list_books():
            print(f"=== book {book.key} ===")
            results = ingest_book(pdf_root, book)
            total_docs += len(results)
            total_chunks += sum(count for _, count in results)
        print(f"DONE approved_books={len(list_books())} documents={total_docs} chunks={total_chunks}")
        print("Skipped files:")
        for item in SKIPPED_PDFS:
            present = (pdf_root / item.filename).exists()
            print(f"  [{'present' if present else 'absent'}] {item.filename}: {item.reason}")
        return

    if args.book:
        book = get_book(args.book)
        ingest_book(pdf_root, book)
        return

    if args.pdf is None and args.profile is None:
        raise SystemExit("Provide --all-approved, --book, --profile, or --pdf")

    if args.profile:
        profile = resolve_profile(
            profile_key=args.profile,
            start_page=args.start_page,
            end_page=args.end_page,
        )
        pdf_path = args.pdf or (pdf_root / next(
            book.filename for book in list_books() if profile.key.startswith(book.key)
        ))
        document_id, count = ingest_profile(pdf_path, profile)
        print(f"Ingested document={document_id} profile={profile.key} chunks={count}")
        return

    assert args.pdf is not None
    profile = resolve_profile(
        profile_key=None,
        start_page=args.start_page,
        end_page=args.end_page,
    )
    document_id, count = ingest_profile(args.pdf, profile)
    print(f"Ingested document={document_id} profile={profile.key} chunks={count}")


if __name__ == "__main__":
    main()
