"""PDF ingestion: catalogs, chapter profiles, and semantic chunking."""

from .catalog import APPROVED_BOOKS, SKIPPED_PDFS, BookSpec, get_book, list_books, skipped_filenames
from .chunking import Chunk, build_chunks, detect_chapters
from .profiles import ChapterProfile, book_to_profiles, get_profile, list_profiles, resolve_profile

__all__ = [
    "APPROVED_BOOKS",
    "SKIPPED_PDFS",
    "BookSpec",
    "ChapterProfile",
    "Chunk",
    "book_to_profiles",
    "build_chunks",
    "detect_chapters",
    "get_book",
    "get_profile",
    "list_books",
    "list_profiles",
    "resolve_profile",
    "skipped_filenames",
]
