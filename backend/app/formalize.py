"""Lean workbench backend: NL → statement → proof draft → kernel check.

Deliberately split so the user confirms the *statement* before (or while)
editing a proof. Chat-mode lean_verify is no longer the primary path; V4
evidence should come from this workbench.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
from openai import AsyncOpenAI

from .config import settings
from .verification import call_lean


STATEMENT_PROMPT = (
    "You translate a natural-language mathematical proposition into a Lean 4 + mathlib "
    "theorem statement. Output JSON only, no Markdown fences: "
    '{"statement":"theorem <name> : <proposition>","explanation":string,"caveats":[string]}. '
    "Rules: the statement field contains ONLY the theorem signature (no := by, no proof); "
    "use mathlib names and conventions; quantify all variables explicitly; "
    "explanation describes in English how each part of the statement matches the question; "
    "caveats lists any simplification or interpretation choice made during translation. "
    "If a proof sketch is provided, use it only to choose natural lemmas/names — "
    "do not embed the proof into the statement."
)

PROOF_PROMPT = (
    "You are a Lean 4 + mathlib proof engineer. Given a theorem statement and an optional "
    "natural-language proof sketch, produce a complete, compiling Lean 4 file. "
    "Output ONLY Lean code, no Markdown fences. "
    "Requirements: import only what is needed from Mathlib (prefer narrow imports such as "
    "'import Mathlib.Tactic' over 'import Mathlib', which is slow to compile); "
    "keep the theorem statement EXACTLY as given (you may wrap it with imports); "
    "follow the sketch when it is sound; never use sorry, admit, axiom, or unsafe."
)

ALIGNMENT_PROMPT = (
    "You check whether a Lean 4 theorem statement faithfully formalizes a user's "
    "natural-language question. Output JSON only: "
    '{"aligned":bool,"notes":[string]}. '
    "Check quantifiers, domains, hypotheses, and the conclusion; note any mismatch."
)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json|lean)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL)
    return text.strip()


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)


def _pack_input(question: str, method: str = "") -> str:
    method = method.strip()
    if not method:
        return question
    return json.dumps(
        {"proposition": question, "proof_sketch": method},
        ensure_ascii=False,
    )


def extract_theorem_statement(code: str) -> str | None:
    """Best-effort extraction of a `theorem ... : ...` signature from Lean code."""
    match = re.search(
        r"(theorem\s+\w+[\s\S]*?)(?::=\s*by\b|:=\s*by\b|:=\s*)",
        code,
        flags=re.IGNORECASE,
    )
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip().rstrip(":")
    match = re.search(r"(theorem\s+\w+\s*:[^\n]+)", code, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


async def propose_statement(question: str, method: str = "") -> dict[str, Any]:
    if not settings.openai_api_key:
        return {"ok": False, "error": "OPENAI_API_KEY is not configured."}
    try:
        response = await _client().responses.create(
            model=settings.openai_model,
            instructions=STATEMENT_PROMPT,
            input=_pack_input(question, method),
        )
        data = json.loads(_strip_fences(response.output_text or ""))
        statement = str(data.get("statement", "")).strip()
        if not statement.startswith("theorem"):
            raise ValueError("model did not return a theorem statement")
        display_code = (
            "import Mathlib.Tactic\n\n"
            f"{statement} := by\n"
            "  sorry -- confirm the statement, then generate or write a proof"
        )
        return {
            "ok": True,
            "statement": statement,
            "display_code": display_code,
            "explanation": str(data.get("explanation", "")).strip(),
            "caveats": [
                item.strip()
                for item in data.get("caveats") or []
                if isinstance(item, str) and item.strip()
            ],
        }
    except Exception as exc:  # noqa: BLE001 - report failure honestly
        return {"ok": False, "error": f"Statement generation failed: {exc}"}


async def generate_proof_draft(
    statement: str,
    *,
    question: str = "",
    method: str = "",
) -> dict[str, Any]:
    """Generate Lean proof code without compiling (user goes into the editor)."""
    if not settings.openai_api_key:
        return {"ok": False, "error": "OPENAI_API_KEY is not configured."}
    payload = {
        "statement": statement,
        "proposition": question,
        "proof_sketch": method,
    }
    try:
        response = await _client().responses.create(
            model=settings.openai_model,
            instructions=PROOF_PROMPT,
            input=json.dumps(payload, ensure_ascii=False),
        )
        code = _strip_fences(response.output_text or "")
        if not code or "theorem" not in code.lower():
            raise ValueError("model did not return Lean theorem code")
        if re.search(r"\b(sorry|admit)\b", code, re.IGNORECASE):
            return {
                "ok": False,
                "error": "Generated draft still contains sorry/admit; refused.",
                "code": code,
            }
        return {"ok": True, "code": code}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Proof draft generation failed: {exc}"}


async def _check_alignment(question: str, statement: str) -> tuple[bool | None, list[str]]:
    try:
        response = await _client().responses.create(
            model=settings.openai_model,
            instructions=ALIGNMENT_PROMPT,
            input=json.dumps(
                {"user_question": question, "lean_statement": statement},
                ensure_ascii=False,
            ),
        )
        data = json.loads(_strip_fences(response.output_text or ""))
        aligned = data.get("aligned")
        notes = [
            item.strip()
            for item in data.get("notes") or []
            if isinstance(item, str) and item.strip()
        ]
        return (None if aligned is None else bool(aligned)), notes
    except Exception as exc:  # noqa: BLE001
        return None, [f"Alignment check unavailable: {exc}"]


async def verify_statement(
    question: str,
    statement: str,
    code: str | None = None,
    *,
    method: str = "",
) -> dict[str, Any]:
    """Compile a proof and audit NL ↔ Lean alignment. V4 requires both."""
    if not settings.openai_api_key and not code:
        return {"ok": False, "error": "OPENAI_API_KEY is not configured and no proof was supplied."}

    notes: list[str] = []
    proof_code = (code or "").strip()
    if not proof_code:
        draft = await generate_proof_draft(statement, question=question, method=method)
        if not draft.get("ok"):
            return {"ok": False, "error": draft.get("error"), "code": draft.get("code")}
        proof_code = str(draft["code"])

    # Prefer an explicit statement; fall back to extracting from code.
    formal_statement = statement.strip() or extract_theorem_statement(proof_code) or ""
    if not formal_statement:
        return {
            "ok": False,
            "error": "No theorem statement available to check against the question.",
            "code": proof_code,
        }

    try:
        lean_result = await call_lean({"code": proof_code})
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "error": f"Lean service call failed: {exc}", "code": proof_code}

    verified = bool(lean_result.get("ok")) and bool(lean_result.get("verified"))
    aligned: bool | None = None
    if verified:
        aligned, alignment_notes = await _check_alignment(question, formal_statement)
        notes.extend(alignment_notes)

    if verified and aligned is True:
        level = "V4"
        notes.append("Lean kernel passed and the formal statement matches the question.")
    elif verified and aligned is False:
        level = "V1"
        notes.append(
            "Lean compiled, but the formal statement may not match the original question; not V4."
        )
    elif verified:
        level = "V1"
        notes.append("Lean compiled, but statement alignment could not be confirmed; not V4.")
    else:
        level = "V0"
        notes.append("Lean compilation failed; the proposition remains unformalized.")

    return {
        "ok": True,
        "verified": verified,
        "aligned": aligned,
        "level": level,
        "statement": formal_statement,
        "code": proof_code,
        "output": str(lean_result.get("output") or lean_result.get("error") or "")[-4000:],
        "notes": notes,
    }
