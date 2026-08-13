from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

from .config import settings


LEVEL_LABELS = {
    "retrieval_only": "No model · API key not configured",
    "V0": "V0 · model-generated, unverified",
    "V1": "V1 · natural-language reasoning passed premise checks",
    "V2": "V2 · SageMath exact computation verified",
    "V3": "V3 · high-confidence natural-language proof after critique",
    "V4": "V4 · Lean formal statement passed the kernel",
}


@dataclass
class GateResult:
    level: str
    label: str
    notes: list[str] = field(default_factory=list)
    lean_aligned: bool | None = None
    premise_ok: bool = False
    blocked: bool = False
    answer_prefix: str = ""


def _tool_successes(tool_results: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {"sage_calculate": [], "lean_verify": []}
    for item in tool_results:
        if item.get("ok") and item.get("tool") in grouped:
            grouped[item["tool"]].append(item)
    return grouped


def _extract_lean_code(tool_results: list[dict[str, Any]]) -> str | None:
    for item in tool_results:
        if item.get("tool") == "lean_verify" and item.get("ok"):
            code = item.get("code")
            if isinstance(code, str) and code.strip():
                return code
    return None


def _heuristic_premise_flags(message: str, answer: str) -> list[str]:
    notes: list[str] = []
    lowered = answer.lower()
    absolute = bool(
        re.search(r"\b(always|never|for all)\b", answer, re.IGNORECASE)
        or re.search(r"(任意|所有|必然|一定)", answer)
    )
    conditioned = ("假设" in answer) or ("条件" in answer) or ("assume" in lowered)
    if absolute and not conditioned:
        notes.append(
            "Answer contains a universal claim without explicit conditions; treated cautiously."
        )
    if re.search(r"\b\d{2,}\b", message) and not re.search(r"\b\d+\b", answer):
        notes.append(
            "Question includes concrete numbers that were not echoed in the answer; please verify."
        )
    return notes


async def _structured_audit(
    message: str,
    answer: str,
    tool_results: list[dict[str, Any]],
    lean_code: str | None,
) -> dict[str, Any]:
    client = AsyncOpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
    )
    payload = {
        "user_question": message,
        "assistant_answer": answer[:6000],
        "tool_results": tool_results[:8],
        "lean_code": lean_code,
    }
    response = await client.responses.create(
        model=settings.deepseek_model,
        instructions=(
            "You are a correctness gate for mathematical and physics answers. Output JSON only, no Markdown. "
            "Check: 1) premises, domains, units, physical assumptions, and applicability conditions; "
            "2) conflicts with tool results; "
            "3) if Lean code is provided, whether its formal statement matches the user's question. "
            "Write notes and summary in English. "
            "JSON fields: "
            '{"premise_ok":bool,"conflict":bool,"lean_aligned":bool|null,'
            '"notes":[string],"summary":string}'
        ),
        input=json.dumps(payload, ensure_ascii=False),
    )
    text = (response.output_text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("audit payload is not an object")
    return data


async def _independent_critique(message: str, answer: str) -> tuple[bool, list[str]]:
    """Second, independent verification route required for V3.

    A separate model call re-derives the problem from scratch and judges whether
    it reaches the same conclusion as the candidate answer.
    """
    client = AsyncOpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
    )
    response = await client.responses.create(
        model=settings.deepseek_model,
        instructions=(
            "You are an independent verifier for mathematical and physics answers. "
            "First solve the user's question yourself from scratch, without assuming the "
            "candidate answer is right. Then compare conclusions and check the candidate for "
            "missing hypotheses, wrong quantifiers, unit or dimensional mistakes, invalid physical "
            "assumptions, division-by-zero cases, and counterexamples. "
            "Output JSON only: "
            '{"verdict":"agree"|"disagree"|"unsure","issues":[string]}'
        ),
        input=json.dumps(
            {"user_question": message, "candidate_answer": answer[:6000]},
            ensure_ascii=False,
        ),
    )
    text = (response.output_text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("critique payload is not an object")
    verdict = str(data.get("verdict", "unsure")).lower()
    issues = [
        item.strip()
        for item in data.get("issues") or []
        if isinstance(item, str) and item.strip()
    ]
    return verdict == "agree", issues


def _assign_level(
    *,
    premise_ok: bool,
    conflict: bool,
    sage_ok: bool,
    lean_ok: bool,
    lean_aligned: bool | None,
    critic_ok: bool,
) -> tuple[str, list[str], bool]:
    notes: list[str] = []
    blocked = False

    if conflict:
        blocked = True
        notes.append(
            "Answer conflicts with verifier tool results; blocked from claiming verified conclusions."
        )
        return "V0", notes, blocked

    if lean_ok:
        if lean_aligned is True:
            notes.append("Lean kernel passed and the formal statement matches the question.")
            return "V4", notes, blocked
        if lean_aligned is False:
            notes.append(
                "Lean compiled, but the formal statement may not match the original question; not V4."
            )
            if premise_ok:
                notes.append(
                    "Downgraded to a natural-language conclusion that passed premise checks."
                )
                return "V1", notes, blocked
            notes.append("Statement mismatch and premise checks failed.")
            return "V0", notes, blocked
        notes.append("Lean compiled, but statement alignment could not be checked; not V4.")
        if sage_ok:
            notes.append("Sage computation also succeeded; counted as computation-verified.")
            return "V2", notes, blocked
        if premise_ok:
            return "V1", notes, blocked
        return "V0", notes, blocked

    if critic_ok and premise_ok:
        notes.append(
            "An independent second derivation reached the same conclusion; "
            "high-confidence natural-language proof, still not formal."
        )
        if sage_ok:
            notes.append("Concrete instances were also verified exactly by SageMath.")
        return "V3", notes, blocked

    if sage_ok:
        notes.append(
            "Concrete computation verified exactly by SageMath; "
            "a general proof does not follow automatically."
        )
        if premise_ok:
            return "V2", notes, blocked
        notes.append("Computation passed, but natural-language premise checks did not fully pass.")
        return "V2", notes, blocked

    if premise_ok:
        notes.append(
            "Natural-language reasoning passed premise and consistency checks; not yet formalized."
        )
        return "V1", notes, blocked

    notes.append("Model-generated only; treat related claims as an unverified draft.")
    return "V0", notes, blocked


async def gate_answer(
    message: str,
    answer: str,
    tool_results: list[dict[str, Any]],
    *,
    lean_code: str | None = None,
) -> GateResult:
    if not settings.deepseek_api_key:
        return GateResult(
            level="retrieval_only",
            label=LEVEL_LABELS["retrieval_only"],
            notes=["No model API key configured."],
        )

    successes = _tool_successes(tool_results)
    sage_ok = bool(successes["sage_calculate"])
    lean_ok = bool(successes["lean_verify"])
    code = lean_code or _extract_lean_code(tool_results)

    premise_ok = False
    conflict = False
    lean_aligned: bool | None = None if not lean_ok else None
    critic_ok = False
    notes: list[str] = []

    try:
        audit = await _structured_audit(message, answer, tool_results, code if lean_ok else None)
        premise_ok = bool(audit.get("premise_ok"))
        conflict = bool(audit.get("conflict"))
        if lean_ok:
            aligned = audit.get("lean_aligned")
            lean_aligned = None if aligned is None else bool(aligned)
        for note in audit.get("notes") or []:
            if isinstance(note, str) and note.strip():
                notes.append(note.strip())
        summary = audit.get("summary")
        if isinstance(summary, str) and summary.strip():
            notes.append(summary.strip())
    except Exception as exc:  # noqa: BLE001 - gating must degrade safely
        notes.append(f"Automatic audit failed; fell back to heuristics: {exc}")
        heuristic = _heuristic_premise_flags(message, answer)
        notes.extend(heuristic)
        premise_ok = not heuristic
        critic_ok = False
        if lean_ok:
            lean_aligned = None

    # V3 requires a second, independent derivation. Only attempt it when the
    # answer is a V3 candidate (premises hold, no conflict, no aligned Lean proof).
    if premise_ok and not conflict and not lean_ok:
        try:
            critic_ok, critique_issues = await _independent_critique(message, answer)
            if critic_ok:
                notes.append("Independent verification route agreed with the answer.")
            else:
                notes.append(
                    "Independent verification route did not fully agree; capped below V3."
                )
            notes.extend(critique_issues[:4])
        except Exception as exc:  # noqa: BLE001 - critique must degrade safely
            critic_ok = False
            notes.append(f"Independent critique unavailable; capped below V3: {exc}")

    level, level_notes, blocked = _assign_level(
        premise_ok=premise_ok,
        conflict=conflict,
        sage_ok=sage_ok,
        lean_ok=lean_ok,
        lean_aligned=lean_aligned,
        critic_ok=critic_ok,
    )
    notes.extend(level_notes)

    prefix = ""
    if blocked:
        prefix = (
            "[Correctness gate] Answer conflicts with verifier tools; "
            "do not treat the content below as verified.\n\n"
        )
    elif level == "V0":
        prefix = "[Correctness gate] Level V0: unverified draft.\n\n"

    unique_notes = list(dict.fromkeys(notes))
    return GateResult(
        level=level,
        label=LEVEL_LABELS[level],
        notes=unique_notes,
        lean_aligned=lean_aligned,
        premise_ok=premise_ok,
        blocked=blocked,
        answer_prefix=prefix,
    )
