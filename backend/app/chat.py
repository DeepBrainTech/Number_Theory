from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from openai import AsyncOpenAI

from .config import settings
from .gating import LEVEL_LABELS, GateResult, gate_answer
from .memory import format_memory_block
from .modes import (
    AnswerMode,
    ResolvedMode,
    TeachDepth,
    enforce_research_structure,
    resolve_answer_mode,
    system_prompt_for,
)
from .latex_ocr import decode_image
from .research import (
    arxiv_search,
    crossref_search,
    literature_search,
    oeis_search,
    semantic_scholar_search,
)
from .verification import call_sage


SAGE_OPERATIONS = [
    "gcd",
    "xgcd",
    "factor",
    "is_prime",
    "inverse_mod",
    "crt",
    "power_mod",
    "euler_phi",
    "multiplicative_order",
    "legendre_symbol",
    "kronecker",
    "primitive_root",
    "divisors",
    "next_prime",
    "quadratic_class_number",
    "elliptic_curve_invariants",
    "pari_bnfinit",
    "ideal_prime_dec",
    "pari_polgalois",
]


StatusEmitter = Callable[[str, str | None], Awaitable[None]]
DeltaEmitter = Callable[[str], Awaitable[None]]
ResetEmitter = Callable[[], Awaitable[None]]


async def emit_status(emitter: StatusEmitter | None, phase: str, detail: str | None = None) -> None:
    if emitter is not None:
        await emitter(phase, detail)


# Hosted by OpenAI; executed inside the Responses API (no local round-trip).
WEB_SEARCH_TOOL: dict[str, Any] = {"type": "web_search"}

# Lean formalization lives in the Lean workbench UI (statement confirm → compile).
# Chat agents keep Sage for concrete checks; they should not silently claim V4.
BASE_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "sage_calculate",
        "description": (
            "Exact number-theory computation via SageMath (whitelisted operations only). "
            "Arguments are decimal integers as strings. Signatures: gcd(a,b); xgcd(a,b); "
            "factor(n); is_prime(n); inverse_mod(a,m); crt(residues+moduli with split as the "
            "boundary index); power_mod(a,e,m); euler_phi(n); multiplicative_order(a,m); "
            "legendre_symbol(a,p) with p an odd prime; kronecker(a,n); primitive_root(m); "
            "divisors(n); next_prime(n); quadratic_class_number(d) with d a squarefree integer "
            "(class number of Q(sqrt(d))); elliptic_curve_invariants(a1,a2,a3,a4,a6); "
            "pari_bnfinit(a0..an) for NumberField invariants of Q[x]/(a0+...+an x^n); "
            "ideal_prime_dec(a0..an,p) for prime ideal factorization of (p); "
            "pari_polgalois(a0..an) for the Galois group label of an irreducible poly."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": SAGE_OPERATIONS},
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
]

RESEARCH_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "arxiv_search",
        "description": (
            "Search arXiv preprints. Pass a short natural-language query (topic + optional year, "
            "e.g. 'mathematics 2026' or 'number theory 2024'); do not write submittedDate syntax."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": ["integer", "null"], "description": "1-10, default 5."},
            },
            "required": ["query", "max_results"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "oeis_search",
        "description": (
            "Search the OEIS. Query with comma-separated terms (e.g. '1,1,2,3,5,8') "
            "or keywords; returns sequence ids, names, and initial terms."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": ["integer", "null"], "description": "1-10, default 3."},
            },
            "required": ["query", "max_results"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "crossref_search",
        "description": "Search Crossref for published papers (title, authors, year, DOI).",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": ["integer", "null"], "description": "1-10, default 5."},
            },
            "required": ["query", "max_results"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "semantic_scholar_search",
        "description": "Search Semantic Scholar for papers (title, abstract, citations, DOI).",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": ["integer", "null"], "description": "1-10, default 5."},
            },
            "required": ["query", "max_results"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "literature_search",
        "description": (
            "Fan-out search across arXiv + Crossref + Semantic Scholar with DOI/title deduplication. "
            "Prefer this when surveying a topic broadly. Use natural language (topic + year)."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": ["integer", "null"], "description": "1-10, default 5."},
            },
            "required": ["query", "max_results"],
            "additionalProperties": False,
        },
    },
]


def tools_for(_mode: ResolvedMode) -> list[dict[str, Any]]:
    """Sage, web search, and literature tools in every mode; research mode only changes the answer template."""
    return [WEB_SEARCH_TOOL, *BASE_TOOLS, *RESEARCH_TOOLS]


def missing_api_key_answer() -> str:
    return "OPENAI_API_KEY is not configured. Chat needs a model API key."


async def execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        if name == "sage_calculate":
            result = await call_sage(arguments)
            return {"tool": name, **arguments, **result}
        if name == "arxiv_search":
            result = await arxiv_search(arguments.get("query", ""), arguments.get("max_results") or 5)
            return {"tool": name, **arguments, **result}
        if name == "oeis_search":
            result = await oeis_search(arguments.get("query", ""), arguments.get("max_results") or 3)
            return {"tool": name, **arguments, **result}
        if name == "crossref_search":
            result = await crossref_search(
                arguments.get("query", ""), arguments.get("max_results") or 5
            )
            return {"tool": name, **arguments, **result}
        if name == "semantic_scholar_search":
            result = await semantic_scholar_search(
                arguments.get("query", ""), arguments.get("max_results") or 5
            )
            return {"tool": name, **arguments, **result}
        if name == "literature_search":
            result = await literature_search(
                arguments.get("query", ""), arguments.get("max_results") or 5
            )
            return {"tool": name, **arguments, **result}
        return {"tool": name, "ok": False, "error": f"Unknown tool: {name}"}
    except (httpx.HTTPError, ValueError) as exc:
        return {"tool": name, "ok": False, "error": f"Verifier call failed: {exc}"}


def _attr(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def collect_hosted_tool_results(response: Any) -> list[dict[str, Any]]:
    """Pull OpenAI-hosted web_search calls and URL citations out of a Responses payload."""
    results: list[dict[str, Any]] = []
    citations: list[dict[str, str]] = []
    for item in _attr(response, "output", None) or []:
        itype = _attr(item, "type")
        if itype == "web_search_call":
            action = _attr(item, "action")
            results.append(
                {
                    "tool": "web_search",
                    "ok": _attr(item, "status", "completed") == "completed",
                    "query": _attr(action, "query") if action is not None else None,
                }
            )
        elif itype == "message":
            for part in _attr(item, "content", None) or []:
                for annotation in _attr(part, "annotations", None) or []:
                    if _attr(annotation, "type") == "url_citation":
                        url = _attr(annotation, "url") or ""
                        title = _attr(annotation, "title") or url
                        if url:
                            citations.append({"url": url, "title": title})
    if citations:
        if results:
            results[-1]["citations"] = citations
        else:
            results.append({"tool": "web_search", "ok": True, "citations": citations})
    return results


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
        return cleaned or "Image message"
    return cleaned[:24].rstrip() + "…"


def validate_images(images: list[str]) -> list[str]:
    validated: list[str] = []
    for image in images:
        raw, media_type = decode_image(image)
        b64 = base64.b64encode(raw).decode("ascii")
        validated.append(f"data:{media_type};base64,{b64}")
    return validated


def build_user_turn(
    message: str,
    *,
    mode_label: str,
    depth_note: str,
    images: list[str] | None = None,
) -> dict[str, Any]:
    question = message.strip() or "(see attached image(s))"
    text = f"Answer mode: {mode_label}{depth_note}\nQuestion: {question}"
    if not images:
        return {"role": "user", "content": text}
    parts: list[dict[str, Any]] = [{"type": "input_text", "text": text}]
    for image in images:
        parts.append({"type": "input_image", "image_url": image})
    return {"role": "user", "content": parts}


def provisional_gate() -> GateResult:
    return GateResult(
        level="V0",
        label=LEVEL_LABELS["V0"],
        notes=["Verification running in the background…"],
    )


def _is_web_search_event(event: Any) -> bool:
    etype = getattr(event, "type", None) or ""
    if etype.startswith("response.web_search_call"):
        return True
    if etype == "response.output_item.added":
        return _attr(getattr(event, "item", None), "type") == "web_search_call"
    return False


async def _stream_model_response(
    client: AsyncOpenAI,
    *,
    model: str,
    instructions: str,
    input_items: list[dict[str, Any]] | list[Any],
    tools: list[dict[str, Any]],
    previous_response_id: str | None = None,
    delta_emitter: DeltaEmitter | None = None,
    status_emitter: StatusEmitter | None = None,
) -> Any:
    kwargs: dict[str, Any] = {
        "model": model,
        "instructions": instructions,
        "input": input_items,
        "tools": tools,
        "stream": True,
    }
    if previous_response_id:
        kwargs["previous_response_id"] = previous_response_id

    stream = await client.responses.create(**kwargs)
    response = None
    search_announced = False
    async for event in stream:
        etype = getattr(event, "type", None)
        if etype == "response.output_text.delta":
            delta = getattr(event, "delta", None) or ""
            if delta and delta_emitter is not None:
                await delta_emitter(delta)
        elif not search_announced and _is_web_search_event(event):
            search_announced = True
            await emit_status(status_emitter, "tool", "web_search")
        elif etype == "response.completed":
            response = event.response
    if response is None:
        raise RuntimeError("Model stream ended without a completed response")
    return response


async def _run_tool_calls(
    calls: list[Any],
    *,
    status_emitter: StatusEmitter | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    async def _one(call: Any) -> tuple[Any, dict[str, Any]]:
        try:
            arguments = json.loads(call.arguments)
        except json.JSONDecodeError:
            arguments = {}
        await emit_status(status_emitter, "tool", call.name)
        result = await execute_tool(call.name, arguments)
        return call, result

    pairs = await asyncio.gather(*[_one(call) for call in calls])
    tool_results: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    for call, result in pairs:
        tool_results.append(result)
        outputs.append(
            {
                "type": "function_call_output",
                "call_id": call.call_id,
                "output": json.dumps(result, ensure_ascii=False),
            }
        )
    return tool_results, outputs


def _apply_structure_notes(gate: GateResult, structure_notes: list[str]) -> GateResult:
    if not structure_notes:
        return gate
    gate.notes = list(dict.fromkeys([*structure_notes, *gate.notes]))
    if gate.level not in {"retrieval_only", "V0"}:
        gate.level = "V0"
        gate.label = LEVEL_LABELS["V0"]
        gate.answer_prefix = (
            "[Correctness gate] Research sections incomplete; "
            "do not treat the content below as a verified survey.\n\n"
        )
    return gate


async def generate_answer(
    message: str,
    *,
    history: list[dict[str, str]] | None = None,
    memories: list[str] | None = None,
    answer_mode: AnswerMode = "auto",
    teach_depth: TeachDepth = "full",
    images: list[str] | None = None,
    status_emitter: StatusEmitter | None = None,
    delta_emitter: DeltaEmitter | None = None,
    reset_emitter: ResetEmitter | None = None,
) -> tuple[str, ResolvedMode | str, list[dict[str, Any]], list[str]]:
    """Generate the model answer (tools included). Does not run the correctness gate."""
    search_query = message.strip() or "mathematics"
    resolved_mode = resolve_answer_mode(search_query, answer_mode)
    if not settings.openai_api_key:
        return missing_api_key_answer(), "retrieval", [], []

    instructions = system_prompt_for(resolved_mode, teach_depth) + format_memory_block(
        memories or []
    )
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
    mode_label = {
        "teach": "teaching",
        "solve": "problem-solving",
        "physics": "physics problem-solving",
        "research": "research",
    }[resolved_mode]
    depth_note = f"\nDepth: {teach_depth}" if resolved_mode in {"teach", "solve", "physics"} else ""
    input_items.append(
        build_user_turn(
            message,
            mode_label=mode_label,
            depth_note=depth_note,
            images=images,
        )
    )

    tools = tools_for(resolved_mode)
    await emit_status(status_emitter, "thinking")
    response = await _stream_model_response(
        client,
        model=settings.openai_model,
        instructions=instructions,
        input_items=input_items,
        tools=tools,
        delta_emitter=delta_emitter,
        status_emitter=status_emitter,
    )

    tool_results: list[dict[str, Any]] = collect_hosted_tool_results(response)
    max_tool_rounds = 5 if resolved_mode == "research" else 4
    for _ in range(max_tool_rounds):
        calls = [item for item in response.output if item.type == "function_call"]
        if not calls:
            break
        if reset_emitter is not None:
            await reset_emitter()
        round_results, outputs = await _run_tool_calls(calls, status_emitter=status_emitter)
        tool_results.extend(round_results)
        await emit_status(status_emitter, "thinking")
        response = await _stream_model_response(
            client,
            model=settings.openai_model,
            instructions=instructions,
            input_items=outputs,
            tools=tools,
            previous_response_id=response.id,
            delta_emitter=delta_emitter,
            status_emitter=status_emitter,
        )
        tool_results.extend(collect_hosted_tool_results(response))

    content = response.output_text or ""
    structure_notes: list[str] = []
    if resolved_mode == "research":
        await emit_status(status_emitter, "structuring")
        structured, structure_notes = enforce_research_structure(content)
        if structured != content:
            if reset_emitter is not None:
                await reset_emitter()
            if delta_emitter is not None:
                await delta_emitter(structured)
        content = structured

    return content, resolved_mode, tool_results, structure_notes


async def answer(
    message: str,
    *,
    history: list[dict[str, str]] | None = None,
    memories: list[str] | None = None,
    answer_mode: AnswerMode = "auto",
    teach_depth: TeachDepth = "full",
    images: list[str] | None = None,
    status_emitter: StatusEmitter | None = None,
    delta_emitter: DeltaEmitter | None = None,
    reset_emitter: ResetEmitter | None = None,
    run_gate: bool = True,
) -> tuple[str, ResolvedMode | str, GateResult, list[dict[str, Any]]]:
    content, resolved_mode, tool_results, structure_notes = await generate_answer(
        message,
        history=history,
        memories=memories,
        answer_mode=answer_mode,
        teach_depth=teach_depth,
        images=images,
        status_emitter=status_emitter,
        delta_emitter=delta_emitter,
        reset_emitter=reset_emitter,
    )

    if not run_gate:
        gate = _apply_structure_notes(provisional_gate(), structure_notes)
        return content, resolved_mode, gate, tool_results

    search_query = message.strip() or "mathematics"
    await emit_status(status_emitter, "gating")
    gate = await gate_answer(search_query, content, tool_results, lean_code=None)
    gate = _apply_structure_notes(gate, structure_notes)
    final = f"{gate.answer_prefix}{content}" if gate.answer_prefix else content
    return final, resolved_mode, gate, tool_results
