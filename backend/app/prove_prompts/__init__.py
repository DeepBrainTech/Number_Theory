"""QED-inspired system prompts for Auto Prove."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).resolve().parent

_RUNTIME_NOTE = """

---

# Proof Lab service runtime

You do not have a host shell. Use these tools instead of bash:

- `list_run_files`, `read_run_file`, and `write_run_file` for this run directory. Paths in the prompt are relative to the run root.
- `fetch_url` and `fetch_pdf_text` to open papers and verify citations against the source.
- `web_search` plus the literature tools (arXiv, Crossref, Semantic Scholar, OEIS) for discovery. Search as many times as the task needs.
- `sage_calculate` for named exact number-theory operations; `sage_execute` for other SageMath exploration. Print the values you need.

Write every required output file with `write_run_file` before you finish. If you also return text, the file on disk is authoritative. Do not select or configure a model; the backend supplies one model for every role.
"""


class _FormatDict(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    path = _DIR / name
    return path.read_text(encoding="utf-8").strip()


def skill_text() -> str:
    """The upstream QED proof-methodology prompt, verbatim."""
    return load_prompt("qed/skill.md")


@lru_cache(maxsize=None)
def _qed_original(name: str) -> str:
    path = _DIR / "qed" / name.rsplit("/", 1)[-1]
    return path.read_text(encoding="utf-8").strip()


def qed_prompt(name: str, paths: dict[str, str] | None = None) -> str:
    """Load a proofQED/QED role prompt and fill path placeholders.

    QED's original prompts address agents that read and write files. This
    service keeps those paths (relative to the run directory) and appends a
    short note that tools replace bash.
    """
    rendered = _qed_original(name).format_map(_FormatDict({k: str(v) for k, v in (paths or {}).items()}))
    return rendered + _RUNTIME_NOTE
