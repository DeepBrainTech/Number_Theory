"""OCR fallback for pages without a text layer.

Uses the poppler/tesseract CLIs directly (no Python imaging dependencies):
pdftoppm renders the page to a grayscale PNG, tesseract reads it with
English + Simplified Chinese models. Returns None when OCR is unavailable
or produces almost nothing, so callers can keep the original extraction.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


OCR_DPI = 220
MIN_OCR_CHARS = 40
# Pages whose pdftotext output is shorter than this are considered scan-only.
MIN_NATIVE_CHARS = 40


def ocr_available() -> bool:
    return shutil.which("tesseract") is not None and shutil.which("pdftoppm") is not None


def ocr_page(pdf_path: Path, page: int, *, languages: str = "eng+chi_sim") -> str | None:
    if not ocr_available():
        return None
    with tempfile.TemporaryDirectory(prefix="nt-ocr-") as temp_dir:
        prefix = Path(temp_dir) / "page"
        try:
            subprocess.run(
                [
                    "pdftoppm",
                    "-f",
                    str(page),
                    "-l",
                    str(page),
                    "-r",
                    str(OCR_DPI),
                    "-gray",
                    "-png",
                    str(pdf_path),
                    str(prefix),
                ],
                check=True,
                capture_output=True,
                timeout=120,
            )
        except (subprocess.SubprocessError, OSError):
            return None
        images = sorted(Path(temp_dir).glob("page*.png"))
        if not images:
            return None
        try:
            result = subprocess.run(
                ["tesseract", str(images[0]), "-", "-l", languages, "--psm", "6"],
                check=True,
                capture_output=True,
                timeout=180,
            )
        except (subprocess.SubprocessError, OSError):
            return None
    text = result.stdout.decode("utf-8", errors="replace").strip()
    if len(text) < MIN_OCR_CHARS:
        return None
    return text
