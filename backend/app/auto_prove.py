"""Bounded QED-inspired proof workflow backed by the existing Responses API.

Unlike the upstream QED application this module neither shells out to Codex nor
lets an agent write arbitrary files.  It keeps the useful roles (plan, prove,
structural review, detailed review, revision) inside the API service.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from openai import AsyncOpenAI

from .config import settings
from .formalize import propose_statement, verify_statement
from .retrieval import search


EventEmitter = Callable[[str, dict[str, Any]], Awaitable[None]]

PLANNER_PROMPT = """You are a rigorous mathematician planning a proof. Analyze the
problem, state any necessary interpretation or missing hypothesis, then give a compact
lemma-by-lemma plan. Do not claim a result is established merely because it is plausible.
Use the supplied library excerpts only when relevant. Output Markdown."""

PROVER_PROMPT = """You are a rigorous number-theory proof writer. Produce a complete,
self-contained natural-language proof for the problem using the plan. Define notation,
justify every nontrivial step, and clearly identify any standard theorem invoked. Do not
invent citations or silently strengthen hypotheses. Output only the proof in Markdown."""

STRUCTURAL_REVIEW_PROMPT = """You are a hostile mathematical referee performing a structural
review. Check that the proof proves exactly the stated problem, has the necessary cases,
and has a valid overall dependency chain. Return JSON only with exactly these fields:
{"pass": boolean, "issues": [string], "revision_instructions": string}.
Mark pass false for a logical gap, a changed claim, an unjustified theorem application, or
a missing case. Be concise and specific."""

DETAILED_REVIEW_PROMPT = """You are a hostile mathematical referee performing a line-by-line
review. Check computations, quantifiers, inequality directions, hidden assumptions, and
applications of named results in the proposed proof. Return JSON only with exactly these
fields: {"pass": boolean, "issues": [string], "revision_instructions": string}.
Mark pass false whenever a reader could not justify a nontrivial inference."""

REVISION_PROMPT = """You are a rigorous proof editor. Rewrite the proof to address every
referee issue while proving exactly the original problem. If the claim cannot be proved
from the stated hypotheses, say so clearly rather than fabricating a proof. Output only
the revised proof in Markdown."""


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)


async def _ask(instructions: str, payload: dict[str, Any]) -> str:
    response = await _client().responses.create(
        model=settings.openai_model,
        instructions=instructions,
        input=json.dumps(payload, ensure_ascii=False),
    )
    text = (response.output_text or "").strip()
    if not text:
        raise RuntimeError("The model returned an empty response.")
    return text


def _parse_review(text: str) -> dict[str, Any]:
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    try:
        data = json.loads(clean)
        issues = [str(x).strip() for x in data.get("issues", []) if str(x).strip()]
        return {
            "pass": bool(data.get("pass")),
            "issues": issues,
            "revision_instructions": str(data.get("revision_instructions", "")).strip(),
        }
    except (json.JSONDecodeError, TypeError):
        return {
            "pass": False,
            "issues": ["The automated referee returned an unreadable report."],
            "revision_instructions": text[:2000],
        }


async def run_auto_prove(
    problem: str,
    guidance: str,
    depth: str,
    formalize: bool,
    emit: EventEmitter | None = None,
) -> dict[str, Any]:
    """Run a small, predictable proof-search loop and return its artifacts."""
    if not settings.openai_api_key:
        return {"ok": False, "error": "OPENAI_API_KEY is not configured."}

    async def status(phase: str, **details: Any) -> None:
        if emit:
            await emit(phase, details)

    try:
        await status("retrieving", label="Retrieving relevant textbook material")
        try:
            hits = await asyncio.to_thread(search, problem, 4)
        except Exception:  # Retrieval is context, not a prerequisite for proof search.
            hits = []
        excerpts = [
            {"heading": hit.get("heading"), "content": str(hit.get("content", ""))[:1200]}
            for hit in hits[:4]
        ]
        await status("planning", label="Building a lemma-by-lemma proof plan")
        plan = await _ask(PLANNER_PROMPT, {"problem": problem, "guidance": guidance, "excerpts": excerpts})

        await status("proving", label="Writing the first proof")
        proof = await _ask(PROVER_PROMPT, {"problem": problem, "guidance": guidance, "plan": plan})
        max_revisions = 0 if depth == "quick" else 2
        review_issues: list[str] = []
        revisions = 0

        for round_no in range(max_revisions + 1):
            await status("reviewing", label=f"Structural review {round_no + 1} of {max_revisions + 1}")
            structural = _parse_review(await _ask(
                STRUCTURAL_REVIEW_PROMPT, {"problem": problem, "plan": plan, "proof": proof}
            ))
            detailed = {"pass": True, "issues": [], "revision_instructions": ""}
            if structural["pass"]:
                await status("reviewing", label=f"Detailed review {round_no + 1} of {max_revisions + 1}")
                detailed = _parse_review(await _ask(
                    DETAILED_REVIEW_PROMPT, {"problem": problem, "plan": plan, "proof": proof}
                ))
            review_issues = structural["issues"] + detailed["issues"]
            if structural["pass"] and detailed["pass"]:
                break
            if round_no == max_revisions:
                break
            revisions += 1
            await status("revising", label=f"Revising proof ({revisions}/{max_revisions})")
            proof = await _ask(
                REVISION_PROMPT,
                {"problem": problem, "plan": plan, "proof": proof, "issues": review_issues,
                 "instructions": "\n".join(filter(None, [
                     structural["revision_instructions"], detailed["revision_instructions"],
                 ]))},
            )

        formalization: dict[str, Any] | None = None
        if formalize:
            await status("formalizing", label="Attempting Lean formalization")
            statement_result = await propose_statement(problem, proof)
            if statement_result.get("ok"):
                formalization = await verify_statement(
                    problem,
                    str(statement_result.get("statement") or ""),
                    method=proof,
                )
            else:
                formalization = statement_result

        await status("complete", label="Proof workflow complete")
        return {
            "ok": True, "proof": proof, "plan": plan, "review": review_issues,
            "revisions": revisions, "formalization": formalization,
        }
    except Exception as exc:  # noqa: BLE001 - API failures must become a client result
        return {"ok": False, "error": f"Auto Prove failed: {exc}"}
