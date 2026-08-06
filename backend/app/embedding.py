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
