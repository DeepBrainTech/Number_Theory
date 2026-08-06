from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from sage.all import Integer, crt, gcd, xgcd
from sage.env import SAGE_VERSION


MAX_BODY = 64 * 1024
MAX_DIGITS = 300


def integer(value: Any) -> Integer:
    text = str(value).strip()
    digits = text.lstrip("+-")
    if not digits.isdigit() or len(digits) > MAX_DIGITS:
        raise ValueError(f"参数必须是至多 {MAX_DIGITS} 位的十进制整数")
    return Integer(text)


def calculate(data: dict[str, Any]) -> dict[str, Any]:
    operation = data.get("operation")
    values = [integer(value) for value in data.get("arguments", [])]
    if operation == "gcd" and len(values) == 2:
        result: Any = str(gcd(values[0], values[1]))
    elif operation == "xgcd" and len(values) == 2:
        result = [str(value) for value in xgcd(values[0], values[1])]
    elif operation == "factor" and len(values) == 1:
        result = [[str(p), int(e)] for p, e in values[0].factor()]
    elif operation == "is_prime" and len(values) == 1:
        result = bool(values[0].is_prime(proof=True))
    elif operation == "inverse_mod" and len(values) == 2:
        result = str(values[0].inverse_mod(values[1]))
    elif operation == "crt":
        split = data.get("split")
        if not isinstance(split, int) or split <= 0 or len(values) != 2 * split:
            raise ValueError("crt 需要等长的余数与模数，split 是两组参数的分界")
        result = str(crt(values[:split], values[split:]))
    else:
        raise ValueError("不支持的操作或参数数量不正确")
    return {"ok": True, "engine": f"SageMath {SAGE_VERSION}", "result": result}


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
            self.send_json(200, {"status": "ok", "engine": f"SageMath {SAGE_VERSION}"})
        else:
            self.send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/calculate":
            self.send_json(404, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY:
                raise ValueError("请求体大小不合法")
            data = json.loads(self.rfile.read(length))
            self.send_json(200, calculate(data))
        except (ValueError, TypeError, ArithmeticError) as exc:
            self.send_json(400, {"ok": False, "error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        return


ThreadingHTTPServer(("0.0.0.0", 8011), Handler).serve_forever()
