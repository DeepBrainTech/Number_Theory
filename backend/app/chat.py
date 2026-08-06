from __future__ import annotations

import json
from typing import Any

import httpx
from openai import AsyncOpenAI

from .config import settings
from .gating import GateResult, gate_answer
from .verification import call_lean, call_sage


SYSTEM_PROMPT = """你是一位严谨的数论教师和研究助手。
先使用检索资料建立定义和论证，再独立检查变量域、定理条件、边界情况与反例。
涉及具体整数计算时应调用 SageMath；用户要求形式化证明，或关键结论适合形式化时，应调用 Lean。
Lean 通过只证明提交的形式命题正确；你仍须确认该形式命题准确表达了用户的问题。
工具失败或资料不足时明确说明不确定性，绝不把模型推测描述成已验证事实。
默认不输出书名、PDF 页码或内部检索过程。使用清晰中文和 LaTeX（行内 $...$，独立公式 $$...$$）。"""

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "sage_calculate",
        "description": "用 SageMath 做精确整数运算。仅支持 gcd、xgcd、factor、is_prime、inverse_mod、crt。",
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
                    "description": "十进制整数；crt 使用 residues 后接 moduli，并用 split 指定分界。",
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
        "description": "用 Lean 4 + mathlib 编译一段完整证明。禁止 sorry、admit 和新增公理。",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "以 import Mathlib 开头、包含 theorem/example 及完整证明的 Lean 4 代码。",
                }
            },
            "required": ["code"],
            "additionalProperties": False,
        },
    },
]


def retrieval_answer(hits: list[dict]) -> str:
    if not hits:
        return "当前已入库资料中没有找到足够相关的内容，暂时无法确认。"
    excerpts = []
    for hit in hits[:3]:
        label = hit["heading"] or hit["block_type"]
        content = hit["content"]
        if len(content) > 700:
            content = content[:700].rstrip() + "…"
        excerpts.append(f"【{label}】\n{content}")
    return "尚未配置 OPENAI_API_KEY。以下是已入库内容的检索结果：\n\n" + "\n\n".join(excerpts)


async def _execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        if name == "sage_calculate":
            result = await call_sage(arguments)
            return {"tool": name, **arguments, **result}
        if name == "lean_verify":
            result = await call_lean(arguments)
            return {"tool": name, **arguments, **result}
        return {"tool": name, "ok": False, "error": f"未知工具：{name}"}
    except (httpx.HTTPError, ValueError) as exc:
        return {"tool": name, "ok": False, "error": f"验证服务调用失败：{exc}"}


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


async def answer(message: str, hits: list[dict]) -> tuple[str, str, GateResult, list[dict[str, Any]]]:
    if not settings.openai_api_key:
        gate = GateResult(
            level="retrieval_only",
            label="仅资料检索，未生成证明",
            notes=["未配置模型密钥，仅返回资料检索结果。"],
        )
        return retrieval_answer(hits), "retrieval", gate, []

    context = "\n\n---\n\n".join(hit["content"] for hit in hits)
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )
    response = await client.responses.create(
        model=settings.openai_model,
        instructions=SYSTEM_PROMPT,
        input=f"问题：{message}\n\n已检索资料：\n{context or '没有检索到相关资料。'}",
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
            instructions=SYSTEM_PROMPT,
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
