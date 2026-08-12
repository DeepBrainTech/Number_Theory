from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql://number_theory:number_theory_dev@localhost:5433/number_theory",
    )
    cors_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:3000,https://proof-lab.deepbrainacademy.org",
        ).split(",")
        if origin.strip()
    )
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-5.6-sol")
    openai_base_url: str | None = os.getenv("OPENAI_BASE_URL") or None
    sage_url: str = os.getenv("SAGE_URL", "http://localhost:8011").rstrip("/")
    lean_url: str = os.getenv("LEAN_URL", "http://localhost:8012").rstrip("/")
    verifier_timeout: float = float(os.getenv("VERIFIER_TIMEOUT", "70"))
    research_tool_timeout: float = float(os.getenv("RESEARCH_TOOL_TIMEOUT", "20"))
    semantic_scholar_api_key: str = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
    auto_prove_runs_dir: Path = Path(
        os.getenv("AUTO_PROVE_RUNS_DIR", "data/auto_prove_runs")
    ).resolve()
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    session_secret: str = os.getenv("SESSION_SECRET", "dev-insecure-session-secret-change-me")
    cookie_secure: bool = os.getenv("COOKIE_SECURE", "0") == "1"
    # lax | strict | none — use "none" when the browser talks to the API cross-site
    # (e.g. frontend on deepbrainacademy.org, API on railway.app). Browsers require
    # Secure when SameSite=None; we force cookie_secure in that case.
    cookie_samesite: str = os.getenv("COOKIE_SAMESITE", "lax").strip().lower() or "lax"


settings = Settings()
