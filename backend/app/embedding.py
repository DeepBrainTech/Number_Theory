from __future__ import annotations

import hashlib
import math
import re


DIMENSIONS = 384
MODEL_NAME = "local-hash-v1"

GLOSSARY = {
    "整除": "divisibility divides factor multiple",
    "最大公因数": "greatest common divisor gcd hcf",
    "最大公约数": "greatest common divisor gcd hcf",
    "欧几里得": "Euclid algorithm",
    "辗转相除": "Euclid algorithm remainder",
    "贝祖": "Bezout lemma identity",
    "裴蜀": "Bezout lemma identity",
    "同余": "congruence modulo",
    "线性同余": "linear congruence",
    "中国剩余": "Chinese Remainder Theorem",
    "素数": "prime number",
    "质数": "prime number",
    "唯一分解": "unique factorization",
    "可逆元": "invertible element unit modulo",
    "互素": "coprime relatively prime",
    "环": "ring",
}


def expand_query(text: str) -> str:
    additions = [english for chinese, english in GLOSSARY.items() if chinese in text]
    return " ".join([text, *additions]).strip()


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", expand_query(text).lower())


def lexical_query(text: str) -> str:
    """Return an OR query containing only terms understood by English FTS."""
    unique_tokens = list(dict.fromkeys(_tokens(text)))
    return " OR ".join(unique_tokens)


def embed(text: str) -> list[float]:
    """Create a deterministic lexical projection for a zero-config MVP.

    This is deliberately labelled as a local retrieval vector, not a semantic
    embedding model. It can be replaced without changing the database API.
    """
    values = [0.0] * DIMENSIONS
    for token in _tokens(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % DIMENSIONS
        sign = 1.0 if digest[4] & 1 else -1.0
        values[bucket] += sign
    norm = math.sqrt(sum(value * value for value in values))
    if norm:
        values = [value / norm for value in values]
    return values


def as_pgvector(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in values) + "]"
