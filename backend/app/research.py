"""Research-mode tools: arXiv, OEIS, Crossref, Semantic Scholar.

Parsing is split into pure functions so it can be unit-tested offline.
All network failures degrade to {"ok": False, "error": ...} — research tools
must never break the chat loop.
"""

from __future__ import annotations

import asyncio
import re
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from .config import settings


ARXIV_API = "https://export.arxiv.org/api/query"
OEIS_API = "https://oeis.org/search"
CROSSREF_API = "https://api.crossref.org/works"
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper/search"

_ATOM = "{http://www.w3.org/2005/Atom}"
_USER_AGENT = "ProofLab/0.5 (research; mailto:research@local)"


_ARXIV_FIELD_PATTERN = re.compile(
    r"(?:^|\s)(cat:|all:|ti:|au:|abs:|submittedDate:|id_list:|report-no:)",
    re.IGNORECASE,
)
_YEAR_PATTERN = re.compile(r"(20\d{2})")


def _arxiv_date_clause(year: str) -> str:
    return f"submittedDate:[{year}01010000 TO {year}12312359]"


def normalize_literature_query(query: str) -> str:
    """English-friendly query for Crossref / Semantic Scholar."""
    text = query.strip()
    if not text:
        return "mathematics"
    year_match = _YEAR_PATTERN.search(text)
    year = year_match.group(1) if year_match else None
    topics: list[str] = []
    if re.search(r"数论|number\s+theory|math\.?\s*nt", text, flags=re.IGNORECASE):
        topics.append("number theory")
    elif re.search(r"数学|mathematics|\bmath\b", text, flags=re.IGNORECASE):
        topics.append("mathematics")
    elif re.search(r"物理|physics", text, flags=re.IGNORECASE):
        topics.append("physics")
    english = re.sub(r"[\u4e00-\u9fff]+", " ", text)
    english = re.sub(r"\barxiv\b", " ", english, flags=re.IGNORECASE)
    english = re.sub(r"\b(20\d{2})\b", " ", english)
    english = " ".join(english.split())
    if english and len(english) >= 3:
        topics.append(english)
    if year:
        topics.append(year)
    return " ".join(topics) if topics else "mathematics"


def build_arxiv_search_query(query: str) -> str:
    """Turn natural language (incl. Chinese) into a valid arXiv API search_query."""
    text = query.strip()
    if not text:
        return "cat:math.NT"
    if _ARXIV_FIELD_PATTERN.search(text):
        return text

    year_match = _YEAR_PATTERN.search(text)
    year = year_match.group(1) if year_match else None
    clauses: list[str] = []

    if re.search(r"数论|number\s+theory|math\.?\s*nt", text, flags=re.IGNORECASE):
        clauses.append("cat:math.NT")
    elif re.search(r"数学|mathematics|\bmath\b", text, flags=re.IGNORECASE):
        clauses.append("cat:math*")
    elif re.search(r"物理|physics", text, flags=re.IGNORECASE):
        clauses.append("cat:physics*")
    elif re.search(r"统计|statistics|\bstat\b", text, flags=re.IGNORECASE):
        clauses.append("cat:stat*")

    english = re.sub(r"[\u4e00-\u9fff]+", " ", text)
    english = re.sub(r"\barxiv\b", " ", english, flags=re.IGNORECASE)
    english = re.sub(r"\b(20\d{2})\b", " ", english)
    english = re.sub(
        r"\b(?:famous|notable|paper|papers|preprint|preprints)\b",
        " ",
        english,
        flags=re.IGNORECASE,
    )
    english = " ".join(english.split())
    if english and len(english) >= 3:
        clauses.append(f'all:"{english}"' if " " in english else f"all:{english}")

    if year:
        clauses.append(_arxiv_date_clause(year))

    return " AND ".join(clauses) if clauses else "cat:math*"


def _research_headers() -> dict[str, str]:
    headers = {"User-Agent": _USER_AGENT}
    if settings.semantic_scholar_api_key:
        headers["x-api-key"] = settings.semantic_scholar_api_key
    return headers


async def _get_json_or_text(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
) -> httpx.Response:
    last_response: httpx.Response | None = None
    for attempt in range(2):
        response = await client.get(url, params=params, headers=_research_headers())
        last_response = response
        if response.status_code == 429 and attempt == 0:
            await asyncio.sleep(2.5)
            continue
        response.raise_for_status()
        return response
    assert last_response is not None
    last_response.raise_for_status()
    return last_response


def _normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def parse_arxiv_atom(xml_text: str, max_results: int) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    results: list[dict[str, Any]] = []
    for entry in root.findall(f"{_ATOM}entry")[:max_results]:
        title = (entry.findtext(f"{_ATOM}title") or "").strip()
        if title.lower() in {"error", "errors"}:
            continue
        summary = (entry.findtext(f"{_ATOM}summary") or "").strip()
        link = (entry.findtext(f"{_ATOM}id") or "").strip()
        published = (entry.findtext(f"{_ATOM}published") or "")[:10]
        authors = [
            (author.findtext(f"{_ATOM}name") or "").strip()
            for author in entry.findall(f"{_ATOM}author")
        ]
        results.append(
            {
                "title": " ".join(title.split()),
                "authors": [name for name in authors if name][:6],
                "published": published,
                "summary": " ".join(summary.split())[:600],
                "url": link,
                "doi": None,
                "source": "arXiv",
            }
        )
    return results


def parse_oeis(payload: Any, max_results: int) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        entries = payload.get("results") or []
    elif isinstance(payload, list):
        entries = payload
    else:
        entries = []
    results: list[dict[str, Any]] = []
    for entry in entries[:max_results]:
        if not isinstance(entry, dict):
            continue
        number = entry.get("number")
        results.append(
            {
                "id": f"A{number:06d}" if isinstance(number, int) else str(number),
                "name": (entry.get("name") or "").strip(),
                "terms": (entry.get("data") or "").split(",")[:20],
                "url": f"https://oeis.org/A{number:06d}" if isinstance(number, int) else None,
            }
        )
    return results


def parse_crossref(payload: dict[str, Any], max_results: int) -> list[dict[str, Any]]:
    items = (payload.get("message") or {}).get("items") or []
    results: list[dict[str, Any]] = []
    for item in items[:max_results]:
        titles = item.get("title") or []
        title = " ".join((titles[0] if titles else "").split())
        if re.search(r"editorial board", title, flags=re.IGNORECASE):
            continue
        authors = [
            " ".join(filter(None, [person.get("given"), person.get("family")]))
            for person in item.get("author") or []
        ]
        issued = item.get("issued") or {}
        parts = (issued.get("date-parts") or [[None]])[0]
        results.append(
            {
                "title": title,
                "authors": [name for name in authors if name][:6],
                "year": parts[0] if parts else None,
                "container": " ".join((item.get("container-title") or [""])[0].split()) or None,
                "doi": item.get("DOI"),
                "url": item.get("URL"),
                "source": "Crossref",
            }
        )
    return results


def parse_semantic_scholar(payload: dict[str, Any], max_results: int) -> list[dict[str, Any]]:
    items = payload.get("data") or []
    results: list[dict[str, Any]] = []
    for item in items[:max_results]:
        if not isinstance(item, dict):
            continue
        authors = [
            (person.get("name") or "").strip()
            for person in item.get("authors") or []
            if isinstance(person, dict)
        ]
        results.append(
            {
                "title": " ".join((item.get("title") or "").split()),
                "authors": [name for name in authors if name][:6],
                "year": item.get("year"),
                "abstract": " ".join((item.get("abstract") or "").split())[:600] or None,
                "doi": item.get("externalIds", {}).get("DOI")
                if isinstance(item.get("externalIds"), dict)
                else None,
                "url": item.get("url")
                or (
                    f"https://www.semanticscholar.org/paper/{item['paperId']}"
                    if item.get("paperId")
                    else None
                ),
                "citation_count": item.get("citationCount"),
                "source": "Semantic Scholar",
            }
        )
    return results


def dedupe_literature(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop duplicates by DOI first, then by normalized title."""
    seen_doi: set[str] = set()
    seen_title: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in records:
        doi = (item.get("doi") or "").strip().lower()
        title_key = _normalize_title(item.get("title") or "")
        if doi and doi in seen_doi:
            continue
        if title_key and title_key in seen_title:
            continue
        if doi:
            seen_doi.add(doi)
        if title_key:
            seen_title.add(title_key)
        unique.append(item)
    return unique


async def arxiv_search(query: str, max_results: int = 5) -> dict[str, Any]:
    max_results = max(1, min(int(max_results or 5), 10))
    try:
        async with httpx.AsyncClient(
            timeout=settings.research_tool_timeout,
            follow_redirects=True,
        ) as client:
            response = await _get_json_or_text(
                client,
                ARXIV_API,
                params={
                    "search_query": build_arxiv_search_query(query),
                    "start": 0,
                    "max_results": max_results,
                    "sortBy": "submittedDate",
                    "sortOrder": "descending",
                },
            )
        results = parse_arxiv_atom(response.text, max_results)
        return {"ok": True, "source": "arXiv", "results": results}
    except (httpx.HTTPError, ET.ParseError) as exc:
        return {"ok": False, "source": "arXiv", "error": str(exc)}


async def oeis_search(query: str, max_results: int = 3) -> dict[str, Any]:
    max_results = max(1, min(int(max_results or 3), 10))
    try:
        async with httpx.AsyncClient(
            timeout=settings.research_tool_timeout,
            follow_redirects=True,
        ) as client:
            response = await _get_json_or_text(client, OEIS_API, params={"q": query, "fmt": "json"})
        results = parse_oeis(response.json(), max_results)
        return {"ok": True, "source": "OEIS", "results": results}
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "source": "OEIS", "error": str(exc)}


async def crossref_search(query: str, max_results: int = 5) -> dict[str, Any]:
    max_results = max(1, min(int(max_results or 5), 10))
    try:
        async with httpx.AsyncClient(
            timeout=settings.research_tool_timeout,
            follow_redirects=True,
        ) as client:
            response = await _get_json_or_text(
                client,
                CROSSREF_API,
                params={
                    "query": query,
                    "rows": max_results,
                    "filter": "type:journal-article",
                    "sort": "published",
                    "order": "desc",
                },
            )
        results = parse_crossref(response.json(), max_results)
        return {"ok": True, "source": "Crossref", "results": results}
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "source": "Crossref", "error": str(exc)}


async def semantic_scholar_search(query: str, max_results: int = 5) -> dict[str, Any]:
    max_results = max(1, min(int(max_results or 5), 10))
    try:
        async with httpx.AsyncClient(
            timeout=settings.research_tool_timeout,
            follow_redirects=True,
        ) as client:
            response = await _get_json_or_text(
                client,
                SEMANTIC_SCHOLAR_API,
                params={
                    "query": query,
                    "limit": max_results,
                    "fields": "title,authors,year,abstract,url,externalIds,citationCount,paperId",
                },
            )
        results = parse_semantic_scholar(response.json(), max_results)
        return {"ok": True, "source": "Semantic Scholar", "results": results}
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "source": "Semantic Scholar", "error": str(exc)}


async def literature_search(query: str, max_results: int = 5) -> dict[str, Any]:
    """Fan-out to arXiv + Crossref + Semantic Scholar and dedupe."""
    max_results = max(1, min(int(max_results or 5), 10))
    general_query = normalize_literature_query(query)
    batches = await asyncio.gather(
        arxiv_search(query, max_results),
        crossref_search(general_query, max_results),
        semantic_scholar_search(general_query, max_results),
    )
    merged: list[dict[str, Any]] = []
    errors: list[str] = []
    for batch in batches:
        if batch.get("ok") and batch.get("results"):
            merged.extend(batch.get("results") or [])
        elif batch.get("error"):
            errors.append(f"{batch.get('source')}: {batch['error']}")
    unique = dedupe_literature(merged)[: max_results * 2]
    return {
        "ok": bool(unique),
        "source": "literature(arXiv+Crossref+S2)",
        "results": unique,
        "errors": errors,
    }
