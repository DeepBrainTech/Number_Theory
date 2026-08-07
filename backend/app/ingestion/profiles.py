from __future__ import annotations

from dataclasses import dataclass

from .catalog import BookSpec, ChapterBound, get_book, list_books


@dataclass(frozen=True)
class ChapterProfile:
    """Reusable metadata for ingesting one chapter (or whole-body unit) of a book."""

    key: str
    book_slug: str
    book_title: str
    author: str
    chapter_number: int
    chapter_title: str
    start_page: int
    end_page: int
    page_offset: int
    header_strings: tuple[str, ...]
    language: str = "en"
    quality: str = "native"

    @property
    def chapter_label(self) -> str:
        if self.chapter_number < 0:
            return self.chapter_title
        if self.chapter_number == 0:
            return self.chapter_title
        return f"{self.chapter_number} {self.chapter_title}"

    @property
    def document_title(self) -> str:
        if self.chapter_number < 0:
            return f"{self.book_title} — {self.chapter_title}"
        if self.chapter_number == 0:
            return f"{self.book_title} — {self.chapter_title}"
        return f"{self.book_title} — Chapter {self.chapter_number}: {self.chapter_title}"

    def document_id(self, digest: str) -> str:
        if self.chapter_number < 0:
            return f"{self.book_slug}-{digest[:12]}-body"
        return f"{self.book_slug}-{digest[:12]}-ch{self.chapter_number}"

    def printed_page(self, pdf_page: int) -> int:
        return pdf_page - self.page_offset


def profile_from_bound(book: BookSpec, bound: ChapterBound) -> ChapterProfile:
    headers = book.header_strings + (bound.title, bound.title.replace("’", "'"))
    key = f"{book.key}-body" if bound.number < 0 else f"{book.key}-ch{bound.number}"
    return ChapterProfile(
        key=key,
        book_slug=book.book_slug,
        book_title=book.book_title,
        author=book.author,
        chapter_number=bound.number,
        chapter_title=bound.title,
        start_page=bound.start_page,
        end_page=bound.end_page,
        page_offset=book.page_offset,
        header_strings=tuple(dict.fromkeys(headers)),
        language=book.language,
        quality=book.quality,
    )


def whole_body_profile(book: BookSpec) -> ChapterProfile:
    return ChapterProfile(
        key=f"{book.key}-body",
        book_slug=book.book_slug,
        book_title=book.book_title,
        author=book.author,
        chapter_number=-1,
        chapter_title="Main text",
        start_page=book.body_start,
        end_page=book.body_end,
        page_offset=book.page_offset,
        header_strings=book.header_strings,
        language=book.language,
        quality=book.quality,
    )


def list_profiles() -> list[ChapterProfile]:
    profiles: list[ChapterProfile] = []
    for book in list_books():
        if book.chapters:
            profiles.extend(profile_from_bound(book, bound) for bound in book.chapters)
        else:
            profiles.append(whole_body_profile(book))
    return profiles


def get_profile(key: str) -> ChapterProfile:
    for profile in list_profiles():
        if profile.key == key:
            return profile
    known = ", ".join(profile.key for profile in list_profiles())
    raise KeyError(f"Unknown profile {key!r}. Known: {known}")


def resolve_profile(
    *,
    profile_key: str | None,
    start_page: int | None,
    end_page: int | None,
) -> ChapterProfile:
    if profile_key:
        profile = get_profile(profile_key)
        if start_page is not None and start_page != profile.start_page:
            raise ValueError(
                f"--start-page {start_page} does not match profile {profile.key} "
                f"(expected {profile.start_page})"
            )
        if end_page is not None and end_page != profile.end_page:
            raise ValueError(
                f"--end-page {end_page} does not match profile {profile.key} "
                f"(expected {profile.end_page})"
            )
        return profile

    if start_page is None or end_page is None:
        raise ValueError("Provide --profile/--book or both --start-page and --end-page")

    for profile in list_profiles():
        if profile.start_page == start_page and profile.end_page == end_page:
            return profile

    raise ValueError(
        f"No known profile for pages {start_page}-{end_page}. "
        "Pass --book/--profile or extend catalog.py."
    )


def book_to_profiles(book: BookSpec, detected: list[ChapterBound] | None = None) -> list[ChapterProfile]:
    if book.chapters:
        return [profile_from_bound(book, bound) for bound in book.chapters]
    if detected:
        return [profile_from_bound(book, bound) for bound in detected]
    return [whole_body_profile(book)]


def resolve_book_key(key: str) -> BookSpec:
    return get_book(key)
