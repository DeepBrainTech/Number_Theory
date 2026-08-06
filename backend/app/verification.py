from __future__ import annotations

from typing import Any

import httpx

from .config import settings


async def service_health(url: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{url}/health")
            response.raise_for_status()
            return {"available": True, **response.json()}
    except (httpx.HTTPError, ValueError) as exc:
        return {"available": False, "error": str(exc)}


async def verifier_status() -> dict[str, Any]:
    return {
        "openai": {
            "configured": bool(settings.openai_api_key),
            "model": settings.openai_model,
        },
        "sage": await service_health(settings.sage_url),
        "lean": await service_health(settings.lean_url),
    }


async def call_sage(arguments: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=settings.verifier_timeout) as client:
        response = await client.post(f"{settings.sage_url}/calculate", json=arguments)
        if response.status_code >= 500:
            response.raise_for_status()
        return response.json()


async def call_lean(arguments: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=settings.verifier_timeout + 5) as client:
        response = await client.post(f"{settings.lean_url}/verify", json=arguments)
        if response.status_code >= 500:
            response.raise_for_status()
        return response.json()
