from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

pdf_root = Path("/data/pdf")


def page_count(path: Path) -> int | None:
    try:
        out = subprocess.check_output(["pdfinfo", str(path)], text=True, errors="replace")
        match = re.search(r"Pages:\s+(\d+)", out)
        return int(match.group(1)) if match else None
    except Exception:
        return None


def extract(path: Path, page: int) -> str:
    try:
        out = subprocess.check_output(
            [
                "pdftotext",
                "-f",
                str(page),
                "-l",
                str(page),
                "-layout",
                "-enc",
                "UTF-8",
                str(path),
                "-",
            ],
            stderr=subprocess.DEVNULL,
        )
        return out.decode("utf-8", "replace")
    except Exception:
        return ""


rows = []
for path in sorted(pdf_root.glob("*.pdf")):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    total = page_count(path)
    if total:
        samples = sorted({1, max(1, total // 4), max(1, total // 2), max(1, 3 * total // 4), total})
    else:
        samples = [1, 2, 10]
    texts = [extract(path, page) for page in samples]
    chars = [len(re.sub(r"\s+", "", text)) for text in texts]
    avg = sum(chars) / len(chars) if chars else 0
    joined = "\n".join(texts)
    letters = len(re.findall(r"[A-Za-z\u4e00-\u9fff]", joined))
    ratio = letters / max(1, len(joined.replace("\x0c", "")))
    if avg >= 400 and ratio >= 0.15:
        status = "good"
    elif avg >= 80:
        status = "sparse"
    else:
        status = "empty/scan"
    rows.append((status, total or -1, avg, round(ratio, 3), digest, path.name, chars))

for status, total, avg, ratio, digest, name, chars in sorted(
    rows, key=lambda item: (0 if item[0] == "good" else 1 if item[0] == "sparse" else 2, item[5])
):
    print(
        f"{status:12} pages={total:4} avg_chars={avg:7.1f} "
        f"letter_ratio={ratio:.3f} sha={digest}  {name}"
    )
    print(f"             sample_chars={chars}")
