from __future__ import annotations

import argparse
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
from .ingestion.manifest import (
    DEFAULT_DEPLOY_TARGETS,
    describe_manifest,
    expand_manifest,
    resolved_deploy_targets,
)

logger = logging.getLogger(__name__)

DEFAULT_FILENAME = "1017984325-Introduction-to-Number-Theory-2026 (1).pdf"


@dataclass(frozen=True)
class SyncManifestResult:
    ingested: list[str]
    already_present: list[str]
    skipped_missing_pdf: list[str]
    failed: list[tuple[str, str]]


def pdf_digest(pdf_path: Path) -> str:
    return hashlib.sha256(pdf_path.read_bytes()).hexdigest()


def expected_document_id(pdf_path: Path, profile: ChapterProfile) -> str:
    return profile.document_id(pdf_digest(pdf_path))


def is_profile_ingested(pdf_path: Path, profile: ChapterProfile) -> bool:
    doc_id = expected_document_id(pdf_path, profile)
    digest = pdf_digest(pdf_path)
    with connection() as conn:
        row = conn.execute(
            """
            SELECT d.sha256, d.embedding_model,
                   COUNT(c.id) AS chunk_count
            FROM documents d
            LEFT JOIN chunks c ON c.document_id = d.id
            WHERE d.id = %s
            GROUP BY d.id, d.sha256, d.embedding_model
            """,
            (doc_id,),
        ).fetchone()
    if not row:
        return False
    if row["sha256"] != digest:
        return False
    if row["embedding_model"] != MODEL_NAME:
        return False
    return int(row["chunk_count"]) > 0


def sync_deploy_manifest(
    pdf_root: Path | None = None,
    targets: tuple[str, ...] | None = None,
) -> SyncManifestResult:
    """Ingest manifest targets that are missing or stale. Skips absent PDFs."""
    root = (pdf_root or settings.pdf_root).resolve()
    initialize_database()
    chosen = targets or resolved_deploy_targets()
    units = expand_manifest(root, chosen)

    ingested: list[str] = []
    already_present: list[str] = []
    skipped_missing_pdf: list[str] = []
    failed: list[tuple[str, str]] = []
    missing_entries: set[str] = set()

    for entry in chosen:
        try:
            expanded = expand_manifest(root, (entry,))
        except (KeyError, ValueError) as exc:
            failed.append((entry, str(exc)))
            continue
        if not expanded:
            missing_entries.add(entry)

    for unit in units:
        if not unit.pdf_path.is_file():
            skipped_missing_pdf.append(unit.profile.key)
            continue
        if is_profile_ingested(unit.pdf_path, unit.profile):
            already_present.append(unit.profile.key)
            continue
        try:
            document_id, count = ingest_profile(unit.pdf_path, unit.profile)
            ingested.append(f"{unit.profile.key} ({document_id}, chunks={count})")
            logger.info(
                "Manifest ingest: profile=%s document=%s chunks=%d",
                unit.profile.key,
                document_id,
                count,
            )
        except Exception as exc:
            failed.append((unit.profile.key, str(exc)))
            logger.exception("Manifest ingest failed for %s", unit.profile.key)

    for entry in missing_entries:
        skipped_missing_pdf.append(entry)

    result = SyncManifestResult(
        ingested=ingested,
        already_present=already_present,
        skipped_missing_pdf=skipped_missing_pdf,
        failed=failed,
    )
    logger.info(
        "Deploy manifest sync: ingested=%d present=%d missing_pdf=%d failed=%d",
        len(ingested),
        len(already_present),
        len(skipped_missing_pdf),
        len(failed),
    )
    return result


def sync_deploy_manifest_summary(
    pdf_root: Path | None = None,
    targets: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    result = sync_deploy_manifest(pdf_root=pdf_root, targets=targets)
    return {
        "targets": list(targets or resolved_deploy_targets()),
        "ingested": result.ingested,
        "already_present": result.already_present,
        "skipped_missing_pdf": result.skipped_missing_pdf,
        "failed": [{"target": t, "error": e} for t, e in result.failed],
    }

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


def ingest_all_approved(pdf_root: Path | None = None) -> tuple[int, int, int]:
    """Ingest every approved book. Returns (books, documents, chunks)."""
    root = (pdf_root or settings.pdf_root).resolve()
    missing = [
        book.filename
        for book in list_books()
        if not (root / book.filename).exists()
    ]
    if missing:
        raise FileNotFoundError("Missing PDF files:\n- " + "\n- ".join(missing))

    books = list_books()
    total_docs = 0
    total_chunks = 0
    for book in books:
        print(f"=== book {book.key} ===")
        results = ingest_book(root, book)
        total_docs += len(results)
        total_chunks += sum(count for _, count in results)
    print(
        f"DONE approved_books={len(books)} documents={total_docs} chunks={total_chunks}"
    )
    print("Skipped files:")
    for item in SKIPPED_PDFS:
        present = (root / item.filename).exists()
        print(f"  [{'present' if present else 'absent'}] {item.filename}: {item.reason}")
    return len(books), total_docs, total_chunks


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
    parser.add_argument(
        "--sync-manifest",
        action="store_true",
        help="Ingest deploy manifest targets that are missing or stale",
    )
    parser.add_argument(
        "--list-manifest",
        action="store_true",
        help="Show deploy manifest targets and resolved profiles",
    )
    parser.add_argument("--list-skipped", action="store_true")
    return parser.parse_args()


def _print_sync_summary(summary: dict[str, Any]) -> None:
    print(f"targets: {', '.join(summary['targets'])}")
    if summary["ingested"]:
        print("ingested:")
        for line in summary["ingested"]:
            print(f"  + {line}")
    if summary["already_present"]:
        print("already_present:")
        for key in summary["already_present"]:
            print(f"  = {key}")
    if summary["skipped_missing_pdf"]:
        print("skipped_missing_pdf:")
        for key in summary["skipped_missing_pdf"]:
            print(f"  ? {key}")
    if summary["failed"]:
        print("failed:")
        for item in summary["failed"]:
            print(f"  ! {item['target']}: {item['error']}")


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

    if args.list_manifest:
        print("Default deploy targets (edit ingestion/manifest.py):")
        for line in DEFAULT_DEPLOY_TARGETS:
            print(f"  {line}")
        print("Resolved (effective targets):")
        for line in describe_manifest():
            print(f"  {line}")
        return

    if args.sync_manifest:
        _print_sync_summary(sync_deploy_manifest_summary(pdf_root))
        return

    if args.list_profiles:
        for profile in list_profiles():
            print(
                f"{profile.key}: pages {profile.start_page}-{profile.end_page} · "
                f"{profile.chapter_label}"
            )
        return

    if args.all_approved:
        try:
            ingest_all_approved(pdf_root)
        except FileNotFoundError as exc:
            raise SystemExit(str(exc)) from exc
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
