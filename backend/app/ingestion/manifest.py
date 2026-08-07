"""Deployment ingest manifest — which books/chapters are required in the RAG library.

Edit DEFAULT_DEPLOY_TARGETS to change what auto-sync ingests on deploy.
Override at runtime with DEPLOY_INGEST_TARGETS (comma-separated).

Target syntax:
  profile:hill-ch1   — one chapter/profile (see: python -m app.ingest --list-profiles)
  book:hill          — every chapter of one catalog book
  hill-ch1           — profile key (auto)
  hill               — whole book if key matches a catalog book

PDF must exist under pdf/; missing files are skipped with a warning (deploy still succeeds).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .catalog import BookSpec, get_book, list_books
from .chunking import detect_chapters
from .profiles import ChapterProfile, book_to_profiles, get_profile

from ..config import settings

# --- Deploy ingest scope (scanned pdf/ on 2026-08-07) ---
#
# ON DISK — do NOT ingest (SKIPPED_PDFS / scan-only / draft):
#   037_解析数论基础.pdf, 790211459-哥德巴赫猜想.pdf,
#   230677144-Ramanujan-s-Notebooks-Part-2-of-5.pdf,
#   Multiplicative number theory.pdf, RamanujanKSRchap3.pdf, 数论-陈景润.pdf
#
# ON DISK — deferred (optional / low priority):
#   wustholz — research anthology (406208375-A-panorama...)
#
# lozano & berndt3: use *-body (auto chapter detect splits into junk 2-page units).
# OCR books (apostol, tenenbaum, berndt4): included; text layer usable but noisier.
#
# Already in local DB: hill-ch1, hill-ch2, hill-ch3 (517 chunks).
DEFAULT_DEPLOY_TARGETS: tuple[str, ...] = (
    # hill — Introduction to Number Theory (native/en)
    "profile:hill-ch1",  # pages 16-41 · Euclid's Algorithm
    "profile:hill-ch2",  # pages 42-67 · Polynomial Rings
    "profile:hill-ch3",  # pages 68-115 · Congruences Modulo Prime Numbers
    "profile:hill-ch4",  # pages 116-163 · p-Adic Methods
    "profile:hill-ch5",  # pages 164-214 · Diophantine Equations
    # grigorieva — Methods of Solving Number Theory Problems (native/en)
    "profile:grigorieva-ch1",
    "profile:grigorieva-ch2",
    "profile:grigorieva-ch3",
    "profile:grigorieva-ch4",
    # cai — 经典数论的现代导引 (native/zh)
    "profile:cai-ch1",
    "profile:cai-ch2",
    "profile:cai-ch3",
    "profile:cai-ch4",
    "profile:cai-ch5",
    "profile:cai-ch6",
    "profile:cai-ch7",
    # burde — Analytic Number Theory lecture notes (native/en)
    "profile:burde-ch0",
    "profile:burde-ch1",
    "profile:burde-ch2",
    "profile:burde-ch3",
    # mv2 — Multiplicative Number Theory II (native/en)
    "profile:mv2-ch16",
    "profile:mv2-ch17",
    "profile:mv2-ch18",
    "profile:mv2-ch19",
    "profile:mv2-ch20",
    "profile:mv2-ch21",
    "profile:mv2-ch22",
    # whole-body native (fixed page ranges in catalog)
    "profile:mv1-body",  # Montgomery–Vaughan I · pages 20-504
    "profile:lozano-body",  # Number Theory and Geometry · pages 18-495
    "profile:berndt3-body",  # Ramanujan Notebooks III · pages 22-504
    # whole-body OCR (usable text, lower quality)
    "profile:apostol-body",  # Apostol analytic NT · pages 13-340
    "profile:tenenbaum-body",  # Tenenbaum analytic & probabilistic · pages 20-449
    "profile:berndt4-body",  # Ramanujan Notebooks IV · pages 9-224
)


@dataclass(frozen=True)
class IngestUnit:
    """One PDF + profile pair to ingest."""

    book: BookSpec
    profile: ChapterProfile
    pdf_path: Path


def resolved_deploy_targets() -> tuple[str, ...]:
    if settings.deploy_ingest_targets:
        return settings.deploy_ingest_targets
    return DEFAULT_DEPLOY_TARGETS


def _book_for_profile_key(key: str) -> BookSpec | None:
    for book in list_books():
        if key == book.key or key.startswith(f"{book.key}-"):
            return book
    return None


def _profiles_for_book(pdf_root: Path, book: BookSpec) -> list[ChapterProfile]:
    pdf_path = pdf_root / book.filename
    if book.chapters:
        return book_to_profiles(book)
    detected = detect_chapters(pdf_path, book)
    if detected:
        return book_to_profiles(book, detected=detected)
    return book_to_profiles(book)


def _expand_book_target(pdf_root: Path, book_key: str) -> list[IngestUnit]:
    book = get_book(book_key)
    pdf_path = (pdf_root / book.filename).resolve()
    if not pdf_path.is_file():
        return []
    units: list[IngestUnit] = []
    for profile in _profiles_for_book(pdf_root, book):
        units.append(IngestUnit(book=book, profile=profile, pdf_path=pdf_path))
    return units


def _expand_profile_target(pdf_root: Path, profile_key: str) -> list[IngestUnit]:
    profile = get_profile(profile_key)
    book = _book_for_profile_key(profile_key)
    if book is None:
        raise KeyError(f"No catalog book for profile {profile_key!r}")
    pdf_path = (pdf_root / book.filename).resolve()
    if not pdf_path.is_file():
        return []
    return [IngestUnit(book=book, profile=profile, pdf_path=pdf_path)]


def expand_target(pdf_root: Path, entry: str) -> list[IngestUnit]:
    raw = entry.strip()
    if not raw:
        return []

    if ":" in raw:
        kind, name = raw.split(":", 1)
        kind = kind.strip().lower()
        name = name.strip()
        if kind == "profile":
            return _expand_profile_target(pdf_root, name)
        if kind == "book":
            return _expand_book_target(pdf_root, name)
        raise ValueError(f"Unknown manifest target kind {kind!r} in {entry!r}")

    try:
        return _expand_profile_target(pdf_root, raw)
    except KeyError:
        pass
    try:
        return _expand_book_target(pdf_root, raw)
    except KeyError:
        pass
    raise ValueError(
        f"Unknown deploy ingest target {entry!r}. "
        "Use profile:<key>, book:<key>, or a catalog profile/book key."
    )


def expand_manifest(pdf_root: Path, targets: tuple[str, ...] | None = None) -> list[IngestUnit]:
    root = pdf_root.resolve()
    chosen = targets or resolved_deploy_targets()
    units: list[IngestUnit] = []
    seen: set[str] = set()
    for entry in chosen:
        for unit in expand_target(root, entry):
            key = unit.profile.key
            if key in seen:
                continue
            seen.add(key)
            units.append(unit)
    return units


def describe_manifest(targets: tuple[str, ...] | None = None) -> list[str]:
    lines: list[str] = []
    for entry in targets or resolved_deploy_targets():
        try:
            units = expand_target(settings.pdf_root, entry)
        except (KeyError, ValueError) as exc:
            lines.append(f"{entry}: ERROR {exc}")
            continue
        if not units:
            lines.append(f"{entry}: PDF missing")
            continue
        for unit in units:
            lines.append(
                f"{entry} -> {unit.profile.key} "
                f"({unit.profile.document_title}) "
                f"pages {unit.profile.start_page}-{unit.profile.end_page} "
                f"[{unit.book.filename}]"
            )
    return lines
