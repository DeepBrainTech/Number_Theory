from __future__ import annotations

import json
from typing import Any

import httpx
from openai import AsyncOpenAI

from .config import settings
from .gating import GateResult, gate_answer
from .memory import format_memory_block
from .verification import call_lean, call_sage


SYSTEM_PROMPT = """You are a rigorous number-theory teacher and research assistant.
Ground definitions and arguments in retrieved material first, then independently check domains, theorem hypotheses, edge cases, and counterexamples.
Call SageMath for concrete integer computation; call Lean when the user asks for a formal proof or when a key claim is suitable for formalization.
A Lean success only verifies the submitted formal statement; you must still confirm that statement faithfully captures the user's question.
If tools fail or evidence is insufficient, state uncertainty clearly and never present model speculation as verified fact.
Do not mention book titles, PDF page numbers, or internal retrieval steps by default. Use clear English and LaTeX (inline $...$, display $$...$$ on their own lines). Never use \\[...\\] or \\(...\\) delimiters.
LaTeX notation rules:
- Congruences: write $x \\equiv a \\pmod{n}$, never $x \\equiv a | (\\mathrm{mod}\\, n)$ or a bare vertical bar before (mod ...).
- Products/juxtaposition: write $11k$ or $11k$, never $11|k$ unless you mean “11 divides k”.
- Use `|` or $\\mid$ only for the divides relation (e.g. $d\\mid n$), not for spacing, punctuation, or modular notation.
- Prefer $\\pmod{n}$ for congruences; use $d\\mid n$ only when stating divisibility.
If long-term user information is provided, use it naturally without reciting the whole memory list."""

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "sage_calculate",
        "description": "Exact integer computation via SageMath. Supports only gcd, xgcd, factor, is_prime, inverse_mod, crt.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["gcd", "xgcd", "factor", "is_prime", "inverse_mod", "crt"],
                },
                "arguments": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Decimal integers; for crt pass residues then moduli, using split as the boundary.",
                },
                "split": {"type": ["integer", "null"]},
            },
            "required": ["operation", "arguments", "split"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "lean_verify",
        "description": "Compile a complete Lean 4 + mathlib proof. No sorry, admit, or new axioms.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Lean 4 code starting with import Mathlib and including a theorem/example with a full proof.",
                }
            },
            "required": ["code"],
            "additionalProperties": False,
        },
    },
]


def retrieval_answer(hits: list[dict]) -> str:
    if not hits:
        return "Not enough relevant material was found in the indexed library to confirm an answer."
    excerpts = []
    for hit in hits[:3]:
        label = hit["heading"] or hit["block_type"]
        content = hit["content"]
        if len(content) > 700:
            content = content[:700].rstrip() + "…"
        excerpts.append(f"[{label}]\n{content}")
    return (
        "OPENAI_API_KEY is not configured. Here are retrieval excerpts from the indexed library:\n\n"
        + "\n\n".join(excerpts)
    )


async def _execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        if name == "sage_calculate":
            result = await call_sage(arguments)
            return {"tool": name, **arguments, **result}
        if name == "lean_verify":
            result = await call_lean(arguments)
            return {"tool": name, **arguments, **result}
        return {"tool": name, "ok": False, "error": f"Unknown tool: {name}"}
    except (httpx.HTTPError, ValueError) as exc:
        return {"tool": name, "ok": False, "error": f"Verifier call failed: {exc}"}


def _legacy_verification(level: str) -> str:
    mapping = {
        "retrieval_only": "retrieval_only",
        "V0": "model_unverified",
        "V1": "model_unverified",
        "V2": "sage_verified",
        "V3": "model_unverified",
        "V4": "lean_verified",
    }
    return mapping.get(level, "model_unverified")


def suggest_title(message: str) -> str:
    cleaned = " ".join(message.strip().split())
    if len(cleaned) <= 24:
        return cleaned or "New chat"
    return cleaned[:24].rstrip() + "…"


async def answer(
    message: str,
    hits: list[dict],
    *,
    history: list[dict[str, str]] | None = None,
    memories: list[str] | None = None,
) -> tuple[str, str, GateResult, list[dict[str, Any]]]:
    if not settings.openai_api_key:
        gate = GateResult(
            level="retrieval_only",
            label="Retrieval only · no proof generated",
            notes=["No model API key configured; returning retrieval results only."],
        )
        return retrieval_answer(hits), "retrieval", gate, []

    context = "\n\n---\n\n".join(hit["content"] for hit in hits)
    instructions = SYSTEM_PROMPT + format_memory_block(memories or [])
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )

    input_items: list[dict[str, Any]] = []
    for turn in history or []:
        role = turn.get("role")
        content = turn.get("content", "").strip()
        if role in {"user", "assistant"} and content:
            input_items.append({"role": role, "content": content})
    input_items.append(
        {
            "role": "user",
            "content": (
                f"Question: {message}\n\nRetrieved material:\n"
                f"{context or 'No relevant material was retrieved.'}"
            ),
        }
    )

    response = await client.responses.create(
        model=settings.openai_model,
        instructions=instructions,
        input=input_items,
        tools=TOOLS,
    )

    tool_results: list[dict[str, Any]] = []
    for _ in range(3):
        calls = [item for item in response.output if item.type == "function_call"]
        if not calls:
            break
        outputs = []
        for call in calls:
            try:
                arguments = json.loads(call.arguments)
            except json.JSONDecodeError:
                arguments = {}
            result = await _execute_tool(call.name, arguments)
            tool_results.append(result)
            outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(result, ensure_ascii=False),
                }
            )
        response = await client.responses.create(
            model=settings.openai_model,
            instructions=instructions,
            previous_response_id=response.id,
            input=outputs,
            tools=TOOLS,
        )

    content = response.output_text or ""
    lean_code = next(
        (
            item.get("code")
            for item in tool_results
            if item.get("tool") == "lean_verify" and item.get("ok") and item.get("code")
        ),
        None,
    )
    gate = await gate_answer(message, content, tool_results, lean_code=lean_code)
    final = f"{gate.answer_prefix}{content}" if gate.answer_prefix else content
    return final, "openai", gate, tool_results
