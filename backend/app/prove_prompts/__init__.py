"""QED-inspired system prompts for Auto Prove."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    path = _DIR / name
    return path.read_text(encoding="utf-8").strip()


def skill_text() -> str:
    """The upstream QED proof-methodology prompt, verbatim."""
    return load_prompt("qed/skill.md")


@lru_cache(maxsize=None)
def qed_prompt(name: str) -> str:
    """Load a verbatim proofQED/QED role prompt.

    QED's original prompts address agents that exchange files.  This service
    passes the equivalent artifacts in its JSON user message, so the brief
    runtime note is deliberately appended rather than rewriting QED's text.
    """
    # Vendored files are flattened because only the prompt filename matters;
    # callers retain QED's upstream directory names for readability.
    path = _DIR / "qed" / name.rsplit("/", 1)[-1]
    original = path.read_text(encoding="utf-8").strip()
    rendered = re.sub(
        r"\{([a-z_]+)\}",
        lambda match: f"`{match.group(1)}` from the JSON user message",
        original,
    )
    return rendered + (
        "\n\n---\n\n"
        "# Proof Lab service runtime\n\n"
        "This service preserves the QED role instructions above verbatim, but "
        "does not grant model filesystem access. Every referenced input file is "
        "provided in the JSON user message as the correspondingly named content "
        "(`problem`, `plan`, `proof`, verification reports, histories, and so on). "
        "Return the requested artifact directly in your response instead of writing a file. "
        "Do not select or configure a model; the backend supplies one model for every role."
    )
