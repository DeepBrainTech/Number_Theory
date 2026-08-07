"""Math-aware query expansion: concept bridges, not just synonyms.

Two layers:
1. Rule bridges — curated regex triggers that map a phrasing of a problem to the
   theory that resolves it (e.g. "x^3 ≡ 2 (mod p)" → cubic reciprocity,
   Chebotarev). Always on, deterministic, testable.
2. Optional LLM expansion — asks the model for related concepts/theorems.
   Guarded by settings.query_expansion_llm and cached per query.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache

from openai import OpenAI

from .config import settings


# (trigger regex, concepts added to retrieval)
CONCEPT_BRIDGES: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), concepts)
    for pattern, concepts in [
        (
            r"x\s*\^\s*3|cubic\s+residue|三次剩余",
            ("cubic residue", "cubic reciprocity", "Kummer extension", "Chebotarev density"),
        ),
        (
            r"x\s*\^\s*2|quadratic\s+residue|平方剩余|二次剩余",
            ("quadratic residue", "Legendre symbol", "quadratic reciprocity", "Euler criterion"),
        ),
        (
            r"\bgcd\b|greatest\s+common|最大公|linear\s+combination",
            ("Euclidean algorithm", "Bezout identity", "extended Euclidean algorithm"),
        ),
        (
            r"simultaneous\s+congruence|system\s+of\s+congruence|同余方程组|剩余定理",
            ("Chinese Remainder Theorem", "coprime moduli", "ring isomorphism Z/mn"),
        ),
        (
            r"sum\s+of\s+two\s+squares|两个?平方数?之和",
            ("Fermat two squares theorem", "Gaussian integers", "norm form", "primes 1 mod 4"),
        ),
        (
            r"pell|佩尔",
            ("Pell equation", "continued fraction", "fundamental unit", "real quadratic field"),
        ),
        (
            r"primes?\s+in\s+arithmetic\s+progression|等差数列.*素数|素数.*等差",
            ("Dirichlet theorem primes arithmetic progressions", "Dirichlet character", "L-function"),
        ),
        (
            r"distribution\s+of\s+primes?|prime\s+counting|素数分布|素数定理",
            ("prime number theorem", "Riemann zeta function", "Chebyshev bounds", "logarithmic integral"),
        ),
        (
            r"fermat.{0,8}little|费马小定理",
            ("Fermat little theorem", "Euler theorem", "Euler totient", "order of element"),
        ),
        (
            r"primitive\s+root|原根",
            ("primitive root", "cyclic group of units", "multiplicative order", "Carmichael function"),
        ),
        (
            r"continued\s+fraction|连分数",
            ("continued fraction", "convergents", "best rational approximation", "Pell equation"),
        ),
        (
            r"perfect\s+number|完全数",
            ("perfect number", "Mersenne prime", "sigma divisor function", "Euclid Euler theorem"),
        ),
        (
            r"twin\s+primes?|孪生素数|prime\s+gaps?|素数间隔",
            ("twin prime conjecture", "bounded gaps between primes", "sieve method", "Zhang Maynard"),
        ),
        (
            r"partition|分拆",
            ("integer partition", "generating function", "Ramanujan congruences", "pentagonal number theorem"),
        ),
        (
            r"congruent\s+number|同余数",
            ("congruent number problem", "elliptic curve rank", "Tunnell theorem"),
        ),
        (
            r"diophantine|丢番图|integer\s+solutions?|整数解",
            ("Diophantine equation", "descent", "local global principle", "modular arithmetic obstruction"),
        ),
        (
            r"unique\s+factori[sz]ation|唯一分解",
            ("unique factorization", "fundamental theorem of arithmetic", "UFD", "class number"),
        ),
        (
            r"zeta|ζ|zeta\s+function|黎曼",
            ("Riemann zeta function", "Euler product", "Dirichlet series", "analytic continuation"),
        ),
        (
            r"order\s+of\s+.{0,20}\bmod\b|multiplicative\s+order|乘法阶|\b阶\b",
            ("multiplicative order", "Lagrange theorem group", "primitive root"),
        ),
        (
            r"irreducible|不可约",
            ("irreducible polynomial", "Eisenstein criterion", "Gauss lemma polynomials"),
        ),
    ]
)

LLM_EXPANSION_PROMPT = (
    "You are a number-theory retrieval planner. Given a question, list the "
    "mathematical concepts, theorems, and techniques most relevant to answering it — "
    "including deeper theory the question does not name explicitly. "
    'Output JSON only: {"concepts": ["...", "..."]} with at most 8 short English phrases.'
)


def rule_concepts(query: str) -> list[str]:
    """Deterministic concept bridges triggered by the query text."""
    found: list[str] = []
    for pattern, concepts in CONCEPT_BRIDGES:
        if pattern.search(query):
            for concept in concepts:
                if concept not in found:
                    found.append(concept)
    return found


@lru_cache(maxsize=256)
def _llm_concepts_cached(query: str) -> tuple[str, ...]:
    client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
    response = client.responses.create(
        model=settings.openai_model,
        instructions=LLM_EXPANSION_PROMPT,
        input=query,
    )
    text = (response.output_text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL)
    data = json.loads(text)
    concepts = data.get("concepts", []) if isinstance(data, dict) else []
    cleaned = tuple(
        item.strip() for item in concepts if isinstance(item, str) and 2 < len(item.strip()) < 80
    )
    return cleaned[:8]


def llm_concepts(query: str) -> list[str]:
    if not settings.openai_api_key or not settings.query_expansion_llm:
        return []
    try:
        return list(_llm_concepts_cached(query.strip()[:500]))
    except Exception:  # noqa: BLE001 - expansion must never break retrieval
        return []


def expand_math_concepts(query: str) -> list[str]:
    """Rule bridges plus optional LLM concepts, deduplicated, order-stable."""
    concepts = rule_concepts(query)
    for concept in llm_concepts(query):
        if concept.lower() not in {item.lower() for item in concepts}:
            concepts.append(concept)
    return concepts
