"""Scan pdf/ and print deploy-manifest recommendations.

Run from repo root:
  python backend/scripts/scan_pdf_manifest.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.ingestion import chunking  # noqa: E402
from app.ingestion.catalog import SKIPPED_PDFS, list_books  # noqa: E402
from app.ingestion.manifest import DEFAULT_DEPLOY_TARGETS, expand_manifest  # noqa: E402
from app.ingestion.profiles import book_to_profiles, profile_from_bound  # noqa: E402

PDF_ROOT = ROOT / "pdf"
BACK_MATTER = re.compile(
    r"(index|bibliography|references|errata|author index|name index|symbol index)",
    re.I,
)


def pymupdf_extract(pdf_path: Path, start_page: int, end_page: int):
    doc = fitz.open(pdf_path)
    last = min(end_page, doc.page_count)
    for pdf_page in range(start_page, last + 1):
        yield pdf_page, doc[pdf_page - 1].get_text("text")


chunking.extract_page_range = pymupdf_extract


def profiles_for_book(book):
    path = PDF_ROOT / book.filename
    if book.chapters:
        return book_to_profiles(book)
    detected = chunking.detect_chapters(path, book)
    if detected and len(detected) >= 2:
        return [profile_from_bound(book, b) for b in detected]
    return book_to_profiles(book)


def tier(book, profile) -> str:
    if BACK_MATTER.search(profile.chapter_title) or profile.chapter_number >= 90:
        return "X"
    if book.quality == "native":
        return "A"
    if book.quality == "ocr":
        return "B"
    return "C"


def main() -> None:
    skipped = {s.filename: s.reason for s in SKIPPED_PDFS}
    print("=== SKIPPED (on disk, do not ingest) ===")
    for path in sorted(PDF_ROOT.glob("*.pdf")):
        if path.name in skipped:
            print(f"  {path.name}: {skipped[path.name]}")

    print("\n=== PER-BOOK SCAN ===")
    for book in list_books():
        path = PDF_ROOT / book.filename
        if not path.is_file():
            print(f"MISSING {book.key}")
            continue
        profiles = profiles_for_book(book)
        print(f"{book.key}: {len(profiles)} units · {book.quality}/{book.language}")

    units = expand_manifest(PDF_ROOT, DEFAULT_DEPLOY_TARGETS)
    print(f"\n=== CURRENT MANIFEST ({len(units)} units) ===")
    for unit in units:
        print(
            f"  profile:{unit.profile.key} pages {unit.profile.start_page}-"
            f"{unit.profile.end_page} [{unit.book.key}]"
        )


if __name__ == "__main__":
    main()
