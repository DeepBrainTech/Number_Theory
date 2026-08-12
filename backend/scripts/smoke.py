"""End-to-end smoke test against a running docker-compose stack.

Usage:  python backend/scripts/smoke.py [--base http://localhost:8000]

Checks: health, Sage whitelist ops, Lean compilation, tools status,
and optionally the chat endpoint. Prints PASS/FAIL per step; exits
non-zero if any required step fails.
"""

from __future__ import annotations

import argparse
import sys
import uuid

import httpx


# Narrow import keeps the smoke fast; `import Mathlib` loads all of mathlib
# and can take minutes on slow Docker I/O.
LEAN_SMOKE = """import Mathlib.Tactic.NormNum

example : 2 + 2 = 4 := by norm_num
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--skip-lean", action="store_true", help="Lean compile can take ~1 min")
    parser.add_argument("--chat", action="store_true", help="Also exercise /api/chat (uses tokens)")
    args = parser.parse_args()

    client = httpx.Client(base_url=args.base, timeout=120)
    client_id = f"smoke-{uuid.uuid4().hex[:12]}"
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(name)

    response = client.get("/health")
    check("health", response.status_code == 200, response.text[:120])

    sage_cases = [
        ({"operation": "gcd", "arguments": ["391", "299"], "split": None}, "23"),
        ({"operation": "power_mod", "arguments": ["3", "100", "7"], "split": None}, "4"),
        ({"operation": "euler_phi", "arguments": ["100"], "split": None}, "40"),
        ({"operation": "legendre_symbol", "arguments": ["2", "7"], "split": None}, "1"),
        ({"operation": "multiplicative_order", "arguments": ["2", "9"], "split": None}, "6"),
        ({"operation": "next_prime", "arguments": ["100"], "split": None}, "101"),
    ]
    for body, expected in sage_cases:
        response = client.post("/api/tools/sage", json=body)
        payload = response.json() if response.status_code == 200 else {}
        ok = payload.get("ok") is True and str(payload.get("result")) == expected
        check(f"sage {body['operation']}", ok, f"got {payload.get('result')!r}, want {expected!r}")

    response = client.post(
        "/api/tools/sage",
        json={"operation": "quadratic_class_number", "arguments": ["-23"], "split": None},
    )
    payload = response.json() if response.status_code == 200 else {}
    ok = payload.get("ok") is True and payload.get("result", {}).get("class_number") == "3"
    check("sage quadratic_class_number(-23)=3", ok, str(payload.get("result"))[:80])

    # x^2 + 1 is irreducible over Q; bnfinit should return degree 2.
    response = client.post(
        "/api/tools/sage",
        json={"operation": "pari_bnfinit", "arguments": ["1", "0", "1"], "split": None},
    )
    payload = response.json() if response.status_code == 200 else {}
    ok = payload.get("ok") is True and payload.get("result", {}).get("degree") == 2
    check("sage pari_bnfinit(x^2+1)", ok, str(payload.get("result"))[:100])

    response = client.post(
        "/api/tools/sage",
        json={
            "operation": "ideal_prime_dec",
            "arguments": ["1", "0", "1", "5"],
            "split": None,
        },
    )
    payload = response.json() if response.status_code == 200 else {}
    factors = (payload.get("result") or {}).get("factors") if payload.get("ok") else None
    check(
        "sage ideal_prime_dec(x^2+1, 5)",
        isinstance(factors, list) and len(factors) >= 1,
        str(payload.get("result"))[:100],
    )

    if not args.skip_lean:
        response = client.post("/api/tools/lean", json={"code": LEAN_SMOKE})
        payload = response.json() if response.status_code == 200 else {}
        check("lean compile", payload.get("verified") is True, str(payload.get("output", ""))[:120])

    response = client.get("/api/tools/status")
    payload = response.json() if response.status_code == 200 else {}
    check(
        "tools status",
        response.status_code == 200,
        f"sage={payload.get('sage', {}).get('available')} lean={payload.get('lean', {}).get('available')}",
    )

    if args.chat:
        response = client.post(
            "/api/chat",
            json={
                "message": "What is Bezout's lemma?",
                "answer_mode": "teach",
            },
        )
        payload = response.json() if response.status_code == 200 else {}
        check(
            "chat",
            response.status_code == 200 and bool(payload.get("answer")),
            f"level={payload.get('verification_level')}",
        )
        conversation_id = payload.get("conversation_id")
        if conversation_id:
            response = client.get(f"/api/conversations/{conversation_id}/verification-log")
            check(
                "verification log download",
                response.status_code == 200 and "attachment" in response.headers.get("content-disposition", ""),
            )

    print()
    if failures:
        print(f"{len(failures)} step(s) failed: {', '.join(failures)}")
        return 1
    print("All smoke steps passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
