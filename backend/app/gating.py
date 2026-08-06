from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

from .config import settings


LEVEL_LABELS = {
    "retrieval_only": "仅资料检索，未生成证明",
    "V0": "V0 · 仅模型生成，未验证",
    "V1": "V1 · 自然语言推导通过前提与一致性检查",
    "V2": "V2 · SageMath 精确计算已复核",
    "V3": "V3 · 批判检查通过的高可信自然语言证明",
    "V4": "V4 · Lean 形式命题已通过 kernel 检查",
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
            # Prefer the code echoed by the tool call payload if present.
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
        notes.append("回答含全称断言，但未见显式条件说明，已降级审慎处理。")
    if re.search(r"\b\d{2,}\b", message) and not re.search(r"\b\d+\b", answer):
        notes.append("问题含具体数值，回答未回显关键数值，请人工核对。")
    return notes


async def _structured_audit(
    message: str,
    answer: str,
    tool_results: list[dict[str, Any]],
    lean_code: str | None,
) -> dict[str, Any]:
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )
    payload = {
        "user_question": message,
        "assistant_answer": answer[:6000],
        "tool_results": tool_results[:8],
        "lean_code": lean_code,
    }
    response = await client.responses.create(
        model=settings.openai_model,
        instructions=(
            "你是数论回答的正确性门控审计器。只输出 JSON，不要 Markdown。"
            "检查：1) 前提、变量域、适用条件是否完整；2) 回答是否与工具结果冲突；"
            "3) 若提供了 Lean 代码，判断其 formal statement 是否准确表达用户原问题。"
            "JSON 字段："
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
        notes.append("检测到回答与验证工具结果冲突，已阻止宣称已验证结论。")
        return "V0", notes, blocked

    if lean_ok:
        if lean_aligned is True:
            notes.append("Lean kernel 通过，且形式命题与用户问题对齐。")
            return "V4", notes, blocked
        if lean_aligned is False:
            notes.append("Lean 编译通过，但形式命题可能未准确表达原问题，不能记为 V4。")
            if premise_ok:
                notes.append("已降级为通过前提检查的自然语言结论。")
                return "V1", notes, blocked
            notes.append("题意未对齐且前提检查未通过。")
            return "V0", notes, blocked
        notes.append("Lean 编译通过，但未能完成题意对齐检查，不能记为 V4。")
        if sage_ok:
            notes.append("同时存在 Sage 验算结果，按计算验证计。")
            return "V2", notes, blocked
        if premise_ok:
            return "V1", notes, blocked
        return "V0", notes, blocked

    if critic_ok and premise_ok and not sage_ok:
        notes.append("前提审计与批判检查均通过；仍非形式证明。")
        return "V3", notes, blocked

    if sage_ok:
        notes.append("具体计算已由 SageMath 精确复核；一般性证明未因此自动成立。")
        if premise_ok:
            return "V2", notes, blocked
        notes.append("计算通过，但自然语言前提检查未完全通过。")
        return "V2", notes, blocked

    if premise_ok:
        notes.append("自然语言推导通过前提与一致性检查；尚未形式化。")
        return "V1", notes, blocked

    notes.append("仅模型生成，关键结论应视为未验证草稿。")
    return "V0", notes, blocked


async def gate_answer(
    message: str,
    answer: str,
    tool_results: list[dict[str, Any]],
    *,
    lean_code: str | None = None,
) -> GateResult:
    if not settings.openai_api_key:
        return GateResult(
            level="retrieval_only",
            label=LEVEL_LABELS["retrieval_only"],
            notes=["未配置模型密钥，仅返回资料检索结果。"],
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
        critic_ok = premise_ok and not conflict and bool(audit.get("notes") is not None)
        # Treat a clean premise audit without conflict as critic pass for V3 when no tools.
        if premise_ok and not conflict and not sage_ok and not lean_ok:
            critic_ok = True
        for note in audit.get("notes") or []:
            if isinstance(note, str) and note.strip():
                notes.append(note.strip())
        summary = audit.get("summary")
        if isinstance(summary, str) and summary.strip():
            notes.append(summary.strip())
    except Exception as exc:  # noqa: BLE001 - gating must degrade safely
        notes.append(f"自动审计失败，已降级为启发式检查：{exc}")
        heuristic = _heuristic_premise_flags(message, answer)
        notes.extend(heuristic)
        premise_ok = not heuristic
        critic_ok = False
        if lean_ok:
            lean_aligned = None

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
            "【正确性门控】回答与验证工具冲突，以下内容不应视为已验证结论。\n\n"
        )
    elif level == "V0":
        prefix = "【正确性门控】当前等级 V0：未验证草稿。\n\n"

    # Deduplicate notes while preserving order.
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
