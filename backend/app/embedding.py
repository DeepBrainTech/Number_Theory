from __future__ import annotations

import re

from openai import OpenAI

from .config import settings


DIMENSIONS = 1536
MODEL_NAME = "text-embedding-3-small"
BATCH_SIZE = 64

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
    "多项式": "polynomial ring F[X]",
    "多项式环": "polynomial ring",
    "首一": "monic polynomial",
    "首项系数": "leading coefficient",
    "次数": "degree of polynomial",
    "不可约": "irreducible polynomial",
    "唯一分解整环": "unique factorization domain UFD",
    "整环": "integral domain",
    "长除法": "polynomial long division",
    "最高公因式": "highest common factor polynomial gcd",
    "费马小定理": "Fermat little theorem",
    "欧拉函数": "Euler totient phi",
    "原根": "primitive root",
    "二次互反": "quadratic reciprocity",
    "勒让德": "Legendre symbol",
    "p进": "p-adic",
    "亨泽尔": "Hensel lemma",
    "丢番图": "Diophantine equation",
    "佩尔方程": "Pell equation",
    "连分数": "continued fraction",
    "黎曼zeta": "Riemann zeta function",
    "狄利克雷": "Dirichlet L-function character",
    "筛法": "sieve method",
    "椭圆曲线": "elliptic curve",
}


# Math symbols and LaTeX commands normalized into searchable English words,
# so that formula-style queries hit prose-style textbook chunks.
SYMBOL_MAP: dict[str, str] = {
    "≡": "congruent modulo congruence",
    "\\equiv": "congruent modulo congruence",
    "\\pmod": "modulo congruence",
    "\\bmod": "modulo",
    "\\mod": "modulo",
    "∣": "divides divisibility",
    "\\mid": "divides divisibility",
    "\\nmid": "does not divide",
    "\\gcd": "greatest common divisor gcd",
    "φ": "euler phi totient",
    "\\varphi": "euler phi totient",
    "\\phi": "euler phi totient",
    "ζ": "zeta function",
    "\\zeta": "zeta function",
    "\\sigma": "sigma divisor function",
    "\\tau": "tau number of divisors",
    "\\mu": "mobius function",
    "ℤ": "integers ring Z",
    "\\mathbb{Z}": "integers ring Z",
    "ℚ": "rational numbers field Q",
    "\\mathbb{Q}": "rational numbers field Q",
    "\\mathbb{F}": "finite field",
    "\\sqrt": "square root",
    "√": "square root",
    "\\sum": "sum series",
    "\\prod": "product",
    "\\infty": "infinity",
    "\\legendre": "legendre symbol",
    "\\binom": "binomial coefficient",
}


def normalize_symbols(text: str) -> str:
    """Return extra searchable words for math symbols / LaTeX commands in text."""
    additions: list[str] = []
    for symbol, words in SYMBOL_MAP.items():
        if symbol in text and words not in additions:
            additions.append(words)
    return " ".join(additions)


def expand_query(text: str) -> str:
    additions = [english for chinese, english in GLOSSARY.items() if chinese in text]
    symbols = normalize_symbols(text)
    if symbols:
        additions.append(symbols)
    return " ".join([text, *additions]).strip()


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", expand_query(text).lower())


def lexical_query(text: str) -> str:
    """Return an OR query containing only terms understood by English FTS."""
    unique_tokens = list(dict.fromkeys(_tokens(text)))
    return " OR ".join(unique_tokens)


def _client() -> OpenAI:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required for real embeddings")
    return OpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed texts with OpenAI text-embedding-3-small."""
    if not texts:
        return []
    client = _client()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = [expand_query(text)[:8000] for text in texts[start : start + BATCH_SIZE]]
        response = client.embeddings.create(
            model=settings.openai_embedding_model,
            input=batch,
            dimensions=DIMENSIONS,
        )
        ordered = sorted(response.data, key=lambda item: item.index)
        vectors.extend(item.embedding for item in ordered)
    if len(vectors) != len(texts):
        raise RuntimeError("Embedding API returned an unexpected number of vectors")
    return vectors


def embed(text: str) -> list[float]:
    return embed_texts([text])[0]


def as_pgvector(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in values) + "]"
