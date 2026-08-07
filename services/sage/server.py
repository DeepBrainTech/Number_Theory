from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from sage.all import (
    QQ,
    EllipticCurve,
    Integer,
    Mod,
    NumberField,
    PolynomialRing,
    QuadraticField,
    crt,
    euler_phi,
    gcd,
    kronecker_symbol,
    legendre_symbol,
    next_prime,
    pari,
    power_mod,
    primitive_root,
    xgcd,
)
from sage.env import SAGE_VERSION


MAX_BODY = 64 * 1024
MAX_DIGITS = 300
# Tighter bounds for operations whose cost explodes with input size.
MAX_CLASS_NUMBER_D = 10**12
MAX_EC_COEFF = 10**9
MAX_DIVISORS_LISTED = 200
MAX_POLY_DEGREE = 12
MAX_POLY_COEFF = 10**6
MAX_PRIME_FOR_DEC = 10**9


def integer(value: Any) -> Integer:
    text = str(value).strip()
    digits = text.lstrip("+-")
    if not digits.isdigit() or len(digits) > MAX_DIGITS:
        raise ValueError(f"参数必须是至多 {MAX_DIGITS} 位的十进制整数")
    return Integer(text)


def _poly_from_coeffs(values: list[Integer]):
    if len(values) < 2:
        raise ValueError("多项式至少需要 2 个系数 (常数项与一次项)")
    if len(values) - 1 > MAX_POLY_DEGREE:
        raise ValueError(f"多项式次数需 ≤ {MAX_POLY_DEGREE}")
    if any(abs(v) > MAX_POLY_COEFF for v in values):
        raise ValueError(f"系数绝对值需 ≤ {MAX_POLY_COEFF}")
    if values[-1] == 0:
        raise ValueError("首项系数不能为 0")
    ring = PolynomialRing(QQ, "x")
    return ring(values)


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
    elif operation == "power_mod" and len(values) == 3:
        if values[2] == 0:
            raise ValueError("模数不能为 0")
        result = str(power_mod(values[0], values[1], values[2]))
    elif operation == "euler_phi" and len(values) == 1:
        if values[0] <= 0:
            raise ValueError("euler_phi 需要正整数")
        result = str(euler_phi(values[0]))
    elif operation == "multiplicative_order" and len(values) == 2:
        if values[1] <= 1:
            raise ValueError("模数必须大于 1")
        result = str(Mod(values[0], values[1]).multiplicative_order())
    elif operation == "legendre_symbol" and len(values) == 2:
        result = str(legendre_symbol(values[0], values[1]))
    elif operation == "kronecker" and len(values) == 2:
        result = str(kronecker_symbol(values[0], values[1]))
    elif operation == "primitive_root" and len(values) == 1:
        result = str(primitive_root(values[0]))
    elif operation == "divisors" and len(values) == 1:
        if values[0] <= 0:
            raise ValueError("divisors 需要正整数")
        divisor_list = values[0].divisors()
        result = {
            "count": len(divisor_list),
            "divisors": [str(d) for d in divisor_list[:MAX_DIVISORS_LISTED]],
            "truncated": len(divisor_list) > MAX_DIVISORS_LISTED,
        }
    elif operation == "next_prime" and len(values) == 1:
        result = str(next_prime(values[0]))
    elif operation == "quadratic_class_number" and len(values) == 1:
        d = values[0]
        if d == 0 or d == 1 or abs(d) > MAX_CLASS_NUMBER_D:
            raise ValueError(f"需要非 0/1 且 |d| ≤ {MAX_CLASS_NUMBER_D} 的无平方因子整数")
        if not d.is_squarefree():
            raise ValueError("d 必须无平方因子")
        field = QuadraticField(d)
        result = {
            "field": f"Q(sqrt({d}))",
            "discriminant": str(field.discriminant()),
            "class_number": str(field.class_number(proof=False)),
        }
    elif operation == "elliptic_curve_invariants" and len(values) == 5:
        if any(abs(v) > MAX_EC_COEFF for v in values):
            raise ValueError(f"椭圆曲线系数绝对值需 ≤ {MAX_EC_COEFF}")
        curve = EllipticCurve([values[0], values[1], values[2], values[3], values[4]])
        result = {
            "weierstrass": str(curve),
            "discriminant": str(curve.discriminant()),
            "j_invariant": str(curve.j_invariant()),
            "conductor": str(curve.conductor()),
            "torsion_order": int(curve.torsion_order()),
        }
    elif operation == "pari_bnfinit" and len(values) >= 2:
        # Coefficients a0..an of a0 + a1 x + ... + an x^n defining K = Q[x]/(f).
        poly = _poly_from_coeffs(values)
        if not poly.is_irreducible():
            raise ValueError("定义多项式必须在 Q 上不可约")
        field = NumberField(poly, names="a")
        result = {
            "polynomial": str(poly),
            "degree": int(field.degree()),
            "discriminant": str(field.discriminant()),
            "signature": [int(field.signature()[0]), int(field.signature()[1])],
            "class_number": str(field.class_number(proof=False)),
            "engine": "Sage NumberField / PARI bnfinit",
        }
    elif operation == "ideal_prime_dec" and len(values) >= 3:
        # coeffs a0..an followed by a rational prime p.
        prime = values[-1]
        if prime <= 1 or prime > MAX_PRIME_FOR_DEC or not prime.is_prime():
            raise ValueError(f"最后一个参数必须是 ≤ {MAX_PRIME_FOR_DEC} 的素数")
        poly = _poly_from_coeffs(values[:-1])
        if not poly.is_irreducible():
            raise ValueError("定义多项式必须在 Q 上不可约")
        field = NumberField(poly, names="a")
        factors = field.ideal(prime).factor()
        result = {
            "field": str(field.polynomial()),
            "prime": str(prime),
            "factors": [
                {
                    "ideal": str(ideal),
                    "residue_degree": int(ideal.residue_class_degree()),
                    "ramification_index": int(exponent),
                }
                for ideal, exponent in factors
            ],
            "engine": "Sage ideal.factor / PARI idealprimedec",
        }
    elif operation == "pari_polgalois" and len(values) >= 2:
        poly = _poly_from_coeffs(values)
        if not poly.is_irreducible():
            raise ValueError("polgalois 需要 Q 上不可约多项式")
        gal = pari(poly).polgalois()
        # PARI returns [n, s, k, name] roughly: degree, sign, index, group label.
        result = {
            "polynomial": str(poly),
            "pari_polgalois": str(gal),
            "degree": int(poly.degree()),
            "engine": "PARI polgalois",
        }
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
        except Exception as exc:  # noqa: BLE001 - the sandbox must always answer
            self.send_json(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})

    def log_message(self, format: str, *args: Any) -> None:
        return


# PARI-backed functions (euler_phi, next_prime, class numbers, elliptic curves,
# bnfinit) segfault when first used from a worker thread: cysignals requires the
# main thread. A single-threaded server keeps every computation on the main thread;
# warming PARI at startup surfaces initialization problems immediately.
assert str(euler_phi(Integer(10))) == "4"

HTTPServer(("0.0.0.0", 8011), Handler).serve_forever()
