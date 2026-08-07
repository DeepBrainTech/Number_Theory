from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .catalog import BookSpec, ChapterBound
from .ocr import MIN_NATIVE_CHARS, ocr_page
from .profiles import ChapterProfile

CHAPTER_START = re.compile(
    r"^(?:Chapter|CHAPTER|Ch\.?)\s+(\d+)\b",
    re.IGNORECASE,
)
CHAPTER_CN = re.compile(r"^第\s*([0-9一二三四五六七八九十百]+)\s*章")
SECTION_DOTTED = re.compile(r"^(\d+\.\d+)\s+(.+)$")
SECTION_CN = re.compile(r"^([0-9]+(?:\.[0-9]+)+)\s+(.+)$")

CN_NUMERALS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


@dataclass
class Chunk:
    ordinal: int
    pdf_page: int
    printed_page: int
    section: str | None
    block_type: str
    heading: str | None
    content: str
    # Lightweight dependency link: for proof blocks, the ordinal of the
    # theorem/lemma chunk this proof belongs to (None when unknown).
    parent_ordinal: int | None = None


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


def extract_page_range(pdf_path: Path, start_page: int, end_page: int) -> list[tuple[int, str]]:
    """Extract many pages in one pdftotext call; split on form feed."""
    result = subprocess.run(
        [
            "pdftotext",
            "-f",
            str(start_page),
            "-l",
            str(end_page),
            "-layout",
            "-enc",
            "UTF-8",
            str(pdf_path),
            "-",
        ],
        check=True,
        capture_output=True,
    )
    raw = result.stdout.decode("utf-8", errors="replace")
    parts = raw.split("\x0c")
    pages: list[tuple[int, str]] = []
    for offset, part in enumerate(parts):
        pdf_page = start_page + offset
        if pdf_page > end_page:
            break
        pages.append((pdf_page, part))
    # pdftotext may omit a trailing empty page; pad if needed
    while pages and pages[-1][0] < end_page and len(pages) < (end_page - start_page + 1):
        missing = pages[-1][0] + 1
        pages.append((missing, ""))
    if not pages:
        for pdf_page in range(start_page, end_page + 1):
            pages.append((pdf_page, extract_page(pdf_path, pdf_page)))
    return pages


def clean_page(text: str, header_strings: tuple[str, ...]) -> str:
    lines = [line.rstrip() for line in text.replace("\x0c", "").splitlines()]
    filtered: list[str] = []
    headers = {item.strip() for item in header_strings if item.strip()}
    ascii_headers = {item.replace("’", "'") for item in headers}
    for line in lines:
        stripped = line.strip()
        if not stripped:
            filtered.append(line)
            continue
        if re.fullmatch(r"\d+", stripped):
            continue
        if stripped in headers or stripped.replace("’", "'") in ascii_headers:
            continue
        filtered.append(line)
    return "\n".join(filtered).strip()


def classify(text: str) -> tuple[str, str | None]:
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if re.match(r"^(Theorem|Lemma|Corollary|Proposition)\b", first):
        return "theorem", first
    if re.match(r"^(定理|引理|推论|命题)\b", first):
        return "theorem", first
    if re.match(r"^Proof\b", first, re.IGNORECASE) or re.match(r"^证明\b", first):
        return "proof", first
    example = re.search(r"\bExample\b", text[:500]) or re.search(r"例\s*[0-9.]*", text[:500])
    if example and (first.startswith("Example") or first.startswith("例")):
        return "example", first[:120]
    if re.match(r"^Exercise\b", first) or re.match(r"^(习题|练习)\b", first):
        return "exercise", first
    if (
        re.match(r"^Definition\b", first)
        or first.endswith("Axioms.")
        or re.match(r"^定义\b", first)
    ):
        return "definition", first
    if "Hints for Some Exercises" in first or first.startswith("提示"):
        return "hint", first
    if re.match(r"^(Remark|Notation|Note)\b", first) or re.match(r"^(注|记号)\b", first):
        return "exposition", first
    return "exposition", None


def split_long_paragraph(paragraph: str, max_chars: int = 1800) -> list[str]:
    if len(paragraph) <= max_chars:
        return [paragraph]
    sentences = re.split(r"(?<=[.!?。！？□])\s+(?=[A-Z(（\u4e00-\u9fff])", paragraph)
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


def _parse_cn_chapter_number(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    if token in CN_NUMERALS:
        return CN_NUMERALS[token]
    if token.startswith("十"):
        rest = token[1:]
        return 10 + (CN_NUMERALS.get(rest, 0) if rest else 0)
    if "十" in token:
        left, _, right = token.partition("十")
        return CN_NUMERALS.get(left, 0) * 10 + CN_NUMERALS.get(right, 0)
    return None


def _page_chapter_banner(page_text: str) -> tuple[int, str] | None:
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    if not lines:
        return None

    # Style A: "Chapter 3" / "第3章"
    for index, line in enumerate(lines[:12]):
        match = CHAPTER_START.match(line)
        if match and len(line) < 100:
            number = int(match.group(1))
            title = ""
            remainder = line[match.end() :].strip(" :-.")
            if remainder and len(remainder) > 2:
                title = remainder
            elif index + 1 < len(lines):
                candidate = lines[index + 1]
                if len(candidate) < 120 and not CHAPTER_START.match(candidate):
                    title = candidate
            return number, title or f"Chapter {number}"
        match_cn = CHAPTER_CN.match(line)
        if match_cn and len(line) < 100:
            number = _parse_cn_chapter_number(match_cn.group(1))
            if number is None:
                continue
            title = line[match_cn.end() :].strip(" ：:.-")
            if not title and index + 1 < len(lines):
                title = lines[index + 1][:120]
            return number, title or f"第{number}章"

    # Style B: lone chapter number near the top, then a title line
    # Used by Montgomery–Vaughan II (chapters 16–22). Require number >= 10 so
    # exercise markers / short page numbers are not mistaken for chapters.
    if re.fullmatch(r"\d{1,2}", lines[0]) and len(lines) >= 2:
        number = int(lines[0])
        title = lines[1]
        if (
            number >= 10
            and 8 < len(title) < 120
            and not re.fullmatch(r"\d+", title)
            and not re.match(r"^\d+\.\d+", title)
        ):
            return number, title

    return None


def detect_chapters(pdf_path: Path, book: BookSpec) -> list[ChapterBound]:
    starts: list[tuple[int, int, str]] = []
    for pdf_page, text in extract_page_range(pdf_path, book.body_start, book.body_end):
        banner = _page_chapter_banner(text)
        if not banner:
            continue
        number, title = banner
        if starts and starts[-1][0] == number:
            continue
        # Ignore out-of-order / TOC echoes once body chapters have begun.
        if starts and number < starts[-1][0]:
            continue
        # Skip tiny jumps that are likely section noise for style-B books
        if starts and number > starts[-1][0] + 3 and starts[-1][0] >= 10:
            # allow MV II style continuation (16,17,...) but reject wild jumps early
            if number - starts[-1][0] > 5:
                continue
        starts.append((number, pdf_page, re.sub(r"\s+", " ", title).strip()))

    if len(starts) < 2:
        return []

    bounds: list[ChapterBound] = []
    for index, (number, start_page, title) in enumerate(starts):
        end_page = starts[index + 1][1] - 1 if index + 1 < len(starts) else book.body_end
        if end_page < start_page:
            continue
        bounds.append(
            ChapterBound(number=number, title=title, start_page=start_page, end_page=end_page)
        )
    return bounds


def _is_chapter_banner(paragraph: str, profile: ChapterProfile) -> bool:
    stripped = paragraph.strip()
    if profile.chapter_number > 0:
        if re.fullmatch(rf"(?:Chapter|CHAPTER)\s+{profile.chapter_number}", stripped, re.IGNORECASE):
            return True
        if re.fullmatch(rf"第\s*{profile.chapter_number}\s*章.*", stripped):
            return True
    if stripped == profile.chapter_title:
        return True
    ascii_title = profile.chapter_title.replace("’", "'")
    return stripped == ascii_title or stripped.replace("’", "'") == ascii_title


def build_chunks(pdf_path: Path, profile: ChapterProfile) -> list[Chunk]:
    chunks: list[Chunk] = []
    ordinal = 0
    current_section: str | None = None
    last_theorem_ordinal: int | None = None
    if profile.chapter_number > 0:
        section_pattern = re.compile(rf"^({profile.chapter_number}\.\d+)\s+(.+)$")
    else:
        section_pattern = SECTION_DOTTED

    for pdf_page, raw_text in extract_page_range(pdf_path, profile.start_page, profile.end_page):
        if len(raw_text.strip()) < MIN_NATIVE_CHARS:
            ocr_text = ocr_page(pdf_path, pdf_page)
            if ocr_text:
                raw_text = ocr_text
        page_text = clean_page(raw_text, profile.header_strings)
        paragraphs = [
            re.sub(r"[ \t]+", " ", paragraph.replace("\n", " ")).strip()
            for paragraph in re.split(r"\n\s*\n", page_text)
            if paragraph.strip()
        ]
        for paragraph in paragraphs:
            section_match = section_pattern.match(paragraph) or SECTION_CN.match(paragraph)
            if section_match and len(paragraph) < 160:
                heading = section_match.group(2).strip()
                current_section = f"{section_match.group(1)} {heading[:80].title()}"
                continue
            if _is_chapter_banner(paragraph, profile):
                continue
            for part in split_long_paragraph(paragraph):
                if len(part) < 40:
                    continue
                block_type, heading = classify(part)
                parent = last_theorem_ordinal if block_type == "proof" else None
                chunks.append(
                    Chunk(
                        ordinal=ordinal,
                        pdf_page=pdf_page,
                        printed_page=profile.printed_page(pdf_page),
                        section=current_section,
                        block_type=block_type,
                        heading=heading,
                        content=part,
                        parent_ordinal=parent,
                    )
                )
                if block_type == "theorem":
                    last_theorem_ordinal = ordinal
                elif block_type not in {"proof", "exposition"}:
                    # An intervening example/exercise breaks the theorem→proof pairing.
                    last_theorem_ordinal = None
                ordinal += 1
    return chunks
