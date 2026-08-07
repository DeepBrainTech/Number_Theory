from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChapterBound:
    number: int
    title: str
    start_page: int
    end_page: int


@dataclass(frozen=True)
class BookSpec:
    """Approved book for the number-theory knowledge base."""

    key: str
    filename: str
    book_slug: str
    book_title: str
    author: str
    body_start: int
    body_end: int
    page_offset: int
    header_strings: tuple[str, ...]
    quality: str  # native | ocr | research
    language: str  # en | zh
    chapters: tuple[ChapterBound, ...] | None = None
    # If chapters is None, chapter starts are auto-detected inside body range.


@dataclass(frozen=True)
class SkippedPdf:
    filename: str
    reason: str


# Pure scans / drafts / non-theorem sources — do not ingest with the current pipeline.
SKIPPED_PDFS: tuple[SkippedPdf, ...] = (
    SkippedPdf("037_解析数论基础.pdf", "scan-only, no text layer; needs OCR before ingest"),
    SkippedPdf("790211459-哥德巴赫猜想.pdf", "scan-only; overlaps 潘承洞筛法专题, defer OCR"),
    SkippedPdf("230677144-Ramanujan-s-Notebooks-Part-2-of-5.pdf", "scan-only; use Berndt Part III/IV instead"),
    SkippedPdf("数论-陈景润.pdf", "scan-only overview pamphlet; low theorem density"),
    SkippedPdf(
        "Multiplicative number theory.pdf",
        "Granville–Soundararajan early draft marked 'Please do not circulate'",
    ),
    SkippedPdf("RamanujanKSRchap3.pdf", "historical/bibliographic survey, not a theorem source"),
)


HILL_PDF = "1017984325-Introduction-to-Number-Theory-2026 (1).pdf"
HILL_HEADERS = ("Introduction to Number Theory",)

APPROVED_BOOKS: tuple[BookSpec, ...] = (
    BookSpec(
        key="hill",
        filename=HILL_PDF,
        book_slug="hill-intro-nt",
        book_title="Introduction to Number Theory",
        author="Richard Michael Hill",
        body_start=16,
        body_end=214,
        page_offset=15,
        header_strings=HILL_HEADERS,
        quality="native",
        language="en",
        chapters=(
            ChapterBound(1, "Euclid’s Algorithm", 16, 41),
            ChapterBound(2, "Polynomial Rings", 42, 67),
            ChapterBound(3, "Congruences Modulo Prime Numbers", 68, 115),
            ChapterBound(4, "p-Adic Methods in Number Theory", 116, 163),
            ChapterBound(5, "Diophantine Equations and Quadratic Rings", 164, 214),
        ),
    ),
    BookSpec(
        key="grigorieva",
        filename="421432598-METHODS-OF-SOLVING-NUMBER-THEORIES.pdf",
        book_slug="grigorieva-methods-nt",
        book_title="Methods of Solving Number Theory Problems",
        author="Ellina Grigorieva",
        body_start=20,
        body_end=351,
        page_offset=19,
        header_strings=("Methods of Solving Number Theory Problems",),
        quality="native",
        language="en",
        chapters=(
            ChapterBound(1, "Numbers: Problems Involving Integers", 20, 80),
            ChapterBound(2, "Further Study of Integers", 81, 157),
            ChapterBound(3, "Diophantine Equations and More", 158, 261),
            ChapterBound(4, "Pythagorean Triples and Additive Problems", 262, 351),
        ),
    ),
    BookSpec(
        key="cai",
        filename="953736487-经典数论的现代导引-蔡天新-著-Z-Library.pdf",
        book_slug="cai-classic-nt-modern",
        book_title="经典数论的现代导引",
        author="蔡天新",
        body_start=22,
        body_end=285,
        page_offset=21,
        header_strings=("经典数论的现代导引",),
        quality="native",
        language="zh",
        chapters=(
            ChapterBound(1, "整除的算法", 22, 62),
            ChapterBound(2, "同余的概念", 63, 97),
            ChapterBound(3, "同余式理论", 98, 134),
            ChapterBound(4, "平方剩余", 135, 166),
            ChapterBound(5, "n次剩余", 167, 196),
            ChapterBound(6, "整数幂模同余", 197, 239),
            ChapterBound(7, "加乘数论", 240, 285),
        ),
    ),
    BookSpec(
        key="burde",
        filename="burde_81_annt_courseAnalytic Number Theory.pdf",
        book_slug="burde-analytic-nt-notes",
        book_title="Analytic Number Theory (Lecture Notes)",
        author="Dietrich Burde",
        body_start=4,
        body_end=117,
        page_offset=3,
        header_strings=("Analytic Number Theory",),
        quality="native",
        language="en",
        chapters=(
            ChapterBound(0, "Introduction", 4, 9),
            ChapterBound(1, "Elementary Prime Number Theory", 10, 51),
            ChapterBound(2, "Periodic Arithmetic Functions and Gauss Sums", 52, 97),
            ChapterBound(3, "Dirichlet Series and the Riemann Zeta Function", 98, 117),
        ),
    ),
    BookSpec(
        key="mv2",
        filename="montgomery-vaughanIIMultiplicative number theory.pdf",
        book_slug="montgomery-vaughan-mnt-ii",
        book_title="Multiplicative Number Theory II: Primes and Sieves",
        author="Hugh L. Montgomery, Robert C. Vaughan",
        body_start=13,
        body_end=346,
        page_offset=12,
        header_strings=("Multiplicative Number Theory",),
        quality="native",
        language="en",
        chapters=(
            ChapterBound(16, "Exponential Sums I: Van der Corput’s Method", 13, 65),
            ChapterBound(17, "Estimates for Sums over Primes", 66, 117),
            ChapterBound(18, "Additive Prime Number Theory", 118, 160),
            ChapterBound(19, "The Large Sieve", 161, 200),
            ChapterBound(20, "Primes in Arithmetic Progressions III", 201, 237),
            ChapterBound(21, "Sieves II", 238, 316),
            ChapterBound(22, "Bounded Gaps Between Primes", 317, 346),
        ),
    ),
    BookSpec(
        key="lozano",
        filename="437419531-Number-theory-and-geometry.pdf",
        book_slug="lozano-nt-geometry",
        book_title="Number Theory and Geometry",
        author="Álvaro Lozano-Robledo",
        body_start=18,
        body_end=495,
        page_offset=17,
        header_strings=("Number Theory and Geometry",),
        quality="native",
        language="en",
        chapters=None,
    ),
    BookSpec(
        key="apostol",
        filename="TomIntroduction to Analytic Number Theory.pdf",
        book_slug="apostol-analytic-nt",
        book_title="Introduction to Analytic Number Theory",
        author="Tom M. Apostol",
        body_start=13,
        body_end=340,
        page_offset=12,
        header_strings=("Introduction to Analytic Number Theory",),
        quality="ocr",
        language="en",
        # OCR often hides early "Chapter N" banners; ingest as one body for coverage.
        chapters=(ChapterBound(-1, "Main text", 13, 340),),
    ),
    BookSpec(
        key="tenenbaum",
        filename="489076707-Introduction-to-Analytic-and-Probabilistic-Number-Theory.pdf",
        book_slug="tenenbaum-analytic-prob-nt",
        book_title="Introduction to Analytic and Probabilistic Number Theory",
        author="Gérald Tenenbaum",
        body_start=20,
        body_end=449,
        page_offset=17,
        header_strings=(
            "Introduction to Analytic and Probabilistic Number Theory",
            "Analytic and Probabilistic Number Theory",
        ),
        quality="ocr",
        language="en",
        chapters=(ChapterBound(-1, "Main text", 20, 449),),
    ),
    BookSpec(
        key="mv1",
        filename="vdoc.pub_multiplicative-number-theory-i-classical-theory.pdf",
        book_slug="montgomery-vaughan-mnt-i",
        book_title="Multiplicative Number Theory I: Classical Theory",
        author="Hugh L. Montgomery, Robert C. Vaughan",
        body_start=20,
        body_end=504,
        page_offset=19,
        header_strings=("Multiplicative Number Theory",),
        quality="native",
        language="en",
        # Auto-detect missed Ch.1–7; whole-body guarantees coverage.
        chapters=(ChapterBound(-1, "Main text", 20, 504),),
    ),
    BookSpec(
        key="wustholz",
        filename="406208375-A-panorama-in-number-theory-G-Wustholz-pdf.pdf",
        book_slug="wustholz-panorama-nt",
        book_title="A Panorama in Number Theory / Baker’s Garden",
        author="Gisbert Wüstholz (ed.)",
        body_start=19,
        body_end=374,
        page_offset=18,
        header_strings=("A Panorama in Number Theory", "Baker’s Garden", "Baker's Garden"),
        quality="research",
        language="en",
        chapters=(ChapterBound(-1, "Main text", 19, 374),),
    ),
    BookSpec(
        key="berndt3",
        filename="RamanujanNotebooksPart3Berndt.pdf",
        book_slug="berndt-ramanujan-nb-iii",
        book_title="Ramanujan’s Notebooks Part III",
        author="Bruce C. Berndt",
        body_start=22,
        body_end=504,
        page_offset=21,
        header_strings=("Ramanujan’s Notebooks", "Ramanujan's Notebooks"),
        quality="native",
        language="en",
        chapters=None,
    ),
    BookSpec(
        key="berndt4",
        filename="Ramanujan Notebooks4Berndt.pdf",
        book_slug="berndt-ramanujan-nb-iv",
        book_title="Ramanujan’s Notebooks Part IV",
        author="Bruce C. Berndt",
        body_start=9,
        body_end=224,
        page_offset=8,
        header_strings=("Ramanujan’s Notebooks", "Ramanujan's Notebooks"),
        quality="ocr",
        language="en",
        chapters=(ChapterBound(-1, "Main text", 9, 224),),
    ),
)


def list_books() -> list[BookSpec]:
    return list(APPROVED_BOOKS)


def get_book(key: str) -> BookSpec:
    for book in APPROVED_BOOKS:
        if book.key == key:
            return book
    known = ", ".join(book.key for book in APPROVED_BOOKS)
    raise KeyError(f"Unknown book {key!r}. Known: {known}")


def skipped_filenames() -> set[str]:
    return {item.filename for item in SKIPPED_PDFS}
