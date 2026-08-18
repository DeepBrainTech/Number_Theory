"""QED-inspired proof workflow on the Responses API.

Roles follow proofQED/QED (survey → decompose → prove → structural → detailed →
regulator). Agents work in the run directory via read/write tools, fetch public
sources to check citations, and may run SageMath in the isolated sandbox.
Artifacts are persisted under AUTO_PROVE_RUNS_DIR.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import re
import shutil
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from openai import AsyncOpenAI

from .chat import (
    BASE_TOOLS,
    RESEARCH_TOOLS,
    WEB_SEARCH_TOOL,
    execute_tool,
    has_hosted_web_search_call,
    response_output_as_input,
)
from .config import settings
from .formalize import propose_statement, verify_statement
from .prove_prompts import qed_prompt, skill_text
from .prove_tools import (
    FETCH_PDF_TOOL,
    FETCH_URL_TOOL,
    SAGE_EXECUTE_TOOL,
    file_tools,
    fetch_pdf_text,
    fetch_url,
    research_agent_tools,
)
from .verification import call_sage_execute


EventEmitter = Callable[[str, dict[str, Any]], Awaitable[None]]
Depth = Literal["quick", "deep"]
RegulatorDecision = Literal["REVISE_PROOF", "REVISE_PLAN", "REWRITE", "FINAL"]

# QED's default three-level retry hierarchy.  ``depth`` remains in the API for
# backwards compatibility, but no longer changes the QED workflow.
DEPTH_BUDGETS: dict[str, dict[str, int]] = {
    "quick": {"max_proof_attempts": 4, "max_revisions": 4, "max_decompositions": 4},
    "deep": {"max_proof_attempts": 4, "max_revisions": 4, "max_decompositions": 4},
}

# QED coding agents run until they finish writing files. These ceilings are high
# enough for repeated search / citation fetches without matching host bash.
SURVEY_ROUNDS = 48
DECOMPOSE_ROUNDS = 32
PROVE_ROUNDS = 48
VERIFY_ROUNDS = 40
LIGHT_ROUNDS = 8

_MAX_RUN_FILE_CHARS = 400_000
_READ_DEFAULT = 40_000
_FORBIDDEN_WRITES = {"checkpoint.json", "call_log.jsonl", "result.json"}
_AGENT_TOOLS = research_agent_tools([WEB_SEARCH_TOOL, *BASE_TOOLS], RESEARCH_TOOLS)
_VERIFY_TOOLS = [
    WEB_SEARCH_TOOL,
    *BASE_TOOLS,
    SAGE_EXECUTE_TOOL,
    FETCH_URL_TOOL,
    FETCH_PDF_TOOL,
    *RESEARCH_TOOLS,
    *file_tools(writable=True),
]
_READ_TOOLS = file_tools(writable=False)

_JSON_BLOCK = re.compile(r"\{[^{}]*\"pass\"[^{}]*\}", re.DOTALL)
_YAML_FENCE = re.compile(r"```(?:yaml|yml)\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
_HEADING = re.compile(r"^## Classification:\s*(Easy|Medium|Hard)\s*$", re.IGNORECASE | re.MULTILINE)
_CURRENT_RUN: contextvars.ContextVar[RunStore | None] = contextvars.ContextVar("auto_prove_run", default=None)
_CANCEL_EVENTS: dict[str, asyncio.Event] = {}
_ACTIVE_TASKS: dict[str, asyncio.Task[Any]] = {}
_RUN_SUBSCRIBERS: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}


def subscribe_run_events(run_id: str) -> asyncio.Queue[dict[str, Any]]:
    """Listen for live status/result events of an in-flight run."""
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    _RUN_SUBSCRIBERS.setdefault(run_id, set()).add(queue)
    return queue


def unsubscribe_run_events(run_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
    subscribers = _RUN_SUBSCRIBERS.get(run_id)
    if not subscribers:
        return
    subscribers.discard(queue)
    if not subscribers:
        _RUN_SUBSCRIBERS.pop(run_id, None)


async def publish_run_event(run_id: str, event: dict[str, Any]) -> None:
    for queue in list(_RUN_SUBSCRIBERS.get(run_id, ())):
        await queue.put(event)


class AutoProveCancelled(Exception):
    """Raised when a user cancels an in-flight Auto Prove run."""


def request_cancel(run_id: str) -> bool:
    """Signal cancel for ``run_id`` and cancel its asyncio task if this process owns it."""
    found = False
    event = _CANCEL_EVENTS.get(run_id)
    if event is not None:
        event.set()
        found = True
    task = _ACTIVE_TASKS.get(run_id)
    current = asyncio.current_task()
    if task is not None and not task.done() and task is not current:
        task.cancel()
        found = True
    return found


def _register_run(run_id: str) -> asyncio.Event:
    event = _CANCEL_EVENTS.get(run_id)
    if event is None:
        event = asyncio.Event()
        _CANCEL_EVENTS[run_id] = event
    task = asyncio.current_task()
    if task is not None:
        _ACTIVE_TASKS[run_id] = task
    return event


def _unregister_run(run_id: str | None) -> None:
    if not run_id:
        return
    _CANCEL_EVENTS.pop(run_id, None)
    current = asyncio.current_task()
    owned = _ACTIVE_TASKS.get(run_id)
    if owned is None or owned is current or owned.done():
        _ACTIVE_TASKS.pop(run_id, None)


def _ensure_not_cancelled(run_id: str | None = None) -> None:
    if run_id is None:
        store = _CURRENT_RUN.get()
        run_id = store.root.name if store else None
    if not run_id:
        return
    event = _CANCEL_EVENTS.get(run_id)
    if event is not None and event.is_set():
        raise AutoProveCancelled()


def mark_run_cancelled(run_id: str, store: RunStore | None = None, *, owner_id: str | None = None) -> dict[str, Any]:
    """Persist cancelled status to disk (and DB when ``owner_id`` is known)."""
    store = store or open_run_store(run_id)
    if store:
        store.log("Cancelled by user")
        store.write("STATUS.md", f"# Auto Prove Status\n\nCancelled by user\n\n- Updated: {_now()}\n")
        store.write(
            "result.json",
            json.dumps(
                {"ok": False, "error": "Cancelled by user", "run_id": run_id, "passed": False},
                ensure_ascii=False,
                indent=2,
            ),
        )
    if owner_id:
        from .prove_runs import touch_run

        touch_run(run_id, owner_id, status="cancelled", phase="cancelled", error="Cancelled by user", current_tool="")
    return {
        "ok": False,
        "error": "Cancelled by user",
        "run_id": run_id,
        "run_dir": str(store.root) if store else None,
        "passed": False,
    }


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class RunStore:
    """Server-side artifact directory for one Auto Prove run."""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._log = self.root / "log.txt"

    @classmethod
    def create(cls, run_id: str | None = None) -> tuple[str, RunStore]:
        run_id = run_id or uuid.uuid4().hex[:12]
        store = cls(settings.auto_prove_runs_dir / run_id)
        return run_id, store

    def resolve(self, relative: str) -> Path:
        """Resolve a run-relative path, rejecting traversal outside the run directory."""
        text = (relative or "").replace("\\", "/").strip()
        if not text or text.startswith("/") or ":" in Path(text).parts[0]:
            raise ValueError("path must be a relative file inside this run")
        candidate = Path(text)
        if ".." in candidate.parts or candidate.is_absolute():
            raise ValueError("path must not contain '..' or be absolute")
        path = (self.root / candidate).resolve()
        root = self.root.resolve()
        if path != root and root not in path.parents:
            raise ValueError("path escapes the run directory")
        return path

    def write(self, relative: str, content: str) -> Path:
        path = self.resolve(relative) if relative not in {".", ""} else self.root
        if path == self.root:
            raise ValueError("path must be a file, not the run root")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")
        return path

    def read(self, relative: str) -> str:
        try:
            path = self.resolve(relative)
        except ValueError:
            return ""
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8")

    def list_files(self, prefix: str | None = None) -> list[str]:
        root = self.root.resolve()
        start = root
        if prefix:
            start = self.resolve(prefix)
            if start.is_file():
                return [start.relative_to(root).as_posix()]
        files: list[str] = []
        if not start.exists():
            return files
        for path in sorted(start.rglob("*") if start.is_dir() else []):
            if path.is_file():
                files.append(path.relative_to(root).as_posix())
        return files

    def read_slice(self, relative: str, offset: int | None, limit: int | None) -> dict[str, Any]:
        path = self.resolve(relative)
        if not path.is_file():
            return {"ok": False, "path": relative, "error": "File not found"}
        text = path.read_text(encoding="utf-8")
        start = max(int(offset or 0), 0)
        size = int(limit) if limit is not None else _READ_DEFAULT
        size = max(1, min(size, _READ_DEFAULT * 2))
        chunk = text[start : start + size]
        return {
            "ok": True,
            "path": path.relative_to(self.root.resolve()).as_posix(),
            "offset": start,
            "length": len(chunk),
            "total": len(text),
            "truncated": start + len(chunk) < len(text),
            "content": chunk,
        }

    def write_safe(self, relative: str, content: str) -> dict[str, Any]:
        if Path(relative.replace("\\", "/")).name in _FORBIDDEN_WRITES:
            return {"ok": False, "path": relative, "error": "This file is reserved for the server"}
        if len(content) > _MAX_RUN_FILE_CHARS:
            return {"ok": False, "path": relative, "error": f"File exceeds {_MAX_RUN_FILE_CHARS} characters"}
        path = self.write(relative, content)
        return {
            "ok": True,
            "path": path.relative_to(self.root.resolve()).as_posix(),
            "bytes": path.stat().st_size,
        }

    def log(self, message: str) -> None:
        line = f"[{_now()}] {message}\n"
        with self._log.open("a", encoding="utf-8") as handle:
            handle.write(line)

    def record_call(self, role: str, started_at: str, elapsed_seconds: float, response: Any) -> None:
        """Append a durable, provider-agnostic model-call audit record."""
        path = self.root / "call_log.jsonl"
        usage = getattr(response, "usage", None)
        record = {
            "role": role,
            "started_at": started_at,
            "elapsed_seconds": round(elapsed_seconds, 3),
            "model": settings.deepseek_model,
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.write_token_usage()

    def write_token_usage(self) -> None:
        path = self.root / "call_log.jsonl"
        if not path.exists():
            return
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        input_total = sum(int(row.get("input_tokens") or 0) for row in rows)
        output_total = sum(int(row.get("output_tokens") or 0) for row in rows)
        lines = [
            "# TOKEN_USAGE",
            "",
            f"- Calls: {len(rows)}",
            f"- Input tokens: {input_total}",
            f"- Output tokens: {output_total}",
            f"- Total tokens: {input_total + output_total}",
            "",
        ]
        for index, row in enumerate(rows, start=1):
            lines.append(
                f"{index}. `{row.get('role')}` · {row.get('elapsed_seconds')}s · "
                f"in={row.get('input_tokens')} out={row.get('output_tokens')}"
            )
        self.write("TOKEN_USAGE.md", "\n".join(lines))
        self.write(
            "token_usage.json",
            json.dumps(
                {"calls": len(rows), "input_tokens": input_total, "output_tokens": output_total, "rows": rows},
                ensure_ascii=False,
                indent=2,
            ),
        )

    def human_guidance(self) -> str:
        return self.read("human_guidance.md")

    def append_human_guidance(self, guidance: str) -> None:
        existing = self.human_guidance()
        self.write("human_guidance.md", f"{existing}\n\n## {_now()}\n\n{guidance}".strip())

    def checkpoint(self, phase: str, state: LoopState) -> None:
        self.write(
            "checkpoint.json",
            json.dumps({"phase": phase, "updated_at": _now(), "state": state.__dict__}, ensure_ascii=False, indent=2),
        )

    def artifact_context(self, limit: int = 80_000) -> str:
        """Provide later agents a bounded, auditable view of prior artifacts."""
        parts: list[str] = []
        used = 0
        for path in sorted(
            self.root.rglob("*"),
            key=lambda item: (0 if item.parts[-2:-1] == ("references",) else 1, str(item)),
        ):
            if not path.is_file() or path.name in {"call_log.jsonl", "checkpoint.json", "log.txt"}:
                continue
            try:
                content = path.read_text(encoding="utf-8").strip()
            except UnicodeDecodeError:
                continue
            block = f"\n\n## Artifact: {path.relative_to(self.root).as_posix()}\n\n{content}"
            if used + len(block) > limit:
                parts.append(f"\n\n[Artifact context capped at {limit} characters; see the artifact index in the run UI.]")
                break
            parts.append(block)
            used += len(block)
        return "".join(parts)

    def proof_dir(self, attempt: int, revision: int, proof: int) -> str:
        return f"attempt_{attempt}/revision_{revision}/proof_{proof}"


def open_run_store(run_id: str) -> RunStore | None:
    """Open one run without permitting paths outside AUTO_PROVE_RUNS_DIR."""
    if not re.fullmatch(r"[a-f0-9]{12}", run_id):
        return None
    root = (settings.auto_prove_runs_dir / run_id).resolve()
    if root.parent != settings.auto_prove_runs_dir.resolve() or not root.is_dir():
        return None
    return RunStore(root)


def delete_run_artifacts(run_id: str) -> bool:
    """Remove one validated run directory without allowing path traversal."""
    store = open_run_store(run_id)
    if store is None:
        return False
    shutil.rmtree(store.root)
    return True


def run_artifacts(run_id: str) -> dict[str, Any] | None:
    store = open_run_store(run_id)
    if not store:
        return None
    files = sorted(
        str(path.relative_to(store.root)).replace("\\", "/")
        for path in store.root.rglob("*")
        if path.is_file()
    )
    result_text = store.read("result.json")
    result = json.loads(result_text) if result_text else None
    proof = store.read("proof.md").strip() or None
    plan = store.read("plan.yaml").strip() or None
    related_work = store.read("related_info/related_work.md").strip() or None
    if related_work == "(none)":
        related_work = None
    # In-progress drafts live on disk for the worker, but must not be shown as a
    # finished proof. Only ``result.json`` (written at finalize/fail/cancel) is
    # a client-visible result.
    if isinstance(result, dict):
        result = {
            **result,
            "proof": proof or result.get("proof"),
            "plan": plan or result.get("plan"),
            "related_work": related_work or result.get("related_work"),
            "review": result.get("review") or [],
        }
    return {
        "run_id": run_id,
        "status": store.read("STATUS.md"),
        "checkpoint": store.read("checkpoint.json"),
        "result": result,
        "files": files,
    }


def add_human_guidance(run_id: str, guidance: str) -> bool:
    store = open_run_store(run_id)
    if not store:
        return False
    store.append_human_guidance(guidance)
    _append_human_help(store, guidance)
    store.log("Human guidance added")
    return True


def _append_human_help(store: RunStore, guidance: str) -> None:
    note = guidance.strip()
    if not note:
        return
    existing = store.read("human_help/additional_prove_human_help_global.md")
    store.write(
        "human_help/additional_prove_human_help_global.md",
        f"{existing}\n\n## {_now()}\n\n{note}".strip(),
    )
    rules = extract_section(note, "Verification rules") or extract_section(note, "Additional verification rules")
    if not rules and re.match(r"(?i)^\s*(verify|verification rules)\s*[:\n]", note):
        rules = note
    if rules:
        previous = store.read("human_help/additional_verify_rule_global.md")
        store.write(
            "human_help/additional_verify_rule_global.md",
            f"{previous}\n\n## {_now()}\n\n{rules}".strip(),
        )


def _prefer_file(store: RunStore, relative: str, fallback: str) -> str:
    existing = store.read(relative).strip()
    if existing:
        return existing
    text = (fallback or "").strip()
    if text:
        store.write(relative, text)
    return text


def _seed_human_help(store: RunStore, guidance: str) -> None:
    store.write("human_help/additional_prove_human_help_global.md", guidance.strip())
    rules = extract_section(guidance, "Verification rules") or extract_section(guidance, "Additional verification rules")
    store.write("human_help/additional_verify_rule_global.md", rules)


@dataclass
class LoopState:
    attempt: int = 1
    revision: int = 1
    proof: int = 1
    plan: str = ""
    proof_text: str = ""
    related_work: str = ""
    plan_history: str = ""
    previous_proof: str = ""
    verification_feedback: str = ""
    regulator_guidance: str = ""
    review_issues: list[str] = field(default_factory=list)
    proof_attempts: int = 0
    plan_revisions: int = 0
    decompositions: int = 0


def _parse_review(text: str) -> dict[str, Any]:
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    candidates = list(_JSON_BLOCK.finditer(clean))
    blob = candidates[-1].group(0) if candidates else clean
    try:
        data = json.loads(blob)
        issues = [str(x).strip() for x in data.get("issues", []) if str(x).strip()]
        return {
            "pass": bool(data.get("pass")),
            "issues": issues,
            "revision_instructions": str(data.get("revision_instructions", "")).strip(),
            "report": text.strip(),
        }
    except (json.JSONDecodeError, TypeError):
        return {
            "pass": False,
            "issues": ["The automated referee returned an unreadable report."],
            "revision_instructions": text[:2000],
            "report": text.strip(),
        }


def parse_regulator_decision(text: str) -> RegulatorDecision:
    upper = text.upper()
    for decision in ("REVISE_PROOF", "REVISE_PLAN", "REWRITE", "FINAL"):
        if f"DECISION: {decision}" in upper:
            return decision  # type: ignore[return-value]
    if "DECISION: REVISE" in upper:
        return "REVISE_PROOF"
    return "REVISE_PROOF"


def parse_verdict(text: str) -> bool:
    """QED verdict agents return DONE only for a passing verification."""
    token = text.strip().split()[0].upper() if text.strip() else ""
    return token == "DONE"


def parse_difficulty(text: str) -> str:
    match = _HEADING.search(text)
    if match:
        return match.group(1).lower()
    lowered = text.lower()
    for level in ("easy", "medium", "hard"):
        if f"classification: {level}" in lowered:
            return level
    return "medium"


def extract_section(text: str, heading: str) -> str:
    pattern = re.compile(
        rf"^#{{1,3}} {re.escape(heading)}\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        return ""
    rest = text[match.end() :]
    nxt = re.search(r"^# ", rest, re.MULTILINE)
    body = rest[: nxt.start()] if nxt else rest
    return body.strip()


_EASY_PROOF_HEADINGS = (
    "Easy Proof",
    "`proof_file`",
    "proof_file",
    "Artifact: proof.md",
    "proof.md",
)
_EASY_PROOF_STOP = re.compile(
    r"^(?:# (?:Difficulty Evaluation|Related Work|Easy Proof)"
    r"|## `[^`]+`"
    r"|## Artifact: .+)"
    r"\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def extract_easy_proof(text: str) -> str:
    """Pull the Easy short-circuit proof from a survey response.

    Upstream QED writes ``proof.md`` on disk. This service keeps artifacts in
    the model reply, so agents may emit ``# Easy Proof`` (preferred) or a
    ``proof_file`` / ``proof.md`` heading. Nested ``# 证明`` titles must not
    truncate the body the way ``extract_section`` would.
    """
    for heading in _EASY_PROOF_HEADINGS:
        pattern = re.compile(
            rf"^#{{1,3}} {re.escape(heading)}\s*$",
            re.IGNORECASE | re.MULTILINE,
        )
        match = pattern.search(text)
        if not match:
            continue
        rest = text[match.end() :]
        stop = _EASY_PROOF_STOP.search(rest)
        body = rest[: stop.start()] if stop else rest
        body = body.strip()
        if body:
            return body
    return ""


def extract_yaml(text: str) -> str:
    fenced = _YAML_FENCE.search(text)
    if fenced:
        return fenced.group(1).strip()
    return text.strip()


def clamp_decision(
    decision: RegulatorDecision,
    state: LoopState,
    limits: dict[str, int],
) -> RegulatorDecision:
    if decision == "FINAL":
        return "FINAL"
    if decision == "REVISE_PROOF" and state.proof >= limits["max_proof_attempts"]:
        decision = "REVISE_PLAN"
    if decision == "REVISE_PLAN" and state.revision >= limits["max_revisions"]:
        decision = "REWRITE"
    if decision == "REWRITE" and state.attempt >= limits["max_decompositions"]:
        return "FINAL"
    return decision


def _with_skill(prompt_name: str, paths: dict[str, str] | None = None) -> str:
    names = {
        "literature_survey.md": "literature_survey.md",
        "decomposition.md": "decomposition.md",
        "prover.md": "single_prover.md",
    }
    target = (
        "decomposition-prover/" + names[prompt_name]
        if prompt_name in {"decomposition.md", "prover.md"}
        else names.get(prompt_name, prompt_name)
    )
    body = qed_prompt(target, paths)
    if prompt_name in {"literature_survey.md", "decomposition.md", "prover.md"}:
        return skill_text() + "\n\n---\n\n" + body
    return body


async def execute_prove_tool(name: str, arguments: dict[str, Any], store: RunStore | None) -> dict[str, Any]:
    try:
        if name == "list_run_files":
            if store is None:
                return {"tool": name, "ok": False, "error": "No active run"}
            prefix = arguments.get("prefix")
            files = store.list_files(str(prefix) if prefix else None)
            return {"tool": name, "ok": True, "files": files, "count": len(files)}
        if name == "read_run_file":
            if store is None:
                return {"tool": name, "ok": False, "error": "No active run"}
            return {"tool": name, **store.read_slice(str(arguments.get("path") or ""), arguments.get("offset"), arguments.get("limit"))}
        if name == "write_run_file":
            if store is None:
                return {"tool": name, "ok": False, "error": "No active run"}
            return {
                "tool": name,
                **store.write_safe(str(arguments.get("path") or ""), str(arguments.get("content") or "")),
            }
        if name == "fetch_url":
            return {"tool": name, **await fetch_url(str(arguments.get("url") or ""))}
        if name == "fetch_pdf_text":
            return {"tool": name, **await fetch_pdf_text(str(arguments.get("url") or ""))}
        if name == "sage_execute":
            result = await call_sage_execute(str(arguments.get("code") or ""))
            return {"tool": name, **result}
        return await execute_tool(name, arguments)
    except (ValueError, OSError) as exc:
        return {"tool": name, "ok": False, "error": str(exc)}


async def _ask(
    instructions: str,
    payload: dict[str, Any],
    *,
    tools: list[dict[str, Any]] | None,
    max_rounds: int,
    emit: EventEmitter | None = None,
) -> str:
    _ensure_not_cancelled()
    run = _CURRENT_RUN.get()
    if run and run.human_guidance():
        payload = {**payload, "human_guidance": run.human_guidance()}
    if run:
        payload = {**payload, "run_files": run.list_files()}
    started = datetime.now(timezone.utc)
    client = _client()
    input_items: list[dict[str, Any]] = [
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}
    ]
    kwargs: dict[str, Any] = {
        "model": settings.deepseek_model,
        "instructions": instructions,
        "input": input_items,
    }
    if tools:
        kwargs["tools"] = tools
    response = await client.responses.create(**kwargs)
    active_tools = list(tools or [])
    for _ in range(max_rounds):
        _ensure_not_cancelled()
        calls = [item for item in (response.output or []) if getattr(item, "type", None) == "function_call"]
        if not calls:
            if has_hosted_web_search_call(response):
                # Keep web_search available so later turns can search again.
                input_items.extend(response_output_as_input(response))
                follow = {
                    "model": settings.deepseek_model,
                    "instructions": instructions,
                    "input": input_items,
                }
                if active_tools:
                    follow["tools"] = active_tools
                response = await client.responses.create(**follow)
                continue
            break
        outputs: list[dict[str, Any]] = []
        for call in calls:
            _ensure_not_cancelled()
            try:
                arguments = json.loads(call.arguments)
            except json.JSONDecodeError:
                arguments = {}
            if emit:
                await emit("tool", {"label": f"Tool: {call.name}", "tool": call.name})
            result = await execute_prove_tool(call.name, arguments, run)
            if emit:
                await emit("tool_complete", {"tool": call.name})
            outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(result, ensure_ascii=False),
                }
            )
        input_items.extend(response_output_as_input(response))
        input_items.extend(outputs)
        follow = {
            "model": settings.deepseek_model,
            "instructions": instructions,
            "input": input_items,
        }
        if active_tools:
            follow["tools"] = active_tools
        response = await client.responses.create(**follow)
    text = (response.output_text or "").strip()
    if not text:
        retry = await client.responses.create(
            model=settings.deepseek_model,
            instructions=(
                f"{instructions}\n\nReturn a non-empty final textual answer now. "
                "Do not make further tool calls. If an output file was required, "
                "summarize what you wrote."
            ),
            input=input_items,
            tool_choice="none",
        )
        text = (retry.output_text or "").strip()
        if not text:
            raise RuntimeError("DeepSeek returned an empty response after one retry.")
    if run:
        role = str(payload.get("mode") or payload.get("verification_phase") or payload.get("role") or "agent")
        run.record_call(role, started.strftime("%Y-%m-%dT%H:%M:%SZ"), (datetime.now(timezone.utc) - started).total_seconds(), response)
    return text


async def run_auto_prove(
    problem: str,
    guidance: str,
    depth: str,
    formalize: bool,
    emit: EventEmitter | None = None,
    run_id: str | None = None,
    resume: bool = False,
    owner_id: str | None = None,
    references: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Run the QED-style proof loop and return artifacts plus a run directory."""
    if not settings.deepseek_api_key:
        return {"ok": False, "error": "DEEPSEEK_API_KEY is not configured."}

    limits = DEPTH_BUDGETS.get(depth, DEPTH_BUDGETS["quick"])
    resuming = bool(resume and run_id)
    if resuming:
        store = open_run_store(run_id or "")
        if store is None:
            return {"ok": False, "error": "The requested research run does not exist."}
        checkpoint_text = store.read("checkpoint.json")
        try:
            restored = json.loads(checkpoint_text).get("state", {})
            state = LoopState(**{name: restored[name] for name in LoopState.__dataclass_fields__ if name in restored})
        except (json.JSONDecodeError, TypeError):
            state = LoopState()
        problem = store.read("problem.md") or problem
        guidance = store.read("guidance.md") or guidance
    else:
        run_id, store = RunStore.create()
        state = LoopState()
    assert run_id is not None
    run_token = _CURRENT_RUN.set(store)
    _register_run(run_id)
    # Search, literature, Sage, citation fetch, and run-directory file tools.
    all_tools = _AGENT_TOOLS
    sage_tools = _VERIFY_TOOLS

    if owner_id and run_id:
        from .prove_runs import create_run

        create_run(
            run_id=run_id,
            client_id=owner_id,
            problem=problem,
            guidance=guidance,
            depth=depth,
            formalize=formalize,
        )

    raw_emit = emit

    async def tracked_emit(phase: str, details: dict[str, Any] | None = None) -> None:
        payload = {"run_id": run_id, **(details or {})}
        label = str(payload.get("label") or phase)
        if owner_id and run_id:
            from .prove_runs import touch_run

            if phase == "tool":
                touch_run(
                    run_id,
                    owner_id,
                    status="running",
                    phase=label,
                    current_tool=str(payload.get("tool") or ""),
                )
            elif phase == "tool_complete":
                touch_run(run_id, owner_id, current_tool="")
            elif phase != "complete":
                touch_run(run_id, owner_id, status="running", phase=label, current_tool="")
        await publish_run_event(run_id, {"type": "status", "phase": phase, **payload})
        if raw_emit:
            await raw_emit(phase, payload)

    async def status(phase: str, **details: Any) -> None:
        _ensure_not_cancelled(run_id)
        store.checkpoint(phase, state)
        await tracked_emit(phase, details)
        store.log(details.get("label") or phase)

    async def finish(result: dict[str, Any]) -> dict[str, Any]:
        await publish_run_event(run_id, {"type": "result", **result})
        return result

    # Emit run_id immediately so the UI can cancel before the first long model call.
    await tracked_emit("starting", {"label": "Starting proof workflow"})

    def write_status(label: str) -> None:
        store.write(
            "STATUS.md",
            "\n".join(
                [
                    "# Auto Prove Status",
                    "",
                    f"- Updated: {_now()}",
                    f"- Phase: {label}",
                    f"- Attempt: {state.attempt}/{limits['max_decompositions']}",
                    f"- Revision: {state.revision}/{limits['max_revisions']}",
                    f"- Proof: {state.proof}/{limits['max_proof_attempts']}",
                ]
            ),
        )

    try:
        if resuming:
            await status("resuming", label="Resuming research run from its last stable checkpoint")
            survey_text = store.read("related_info/survey_raw.md")
            difficulty = parse_difficulty(store.read("related_info/difficulty_evaluation.md") or survey_text)
            related_work = store.read("related_info/related_work.md")
            state.related_work = related_work
            easy_proof = store.read("proof.md") if difficulty == "easy" else ""
        else:
            store.write("problem.md", problem)
            if guidance.strip():
                store.write("guidance.md", guidance)
            _seed_human_help(store, guidance)
            store.write("error.log", "")
            store.write("plan_history.md", "# Plan History\n")
            for index, reference in enumerate(references or [], start=1):
                name = str(reference.get("name") or f"reference-{index}")
                content = str(reference.get("content") or "").strip()
                if not content:
                    continue
                safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-") or f"reference-{index}"
                store.write(f"references/{index:02d}-{safe_name}.md", f"# Source: {name}\n\n{content}")
            store.write("config.json", json.dumps({"depth": depth, "formalize": formalize, **limits}, indent=2))
            await status("surveying", label="Literature survey and difficulty check")
            write_status("surveying")
            survey_paths = {
                "problem_file": "problem.md",
                "related_info_dir": "related_info",
                "proof_file": "proof.md",
                "error_file": "error.log",
                "output_dir": ".",
            }
            survey_text = await _ask(
                _with_skill("literature_survey.md", survey_paths),
                {
                    "role": "literature_survey",
                    "read_these_files_first": ["problem.md", "guidance.md", "human_help/additional_prove_human_help_global.md"],
                },
                tools=all_tools,
                max_rounds=SURVEY_ROUNDS,
                emit=tracked_emit,
            )
            store.write("related_info/survey_raw.md", survey_text)
            evaluation = store.read("related_info/difficulty_evaluation.md").strip()
            if not evaluation:
                evaluation = extract_section(survey_text, "Difficulty Evaluation") or survey_text
                store.write("related_info/difficulty_evaluation.md", evaluation)
            difficulty = parse_difficulty(evaluation)
            related_work = store.read("related_info/related_work.md").strip()
            if not related_work:
                related_work = extract_section(survey_text, "Related Work")
                store.write("related_info/related_work.md", related_work or "(none)")
            if related_work == "(none)":
                related_work = ""
            easy_proof = store.read("proof.md").strip() or extract_easy_proof(survey_text)
            if easy_proof and difficulty == "easy" and not store.read("proof.md").strip():
                store.write("proof.md", easy_proof)
            state.related_work = related_work
            store.log(f"Difficulty classified as {difficulty}")
            if owner_id and run_id:
                from .prove_runs import touch_run

                touch_run(run_id, owner_id, difficulty=difficulty)

        if difficulty == "easy" and easy_proof.strip():
            await status("proving", label="Easy path: survey agent wrote the proof")
            state.proof_text = easy_proof.strip()
            state.plan = "Easy short-circuit: no decomposition (QED Stage 0)."
            state.proof_attempts = 1
            store.write("proof.md", state.proof_text)
            store.write("plan.yaml", state.plan)
            result = await _finalize(
                state,
                store,
                run_id,
                problem,
                formalize,
                status,
                difficulty=difficulty,
                related_work=related_work,
                passed=True,
            )
            if owner_id and run_id:
                from .prove_runs import touch_run

                touch_run(
                    run_id,
                    owner_id,
                    status="complete",
                    phase="complete",
                    difficulty=difficulty,
                    passed=True,
                    proof_attempts=state.proof_attempts,
                    revisions=state.plan_revisions,
                    decompositions=state.decompositions,
                    current_tool="",
                )
            return await finish(result)

        next_action = "prove" if resuming and state.plan else "decompose"
        passed = False

        while state.attempt <= limits["max_decompositions"]:
            revision_dir = f"attempt_{state.attempt}/revision_{state.revision}"
            plan_path = f"{revision_dir}/decomposition.yaml"
            if next_action in {"decompose", "decompose_revise"}:
                mode = "CREATE" if next_action == "decompose" and state.attempt == 1 and state.revision == 1 else (
                    "REVISE" if next_action == "decompose_revise" else "REWRITE"
                )
                await status(
                    "planning",
                    label=f"Decomposition {mode} (attempt {state.attempt}, revision {state.revision})",
                )
                write_status("planning")
                prev_rev = state.revision - 1
                prev_decomp = f"attempt_{state.attempt}/revision_{prev_rev}/decomposition.yaml" if mode == "REVISE" else ""
                prev_proof_file = ""
                if mode == "REVISE" and state.previous_proof:
                    prev_proof_file = f"attempt_{state.attempt}/revision_{prev_rev}/proof_{max(state.proof, 1)}/proof.md"
                    if not store.read(prev_proof_file).strip():
                        store.write("previous_proof.md", state.previous_proof)
                        prev_proof_file = "previous_proof.md"
                decomp_paths = {
                    "mode": mode,
                    "problem_file": "problem.md",
                    "related_work_file": "related_info/related_work.md",
                    "problem_id": run_id,
                    "attempt_number": str(state.attempt),
                    "revision_number": str(state.revision),
                    "timestamp": _now(),
                    "output_file": plan_path,
                    "current_decomposition_file": prev_decomp,
                    "verification_feedback": state.verification_feedback if mode == "REVISE" else "",
                    "regulator_guidance": state.regulator_guidance if mode in {"REVISE", "REWRITE"} else "",
                    "previous_proof_file": prev_proof_file,
                    "human_help_file": "human_help/additional_prove_human_help_global.md",
                    "plan_history_file": "plan_history.md",
                }
                plan_text = await _ask(
                    _with_skill("decomposition.md", decomp_paths),
                    {
                        "role": "decomposer",
                        "mode": mode,
                        "read_these_files_first": [
                            "problem.md",
                            "related_info/related_work.md",
                            "plan_history.md",
                            "human_help/additional_prove_human_help_global.md",
                        ],
                    },
                    tools=all_tools,
                    max_rounds=DECOMPOSE_ROUNDS,
                    emit=tracked_emit,
                )
                store.write(f"{revision_dir}/decomposer_response.md", plan_text)
                state.plan = _prefer_file(store, plan_path, extract_yaml(plan_text))
                state.decompositions += 1
                store.write("plan.yaml", state.plan)
                state.regulator_guidance = ""

            while state.proof <= limits["max_proof_attempts"]:
                await status(
                    "proving",
                    label=(
                        f"Writing proof (attempt {state.attempt}, "
                        f"revision {state.revision}, proof {state.proof})"
                    ),
                )
                write_status("proving")
                proof_rel = store.proof_dir(state.attempt, state.revision, state.proof)
                proof_path = f"{proof_rel}/proof.md"
                prev_proof_path = ""
                prev_verify_path = ""
                if state.previous_proof:
                    store.write(f"{proof_rel}/previous_proof.md", state.previous_proof)
                    prev_proof_path = f"{proof_rel}/previous_proof.md"
                if state.verification_feedback:
                    store.write(f"{proof_rel}/previous_verification.md", state.verification_feedback)
                    prev_verify_path = f"{proof_rel}/previous_verification.md"
                prover_paths = {
                    "problem_file": "problem.md",
                    "related_work_file": "related_info/related_work.md",
                    "decomposition_file": plan_path if store.read(plan_path).strip() else "plan.yaml",
                    "human_help_file": "human_help/additional_prove_human_help_global.md",
                    "previous_proof_file": prev_proof_path,
                    "previous_verification_file": prev_verify_path,
                    "output_file": proof_path,
                    "output_dir": ".",
                    "scratchpad_file": f"{proof_rel}/scratchpad.md",
                }
                proof_text = await _ask(
                    _with_skill("prover.md", prover_paths),
                    {
                        "role": "single_prover",
                        "read_these_files_first": [
                            "problem.md",
                            prover_paths["decomposition_file"],
                            "related_info/related_work.md",
                        ],
                    },
                    tools=all_tools,
                    max_rounds=PROVE_ROUNDS,
                    emit=tracked_emit,
                )
                store.write(f"{proof_rel}/prover_response.md", proof_text)
                state.proof_text = _prefer_file(store, proof_path, proof_text)
                state.proof_attempts += 1
                store.write("proof.md", state.proof_text)

                await status(
                    "reviewing",
                    label=f"Structural review {state.proof} (attempt {state.attempt})",
                )
                write_status("reviewing")
                structural_path = f"{proof_rel}/structural_verification.md"
                structural_report = await _ask(
                    qed_prompt(
                        "decomposition-prover/proof_verify_structural.md",
                        {
                            "problem_file": "problem.md",
                            "proof_file": "proof.md",
                            "decomposition_file": prover_paths["decomposition_file"],
                            "additional_verify_rule_global_file": "human_help/additional_verify_rule_global.md",
                            "output_file": structural_path,
                            "error_file": f"{proof_rel}/error_structural_verification.md",
                            "output_dir": ".",
                        },
                    ),
                    {
                        "role": "structural_verifier",
                        "read_these_files_first": [
                            "problem.md",
                            "proof.md",
                            prover_paths["decomposition_file"],
                            "human_help/additional_verify_rule_global.md",
                        ],
                    },
                    tools=sage_tools,
                    max_rounds=VERIFY_ROUNDS,
                    emit=tracked_emit,
                )
                structural_report = _prefer_file(store, structural_path, structural_report)
                structural = _parse_review(structural_report)
                structural_verdict_path = f"{proof_rel}/structural_verdict.md"
                structural_verdict_text = await _ask(
                    qed_prompt(
                        "decomposition-prover/verdict_proof.md",
                        {
                            "mode": "STRUCTURAL",
                            "structural_verification_file": structural_path,
                            "detailed_verification_file": "",
                        },
                    ),
                    {
                        "role": "verdict",
                        "mode": "STRUCTURAL",
                        "read_these_files_first": [structural_path],
                    },
                    tools=_READ_TOOLS,
                    max_rounds=LIGHT_ROUNDS,
                    emit=tracked_emit,
                )
                structural_verdict_text = _prefer_file(store, structural_verdict_path, structural_verdict_text)
                structural_passed = parse_verdict(structural_verdict_text)
                detailed = {
                    "pass": True,
                    "issues": [],
                    "revision_instructions": "",
                    "report": "Skipped: structural review failed.",
                }
                phase: Literal["structural", "detailed"] = "structural"
                detailed_path = f"{proof_rel}/detailed_verification.md"
                if structural_passed:
                    await status(
                        "reviewing",
                        label=f"Detailed review {state.proof} (attempt {state.attempt})",
                    )
                    detailed_report = await _ask(
                        qed_prompt(
                            "decomposition-prover/proof_verify_detailed.md",
                            {
                                "problem_file": "problem.md",
                                "proof_file": "proof.md",
                                "structural_report_file": structural_path,
                                "decomposition_file": prover_paths["decomposition_file"],
                                "output_file": detailed_path,
                                "error_file": f"{proof_rel}/error_detailed_verification.md",
                                "output_dir": ".",
                            },
                        ),
                        {
                            "role": "detailed_verifier",
                            "read_these_files_first": ["problem.md", "proof.md", structural_path],
                        },
                        tools=sage_tools,
                        max_rounds=VERIFY_ROUNDS,
                        emit=tracked_emit,
                    )
                    detailed_report = _prefer_file(store, detailed_path, detailed_report)
                    detailed = _parse_review(detailed_report)
                    phase = "detailed"

                final_verdict_text = "CONTINUE"
                if structural_passed:
                    final_verdict_text = await _ask(
                        qed_prompt(
                            "decomposition-prover/verdict_proof.md",
                            {
                                "mode": "FINAL",
                                "structural_verification_file": structural_path,
                                "detailed_verification_file": detailed_path,
                            },
                        ),
                        {
                            "role": "verdict",
                            "mode": "FINAL",
                            "read_these_files_first": [structural_path, detailed_path],
                        },
                        tools=_READ_TOOLS,
                        max_rounds=LIGHT_ROUNDS,
                        emit=tracked_emit,
                    )
                store.write(f"{proof_rel}/final_verdict.md", final_verdict_text)
                final_verdict_text = store.read(f"{proof_rel}/final_verdict.md").strip() or final_verdict_text

                state.review_issues = structural["issues"] + detailed["issues"]
                state.verification_feedback = (
                    f"# Structural Verification\n\n{structural['report']}\n\n"
                    f"---\n\n# Detailed Verification\n\n{detailed['report']}"
                )
                store.write(f"{proof_rel}/verification.md", state.verification_feedback)

                if parse_verdict(final_verdict_text):
                    passed = True
                    state.review_issues = []
                    break

                await status("regulating", label=f"Regulator deciding after {phase} failure")
                write_status("regulating")
                regulator_path = f"{proof_rel}/regulator_decision.md"
                attempt_history = (
                    f"proofs={state.proof_attempts}, plan_revisions={state.plan_revisions}, "
                    f"decompositions={state.decompositions}"
                )
                regulator_text = await _ask(
                    qed_prompt(
                        "decomposition-prover/regulator.md",
                        {
                            "mode": "DECIDE",
                            "verification_phase": phase,
                            "state_file": (
                                f"attempt={state.attempt}/{limits['max_decompositions']}, "
                                f"revision={state.revision}/{limits['max_revisions']}, "
                                f"proof={state.proof}/{limits['max_proof_attempts']}"
                            ),
                            "decomposition_file": prover_paths["decomposition_file"],
                            "proof_file": "proof.md",
                            "verification_report": f"{proof_rel}/verification.md",
                            "attempt_history": attempt_history,
                            "max_proof_attempts": str(limits["max_proof_attempts"]),
                            "max_revisions": str(limits["max_revisions"]),
                            "max_decompositions": str(limits["max_decompositions"]),
                            "output_file": regulator_path,
                            "plan_history_file": "plan_history.md",
                        },
                    ),
                    {
                        "role": "regulator",
                        "mode": "DECIDE",
                        "verification_phase": phase,
                        "read_these_files_first": [
                            "proof.md",
                            f"{proof_rel}/verification.md",
                            "plan_history.md",
                        ],
                    },
                    tools=[*file_tools(writable=True)],
                    max_rounds=LIGHT_ROUNDS,
                    emit=tracked_emit,
                )
                regulator_text = _prefer_file(store, regulator_path, regulator_text)
                decision = clamp_decision(parse_regulator_decision(regulator_text), state, limits)
                store.log(f"Regulator: {decision}")
                state.previous_proof = state.proof_text
                state.regulator_guidance = regulator_text
                if decision in {"REVISE_PLAN", "REWRITE"}:
                    entry = extract_section(regulator_text, "Plan History Entry") or regulator_text
                    state.plan_history = store.read("plan_history.md")
                    if f"Attempt {state.attempt} · Revision {state.revision} — {decision}" not in state.plan_history:
                        state.plan_history += (
                            f"\n\n## Attempt {state.attempt} · Revision {state.revision} — {decision}\n\n{entry}\n"
                        )
                        store.write("plan_history.md", state.plan_history)

                if decision == "REVISE_PROOF":
                    state.proof += 1
                    next_action = "prove"
                    continue
                if decision == "REVISE_PLAN":
                    state.plan_revisions += 1
                    state.revision += 1
                    state.proof = 1
                    next_action = "decompose_revise"
                    break
                if decision == "REWRITE":
                    state.attempt += 1
                    state.revision = 1
                    state.proof = 1
                    next_action = "decompose"
                    break
                next_action = "exhausted"
                break

            if passed or next_action in {"exhausted", "decompose"}:
                if next_action == "decompose" and not passed:
                    continue
                break
            if next_action == "decompose_revise":
                continue
            break

        if not passed:
            await status("regulating", label="Retry limits exhausted — failure analysis")
            failure_paths = {
                "mode": "FINAL",
                "verification_phase": "final",
                "state_file": (
                    f"attempt={state.attempt}/{limits['max_decompositions']}, "
                    f"revision={state.revision}/{limits['max_revisions']}, "
                    f"proof={state.proof}/{limits['max_proof_attempts']}"
                ),
                "decomposition_file": "plan.yaml",
                "proof_file": "proof.md",
                "verification_report": "verification.md" if store.read("verification.md") else "plan_history.md",
                "attempt_history": (
                    f"proofs={state.proof_attempts}, plan_revisions={state.plan_revisions}, "
                    f"decompositions={state.decompositions}"
                ),
                "max_proof_attempts": str(limits["max_proof_attempts"]),
                "max_revisions": str(limits["max_revisions"]),
                "max_decompositions": str(limits["max_decompositions"]),
                "output_file": "failure_analysis.md",
                "plan_history_file": "plan_history.md",
            }
            failure = await _ask(
                qed_prompt("decomposition-prover/regulator.md", failure_paths),
                {
                    "role": "regulator",
                    "mode": "FINAL",
                    "verification_phase": "final",
                    "read_these_files_first": ["proof.md", "plan.yaml", "plan_history.md"],
                },
                tools=[*file_tools(writable=True)],
                max_rounds=LIGHT_ROUNDS,
                emit=tracked_emit,
            )
            failure = _prefer_file(store, "failure_analysis.md", failure)
            if failure.strip():
                state.review_issues = list(dict.fromkeys([*state.review_issues, "Retry limits exhausted."]))

        # QED Stage 2: preserve a readable account of the entire effort after
        # either a verified proof or exhaustive failure.  Easy problems return
        # above, matching QED's Stage-0 short circuit.
        await status("summarizing", label="QED proof-effort summary")
        write_status("summarizing")
        summary = await _ask(
            qed_prompt(
                "proof_effort_summary.md",
                {
                    "summary_file": "proof_effort_summary.md",
                    "output_dir": ".",
                },
            ),
            {
                "role": "proof_summary",
                "read_these_files_first": [
                    "problem.md",
                    "proof.md",
                    "TOKEN_USAGE.md",
                    "related_info/difficulty_evaluation.md",
                    "plan_history.md",
                ],
            },
            tools=[*file_tools(writable=True)],
            max_rounds=LIGHT_ROUNDS,
            emit=tracked_emit,
        )
        summary = _prefer_file(store, "proof_effort_summary.md", summary)
        store.write("proof_effort_summary.md", summary)

        result = await _finalize(
            state,
            store,
            run_id,
            problem,
            formalize,
            status,
            difficulty=difficulty,
            related_work=related_work,
            passed=passed,
        )
        if owner_id and run_id:
            from .prove_runs import touch_run

            touch_run(
                run_id,
                owner_id,
                status="complete" if result.get("ok") else "failed",
                phase="complete",
                difficulty=difficulty,
                passed=passed,
                proof_attempts=state.proof_attempts,
                revisions=state.plan_revisions,
                decompositions=state.decompositions,
                error=None if result.get("ok") else str(result.get("error") or "failed"),
                current_tool="",
            )
        return await finish(result)
    except (AutoProveCancelled, asyncio.CancelledError):
        return await finish(mark_run_cancelled(run_id, store, owner_id=owner_id))
    except Exception as exc:  # noqa: BLE001 - API failures must become a client result
        store.log(f"ERROR: {exc}")
        store.write("STATUS.md", f"# Auto Prove Status\n\nFailed: {exc}\n")
        failed = {
            "ok": False,
            "error": f"Auto Prove failed: {exc}",
            "run_id": run_id,
            "run_dir": str(store.root),
            "passed": False,
        }
        store.write("result.json", json.dumps(failed, ensure_ascii=False, indent=2))
        if owner_id and run_id:
            from .prove_runs import touch_run

            touch_run(
                run_id,
                owner_id,
                status="failed",
                phase="failed",
                proof_attempts=state.proof_attempts,
                revisions=state.plan_revisions,
                decompositions=state.decompositions,
                error=str(exc),
                current_tool="",
            )
        return await finish(failed)
    finally:
        _unregister_run(run_id)
        _CURRENT_RUN.reset(run_token)


async def _finalize(
    state: LoopState,
    store: RunStore,
    run_id: str,
    problem: str,
    formalize: bool,
    status: EventEmitter,
    *,
    difficulty: str,
    related_work: str,
    passed: bool,
) -> dict[str, Any]:
    formalization: dict[str, Any] | None = None
    if formalize and state.proof_text:
        await status("formalizing", label="Attempting Lean formalization")
        statement_result = await propose_statement(problem, state.proof_text)
        if statement_result.get("ok"):
            formalization = await verify_statement(
                problem,
                str(statement_result.get("statement") or ""),
                method=state.proof_text,
            )
        else:
            formalization = statement_result

    await status(
        "complete",
        label="Proof workflow complete" if passed else "Proof workflow finished without a passing review",
    )
    store.write(
        "STATUS.md",
        f"# Auto Prove Status\n\n- Result: {'PASS' if passed else 'FAIL'}\n- Updated: {_now()}\n",
    )
    store.write(
        "result.json",
        json.dumps(
            {
                "ok": True,
                "passed": passed,
                "difficulty": difficulty,
                "proof_attempts": state.proof_attempts,
                "revisions": state.plan_revisions,
                "decompositions": state.decompositions,
            },
            indent=2,
        ),
    )
    return {
        "ok": True,
        "proof": state.proof_text or None,
        "plan": state.plan or None,
        "review": state.review_issues,
        "revisions": state.plan_revisions,
        "proof_attempts": state.proof_attempts,
        "decompositions": state.decompositions,
        "difficulty": difficulty,
        "related_work": related_work or None,
        "passed": passed,
        "run_id": run_id,
        "run_dir": str(store.root),
        "formalization": formalization,
    }
