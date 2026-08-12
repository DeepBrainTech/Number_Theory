"""QED-inspired proof workflow on the Responses API.

Roles follow proofQED/QED (survey → decompose → prove → structural → detailed →
regulator) but stay inside this service: no Codex CLI, no arbitrary filesystem
writes by the model. Sage and literature tools are the same function tools as
chat. Artifacts are persisted by the server under AUTO_PROVE_RUNS_DIR.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from openai import AsyncOpenAI

from .chat import BASE_TOOLS, RESEARCH_TOOLS, WEB_SEARCH_TOOL, execute_tool
from .config import settings
from .formalize import propose_statement, verify_statement
from .prove_prompts import qed_prompt, skill_text


EventEmitter = Callable[[str, dict[str, Any]], Awaitable[None]]
Depth = Literal["quick", "deep"]
RegulatorDecision = Literal["REVISE_PROOF", "REVISE_PLAN", "REWRITE", "FINAL"]

# QED's default three-level retry hierarchy.  ``depth`` remains in the API for
# backwards compatibility, but no longer changes the QED workflow.
DEPTH_BUDGETS: dict[str, dict[str, int]] = {
    "quick": {"max_proof_attempts": 4, "max_revisions": 4, "max_decompositions": 4},
    "deep": {"max_proof_attempts": 4, "max_revisions": 4, "max_decompositions": 4},
}

_JSON_BLOCK = re.compile(r"\{[^{}]*\"pass\"[^{}]*\}", re.DOTALL)
_YAML_FENCE = re.compile(r"```(?:yaml|yml)\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
_HEADING = re.compile(r"^## Classification:\s*(Easy|Medium|Hard)\s*$", re.IGNORECASE | re.MULTILINE)
_CURRENT_RUN: contextvars.ContextVar[RunStore | None] = contextvars.ContextVar("auto_prove_run", default=None)


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)


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

    def write(self, relative: str, content: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")
        return path

    def read(self, relative: str) -> str:
        path = self.root / relative
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

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
            "model": settings.openai_model,
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

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
        for path in sorted(self.root.rglob("*")):
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


def run_artifacts(run_id: str) -> dict[str, Any] | None:
    store = open_run_store(run_id)
    if not store:
        return None
    files = sorted(
        str(path.relative_to(store.root)).replace("\\", "/")
        for path in store.root.rglob("*")
        if path.is_file()
    )
    result = store.read("result.json")
    return {"run_id": run_id, "status": store.read("STATUS.md"), "checkpoint": store.read("checkpoint.json"), "result": json.loads(result) if result else None, "files": files}


def add_human_guidance(run_id: str, guidance: str) -> bool:
    store = open_run_store(run_id)
    if not store:
        return False
    store.append_human_guidance(guidance)
    store.log("Human guidance added")
    return True


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
    return text.strip().upper() == "DONE"


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


def _with_skill(prompt_name: str) -> str:
    names = {
        "literature_survey.md": "literature_survey.md",
        "decomposition.md": "decomposition.md",
        "prover.md": "single_prover.md",
    }
    return skill_text() + "\n\n---\n\n" + qed_prompt(
        "decomposition-prover/" + names[prompt_name]
        if prompt_name in {"decomposition.md", "prover.md"}
        else names[prompt_name]
    )


async def _ask(
    instructions: str,
    payload: dict[str, Any],
    *,
    tools: list[dict[str, Any]] | None,
    max_rounds: int,
    emit: EventEmitter | None = None,
) -> str:
    run = _CURRENT_RUN.get()
    if run and run.human_guidance():
        payload = {**payload, "human_guidance": run.human_guidance()}
    if run:
        payload = {**payload, "prior_run_artifacts": run.artifact_context()}
    started = datetime.now(timezone.utc)
    client = _client()
    input_items: list[dict[str, Any]] = [
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}
    ]
    kwargs: dict[str, Any] = {
        "model": settings.openai_model,
        "instructions": instructions,
        "input": input_items,
    }
    if tools:
        kwargs["tools"] = tools
    response = await client.responses.create(**kwargs)
    for _ in range(max_rounds):
        calls = [item for item in (response.output or []) if getattr(item, "type", None) == "function_call"]
        if not calls:
            break
        outputs: list[dict[str, Any]] = []
        for call in calls:
            try:
                arguments = json.loads(call.arguments)
            except json.JSONDecodeError:
                arguments = {}
            if emit:
                await emit("tool", {"label": f"Tool: {call.name}", "tool": call.name})
            result = await execute_tool(call.name, arguments)
            outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(result, ensure_ascii=False),
                }
            )
        follow: dict[str, Any] = {
            "model": settings.openai_model,
            "instructions": instructions,
            "input": outputs,
            "previous_response_id": response.id,
        }
        if tools:
            follow["tools"] = tools
        response = await client.responses.create(**follow)
    text = (response.output_text or "").strip()
    if not text:
        raise RuntimeError("The model returned an empty response.")
    if run:
        role = str(payload.get("mode") or payload.get("verification_phase") or "agent")
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
) -> dict[str, Any]:
    """Run the QED-style proof loop and return artifacts plus a run directory."""
    if not settings.openai_api_key:
        return {"ok": False, "error": "OPENAI_API_KEY is not configured."}

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
    run_token = _CURRENT_RUN.set(store)
    all_tools = [WEB_SEARCH_TOOL, *BASE_TOOLS, *RESEARCH_TOOLS]
    sage_tools = list(BASE_TOOLS)

    async def status(phase: str, **details: Any) -> None:
        store.checkpoint(phase, state)
        if emit:
            await emit(phase, {"run_id": run_id, **details})
        store.log(details.get("label") or phase)

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
            difficulty = parse_difficulty(survey_text)
            related_work = store.read("related_info/related_work.md")
            state.related_work = related_work
            easy_proof = ""
        else:
            store.write("problem.md", problem)
            if guidance.strip():
                store.write("guidance.md", guidance)
            store.write("config.json", json.dumps({"depth": depth, "formalize": formalize, **limits}, indent=2))
            await status("surveying", label="Literature survey and difficulty check")
            write_status("surveying")
            survey_text = await _ask(_with_skill("literature_survey.md"), {"problem": problem, "guidance": guidance}, tools=all_tools, max_rounds=6, emit=emit)
            difficulty = parse_difficulty(survey_text)
            related_work = extract_section(survey_text, "Related Work")
            easy_proof = extract_section(survey_text, "Easy Proof")
            evaluation = extract_section(survey_text, "Difficulty Evaluation") or survey_text
            store.write("related_info/difficulty_evaluation.md", evaluation or survey_text)
            store.write("related_info/related_work.md", related_work or "(none)")
            store.write("related_info/survey_raw.md", survey_text)
            state.related_work = related_work
            store.log(f"Difficulty classified as {difficulty}")

        if difficulty == "easy" and easy_proof.strip():
            await status("proving", label="Easy path: survey agent wrote the proof")
            state.proof_text = easy_proof.strip()
            state.plan = "Easy short-circuit: no decomposition (QED Stage 0)."
            state.proof_attempts = 1
            store.write("proof.md", state.proof_text)
            store.write("plan.yaml", state.plan)
            return await _finalize(
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

        next_action = "prove" if resuming and state.plan else "decompose"
        passed = False

        while state.attempt <= limits["max_decompositions"]:
            if next_action in {"decompose", "decompose_revise"}:
                mode = "CREATE" if next_action == "decompose" and state.attempt == 1 and state.revision == 1 else (
                    "REVISE" if next_action == "decompose_revise" else "REWRITE"
                )
                await status(
                    "planning",
                    label=f"Decomposition {mode} (attempt {state.attempt}, revision {state.revision})",
                )
                write_status("planning")
                plan_text = await _ask(
                    _with_skill("decomposition.md"),
                    {
                        "mode": mode,
                        "problem": problem,
                        "guidance": guidance,
                        "related_work": state.related_work,
                        "current_plan": state.plan,
                        "previous_proof": state.previous_proof,
                        "verification_feedback": state.verification_feedback,
                        "regulator_guidance": state.regulator_guidance,
                        "plan_history": state.plan_history,
                        "attempt": state.attempt,
                        "revision": state.revision,
                    },
                    tools=all_tools,
                    max_rounds=4,
                    emit=emit,
                )
                state.plan = extract_yaml(plan_text)
                state.decompositions += 1
                store.write(
                    f"attempt_{state.attempt}/revision_{state.revision}/decomposition.yaml",
                    state.plan,
                )
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
                proof_text = await _ask(
                    _with_skill("prover.md"),
                    {
                        "problem": problem,
                        "guidance": guidance,
                        "plan": state.plan,
                        "related_work": state.related_work,
                        "previous_proof": state.previous_proof,
                        "verification_feedback": state.verification_feedback,
                        "regulator_guidance": state.regulator_guidance,
                    },
                    tools=all_tools,
                    max_rounds=6,
                    emit=emit,
                )
                state.proof_text = proof_text
                state.proof_attempts += 1
                store.write(f"{proof_rel}/proof.md", proof_text)
                store.write("proof.md", proof_text)

                await status(
                    "reviewing",
                    label=f"Structural review {state.proof} (attempt {state.attempt})",
                )
                write_status("reviewing")
                structural = _parse_review(
                    await _ask(
                        qed_prompt("decomposition-prover/proof_verify_structural.md"),
                        {"problem": problem, "plan": state.plan, "proof": state.proof_text},
                        tools=sage_tools,
                        max_rounds=3,
                        emit=emit,
                    )
                )
                store.write(f"{proof_rel}/structural_verification.md", structural["report"])
                structural_verdict_text = await _ask(
                    qed_prompt("decomposition-prover/verdict_proof.md"),
                    {
                        "mode": "STRUCTURAL",
                        "structural_verification": structural["report"],
                        "structural_verification_file": "structural_verification (JSON field)",
                    },
                    tools=None,
                    max_rounds=0,
                    emit=emit,
                )
                store.write(f"{proof_rel}/structural_verdict.md", structural_verdict_text)
                structural_passed = parse_verdict(structural_verdict_text)
                detailed = {
                    "pass": True,
                    "issues": [],
                    "revision_instructions": "",
                    "report": "Skipped: structural review failed.",
                }
                phase: Literal["structural", "detailed"] = "structural"
                if structural_passed:
                    await status(
                        "reviewing",
                        label=f"Detailed review {state.proof} (attempt {state.attempt})",
                    )
                    detailed = _parse_review(
                        await _ask(
                            qed_prompt("decomposition-prover/proof_verify_detailed.md"),
                            {
                                "problem": problem,
                                "plan": state.plan,
                                "proof": state.proof_text,
                                "structural_review": structural["report"],
                            },
                            tools=sage_tools,
                            max_rounds=4,
                            emit=emit,
                        )
                    )
                    store.write(f"{proof_rel}/detailed_verification.md", detailed["report"])
                    phase = "detailed"

                final_verdict_text = "CONTINUE"
                if structural_passed:
                    final_verdict_text = await _ask(
                        qed_prompt("decomposition-prover/verdict_proof.md"),
                        {
                            "mode": "FINAL",
                            "structural_verification": structural["report"],
                            "detailed_verification": detailed["report"],
                            "structural_verification_file": "structural_verification (JSON field)",
                            "detailed_verification_file": "detailed_verification (JSON field)",
                        },
                        tools=None,
                        max_rounds=0,
                        emit=emit,
                    )
                store.write(f"{proof_rel}/final_verdict.md", final_verdict_text)

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
                regulator_text = await _ask(
                    qed_prompt("decomposition-prover/regulator.md"),
                    {
                        "mode": "DECIDE",
                        "verification_phase": phase,
                        "problem": problem,
                        "plan": state.plan,
                        "proof": state.proof_text,
                        "verification_report": state.verification_feedback,
                        "attempt_history": (
                            f"proofs={state.proof_attempts}, plan_revisions={state.plan_revisions}, "
                            f"decompositions={state.decompositions}"
                        ),
                        "plan_history": state.plan_history,
                        "attempt": state.attempt,
                        "revision": state.revision,
                        "proof_index": state.proof,
                        **limits,
                    },
                    tools=None,
                    max_rounds=0,
                    emit=emit,
                )
                store.write(f"{proof_rel}/regulator_decision.md", regulator_text)
                decision = clamp_decision(parse_regulator_decision(regulator_text), state, limits)
                store.log(f"Regulator: {decision}")
                state.previous_proof = state.proof_text
                state.regulator_guidance = regulator_text
                if decision in {"REVISE_PLAN", "REWRITE"}:
                    entry = extract_section(regulator_text, "Plan History Entry") or regulator_text
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
            failure = await _ask(
                qed_prompt("decomposition-prover/regulator.md"),
                {
                    "mode": "FINAL",
                    "verification_phase": "final",
                    "problem": problem,
                    "plan": state.plan,
                    "proof": state.proof_text,
                    "verification_report": state.verification_feedback,
                    "attempt_history": (
                        f"proofs={state.proof_attempts}, plan_revisions={state.plan_revisions}, "
                        f"decompositions={state.decompositions}"
                    ),
                    "plan_history": state.plan_history,
                    "attempt": state.attempt,
                    "revision": state.revision,
                    "proof_index": state.proof,
                    **limits,
                },
                tools=None,
                max_rounds=0,
                emit=emit,
            )
            store.write("failure_analysis.md", failure)
            if failure.strip():
                state.review_issues = list(dict.fromkeys([*state.review_issues, "Retry limits exhausted."]))

        # QED Stage 2: preserve a readable account of the entire effort after
        # either a verified proof or exhaustive failure.  Easy problems return
        # above, matching QED's Stage-0 short circuit.
        await status("summarizing", label="QED proof-effort summary")
        write_status("summarizing")
        summary = await _ask(
            qed_prompt("proof_effort_summary.md"),
            {
                "problem": problem,
                "difficulty": difficulty,
                "passed": passed,
                "final_proof": state.proof_text,
                "related_work": state.related_work,
                "plan_history": state.plan_history,
                "verification_feedback": state.verification_feedback,
                "failure_analysis": store.read("failure_analysis.md"),
                "resource_usage": {
                    "proof_attempts": state.proof_attempts,
                    "plan_revisions": state.plan_revisions,
                    "decompositions": state.decompositions,
                    "limits": limits,
                },
                "summary_file": "proof_effort_summary.md",
                "output_dir": "the current run artifacts supplied in this JSON message",
            },
            tools=None,
            max_rounds=0,
            emit=emit,
        )
        store.write("proof_effort_summary.md", summary)

        return await _finalize(
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
    except Exception as exc:  # noqa: BLE001 - API failures must become a client result
        store.log(f"ERROR: {exc}")
        store.write("STATUS.md", f"# Auto Prove Status\n\nFailed: {exc}\n")
        return {
            "ok": False,
            "error": f"Auto Prove failed: {exc}",
            "run_id": run_id,
            "run_dir": str(store.root),
        }
    finally:
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
