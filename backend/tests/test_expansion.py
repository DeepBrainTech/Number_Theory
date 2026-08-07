import unittest

from app.embedding import expand_query, normalize_symbols
from app.expansion import rule_concepts


class RuleConceptTests(unittest.TestCase):
    def test_cubic_residue_bridges_to_reciprocity(self) -> None:
        concepts = rule_concepts("For which primes p does x^3 ≡ 2 (mod p) have a solution?")
        self.assertIn("cubic reciprocity", concepts)
        self.assertIn("Chebotarev density", concepts)

    def test_gcd_bridges_to_bezout(self) -> None:
        concepts = rule_concepts("Express gcd(391, 299) as a linear combination.")
        self.assertIn("Bezout identity", concepts)

    def test_chinese_query_triggers_bridges(self) -> None:
        concepts = rule_concepts("哪些素数可以写成两个平方数之和？")
        self.assertIn("Fermat two squares theorem", concepts)
        self.assertIn("Gaussian integers", concepts)

    def test_unrelated_query_yields_nothing(self) -> None:
        self.assertEqual(rule_concepts("hello world"), [])

    def test_deduplicates_across_bridges(self) -> None:
        concepts = rule_concepts("Pell equation and continued fraction expansion")
        self.assertEqual(len(concepts), len(set(concepts)))


class SymbolNormalizationTests(unittest.TestCase):
    def test_congruence_symbol(self) -> None:
        words = normalize_symbols("solve x ≡ 3 (mod 7)")
        self.assertIn("congruent", words)

    def test_latex_commands(self) -> None:
        words = normalize_symbols(r"compute $\gcd(a,b)$ where $a \equiv b \pmod{n}$")
        self.assertIn("greatest common divisor", words)
        self.assertIn("modulo", words)

    def test_euler_phi_symbol(self) -> None:
        words = normalize_symbols(r"evaluate $\varphi(100)$")
        self.assertIn("totient", words)

    def test_expand_query_includes_symbols_and_glossary(self) -> None:
        expanded = expand_query("求 φ(100)，即欧拉函数")
        self.assertIn("euler phi totient", expanded)
        self.assertIn("Euler totient phi", expanded)


if __name__ == "__main__":
    unittest.main()
