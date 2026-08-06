from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


MAX_BODY = 64 * 1024
MAX_CODE = 12_000
TIMEOUT = int(os.getenv("LEAN_TIMEOUT", "60"))
FORBIDDEN = re.compile(
    r"\b(sorry|admit|axiom|unsafe|run_tac)\b|#\s*(eval|check|reduce)|set_option",
    re.IGNORECASE,
)


def verify(data: dict[str, Any]) -> dict[str, Any]:
    code = data.get("code", "")
    if not isinstance(code, str) or not code.strip() or len(code) > MAX_CODE:
        raise ValueError(f"Lean 代码必须为 1–{MAX_CODE} 个字符")
    if FORBIDDEN.search(code):
        raise ValueError("代码含有被禁止的占位证明、公理或执行指令")
    imports = re.findall(r"^\s*import\s+(.+)$", code, flags=re.MULTILINE)
    if not imports or any(not item.strip().startswith("Mathlib") for item in imports):
        raise ValueError("代码必须只从 Mathlib 命名空间导入依赖")

    with tempfile.TemporaryDirectory(prefix="lean-check-") as temp_dir:
        source = Path(temp_dir) / "Main.lean"
        source.write_text(code, encoding="utf-8")
        try:
            process = subprocess.run(
                ["lake", "env", "lean", str(source)],
                cwd=os.getenv("LEAN_WORKDIR", "/mathlib"),
                capture_output=True,
                text=True,
                timeout=TIMEOUT,
                encoding="utf-8",
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "verified": False, "error": "Lean 验证超时"}
    output = (process.stdout + process.stderr).strip()
    return {
        "ok": process.returncode == 0,
        "verified": process.returncode == 0,
        "engine": "Lean 4 + mathlib",
        "output": output[-6000:],
    }


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status: int, data: dict[str, Any]) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            try:
                process = subprocess.run(["lean", "--version"], capture_output=True, text=True)
                self.send_json(200, {"status": "ok", "engine": process.stdout.strip()})
            except OSError as exc:
                self.send_json(503, {"status": "error", "error": str(exc)})
        else:
            self.send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/verify":
            self.send_json(404, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY:
                raise ValueError("请求体大小不合法")
            self.send_json(200, verify(json.loads(self.rfile.read(length))))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.send_json(400, {"ok": False, "verified": False, "error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        return


ThreadingHTTPServer(("0.0.0.0", 8012), Handler).serve_forever()
