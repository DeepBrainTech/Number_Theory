"""Tools that give Auto Prove QED-like affordances without host bash.

Fetch is limited to public http(s). Run-directory file tools live on RunStore.
"""

from __future__ import annotations

import html
import ipaddress
import re
import socket
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from .config import settings


_USER_AGENT = "ProofLab/0.5 (auto-prove; citation-check)"
_MAX_FETCH_BYTES = 5 * 1024 * 1024
_MAX_TEXT_CHARS = 80_000
_MAX_PDF_PAGES = 40
_FETCH_TIMEOUT = 20.0
_MAX_REDIRECTS = 4

_PRIVATE_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata.internal",
}


class _HTMLTextParser(HTMLParser):
    _skip = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._skip:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._skip and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = html.unescape(data).strip()
        if text:
            self._parts.append(text)

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "\n".join(self._parts)).strip()


def html_to_text(raw: str) -> str:
    parser = _HTMLTextParser()
    parser.feed(raw)
    parser.close()
    return parser.text()


def validate_public_http_url(url: str) -> str:
    """Reject non-http(s) URLs and hosts that resolve to private/reserved addresses."""
    text = (url or "").strip()
    if not text:
        raise ValueError("url is required")
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http(s) URLs are allowed")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ValueError("URL host is required")
    if host in _PRIVATE_HOSTS or host.endswith(".localhost"):
        raise ValueError("Private hosts are not allowed")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve host: {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ValueError("Private or reserved addresses are not allowed")
    return text


async def _get_public(url: str) -> httpx.Response:
    current = validate_public_http_url(url)
    headers = {"User-Agent": _USER_AGENT, "Accept": "*/*"}
    timeout = httpx.Timeout(_FETCH_TIMEOUT)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, headers=headers) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            response = await client.get(current)
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise ValueError("Redirect without Location")
                current = validate_public_http_url(urljoin(current, location))
                continue
            response.raise_for_status()
            length = response.headers.get("content-length")
            if length and int(length) > _MAX_FETCH_BYTES:
                raise ValueError("Response is larger than 5 MB")
            body = response.content
            if len(body) > _MAX_FETCH_BYTES:
                raise ValueError("Response is larger than 5 MB")
            return response
    raise ValueError("Too many redirects")


def _clip(text: str) -> tuple[str, bool]:
    if len(text) <= _MAX_TEXT_CHARS:
        return text, False
    return text[:_MAX_TEXT_CHARS], True


async def fetch_url(url: str) -> dict[str, Any]:
    try:
        response = await _get_public(url)
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "url": url, "error": str(exc)}
    content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
    if "pdf" in content_type or url.lower().endswith(".pdf"):
        return await fetch_pdf_text(url, _response=response)
    raw = response.text
    text, truncated = _clip(html_to_text(raw) or raw)
    return {
        "ok": True,
        "url": str(response.url),
        "content_type": content_type or "text/html",
        "text": text,
        "truncated": truncated,
    }


async def fetch_pdf_text(url: str, *, _response: httpx.Response | None = None) -> dict[str, Any]:
    try:
        response = _response or await _get_public(url)
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "url": url, "error": str(exc)}
    try:
        from io import BytesIO

        from pypdf import PdfReader

        reader = PdfReader(BytesIO(response.content))
        pages: list[str] = []
        for page in reader.pages[:_MAX_PDF_PAGES]:
            pages.append(page.extract_text() or "")
        text, truncated = _clip("\n\n".join(part for part in pages if part.strip()))
        if not text.strip():
            return {"ok": False, "url": str(response.url), "error": "No extractable PDF text"}
        truncated = truncated or len(reader.pages) > _MAX_PDF_PAGES
        return {
            "ok": True,
            "url": str(response.url),
            "pages": min(len(reader.pages), _MAX_PDF_PAGES),
            "text": text,
            "truncated": truncated,
        }
    except Exception as exc:  # noqa: BLE001 - PDF parse failures must not abort a run
        return {"ok": False, "url": url, "error": f"PDF extract failed: {exc}"}


def _fn(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


FETCH_URL_TOOL = _fn(
    "fetch_url",
    "Fetch a public http(s) page and return readable text. Use this to verify citations against the source.",
    {"url": {"type": "string"}},
    ["url"],
)
FETCH_PDF_TOOL = _fn(
    "fetch_pdf_text",
    "Download a public PDF (arXiv pdf, journal reprint) and extract text for citation checking.",
    {"url": {"type": "string"}},
    ["url"],
)
LIST_RUN_FILES_TOOL = _fn(
    "list_run_files",
    "List files in this Auto Prove run directory. Optional prefix limits the listing to a subdirectory.",
    {
        "prefix": {
            "type": ["string", "null"],
            "description": "Optional relative subdirectory, e.g. related_info or attempt_1/revision_1.",
        }
    },
    ["prefix"],
)
READ_RUN_FILE_TOOL = _fn(
    "read_run_file",
    "Read a file from this run directory. Paths are relative (problem.md, proof.md, related_info/related_work.md).",
    {
        "path": {"type": "string"},
        "offset": {"type": ["integer", "null"], "description": "Character offset; default 0."},
        "limit": {"type": ["integer", "null"], "description": "Max characters; default 40000."},
    },
    ["path", "offset", "limit"],
)
WRITE_RUN_FILE_TOOL = _fn(
    "write_run_file",
    "Write a UTF-8 text file inside this run directory. Use this for every required QED output path.",
    {
        "path": {"type": "string"},
        "content": {"type": "string"},
    },
    ["path", "content"],
)
SAGE_EXECUTE_TOOL = _fn(
    "sage_execute",
    "Run SageMath code in the isolated Sage sandbox and return stdout. Print the values you need. "
    "Use for calculations beyond sage_calculate's named operations. Do not expect network or host files.",
    {"code": {"type": "string"}},
    ["code"],
)


def file_tools(*, writable: bool) -> list[dict[str, Any]]:
    tools = [LIST_RUN_FILES_TOOL, READ_RUN_FILE_TOOL]
    if writable:
        tools.append(WRITE_RUN_FILE_TOOL)
    return tools


def research_agent_tools(base: list[dict[str, Any]], extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sage + literature + web + fetch + run files + Sage REPL."""
    return [*base, *extra, FETCH_URL_TOOL, FETCH_PDF_TOOL, SAGE_EXECUTE_TOOL, *file_tools(writable=True)]
