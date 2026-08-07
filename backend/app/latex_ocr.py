"""Formula image → LaTeX via a vision-capable OpenAI model."""

from __future__ import annotations

import base64
import json
import re
from typing import Any

from openai import AsyncOpenAI

from .config import settings

MAX_IMAGE_BYTES = 4 * 1024 * 1024
ALLOWED_MEDIA = frozenset({"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"})

LATEX_PROMPT = (
    "You read a screenshot of a mathematical formula or statement. "
    "Transcribe it as LaTeX suitable for KaTeX. "
    "Output JSON only, no Markdown fences: "
    '{"latex":string,"display":bool,"confidence":"high|medium|low","notes":[string]}. '
    "Rules: latex must NOT include outer $ or $$ delimiters; use standard commands "
    "(\\mathbb{Z}, \\equiv, \\pmod, \\gcd, \\varphi, \\frac, etc.); "
    "set display=true for centered display equations, false for inline fragments; "
    "if uncertain about a symbol, pick the most likely reading and note it in notes."
)


def parse_latex_payload(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("response is not a JSON object")
    latex = str(data.get("latex", "")).strip()
    if not latex:
        raise ValueError("empty latex field")
    latex = latex.strip("$").strip()
    display = bool(data.get("display"))
    confidence = str(data.get("confidence") or "medium").lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "medium"
    notes = [
        item.strip()
        for item in data.get("notes") or []
        if isinstance(item, str) and item.strip()
    ]
    return {
        "latex": latex,
        "display": display,
        "confidence": confidence,
        "notes": notes,
    }


def wrap_latex(latex: str, *, display: bool) -> str:
    if display:
        return f"\n$$\n{latex}\n$$\n"
    return f"${latex}$"


def decode_image(data_url: str) -> tuple[bytes, str]:
    """Accept raw base64 or a data: URL; return (bytes, media_type)."""
    text = data_url.strip()
    media_type = "image/png"
    if text.startswith("data:"):
        header, _, payload = text.partition(",")
        if not payload:
            raise ValueError("invalid data URL")
        match = re.match(r"data:([^;]+)", header)
        if match:
            media_type = match.group(1).lower()
        text = payload
    if media_type not in ALLOWED_MEDIA:
        raise ValueError(f"unsupported image type: {media_type}")
    try:
        raw = base64.b64decode(text, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("invalid base64 image data") from exc
    if not raw:
        raise ValueError("empty image")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError(f"image exceeds {MAX_IMAGE_BYTES // (1024 * 1024)}MB limit")
    return raw, media_type


async def image_to_latex(image_data: str) -> dict[str, Any]:
    if not settings.openai_api_key:
        return {"ok": False, "error": "OPENAI_API_KEY is not configured."}
    try:
        raw, media_type = decode_image(image_data)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    b64 = base64.b64encode(raw).decode("ascii")
    data_url = f"data:{media_type};base64,{b64}"
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )

    try:
        response = await client.responses.create(
            model=settings.openai_model,
            instructions=LATEX_PROMPT,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Transcribe the formula in this image to LaTeX JSON.",
                        },
                        {"type": "input_image", "image_url": data_url},
                    ],
                }
            ],
        )
        parsed = parse_latex_payload(response.output_text or "")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Vision transcription failed: {exc}"}

    wrapped = wrap_latex(parsed["latex"], display=parsed["display"])
    return {
        "ok": True,
        "latex": parsed["latex"],
        "display": parsed["display"],
        "wrapped": wrapped,
        "confidence": parsed["confidence"],
        "notes": parsed["notes"],
    }
