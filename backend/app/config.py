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
    pdf_root: Path = Path(os.getenv("PDF_ROOT", "../pdf")).resolve()
    cors_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
        if origin.strip()
    )
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-5.6-sol")
    openai_base_url: str | None = os.getenv("OPENAI_BASE_URL") or None
    sage_url: str = os.getenv("SAGE_URL", "http://localhost:8011").rstrip("/")
    lean_url: str = os.getenv("LEAN_URL", "http://localhost:8012").rstrip("/")
    verifier_timeout: float = float(os.getenv("VERIFIER_TIMEOUT", "25"))


settings = Settings()
