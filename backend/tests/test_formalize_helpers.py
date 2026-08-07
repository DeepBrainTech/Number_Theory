import unittest

from app.formalize import extract_theorem_statement


class ExtractStatementTests(unittest.TestCase):
    def test_extracts_theorem_before_by(self) -> None:
        code = (
            "import Mathlib.Tactic\n\n"
            "theorem n_sq_add_n_even (n : ℕ) : Even (n ^ 2 + n) := by\n"
            "  sorry\n"
        )
        statement = extract_theorem_statement(code)
        self.assertIsNotNone(statement)
        assert statement is not None
        self.assertTrue(statement.startswith("theorem n_sq_add_n_even"))
        self.assertIn("Even", statement)

    def test_returns_none_without_theorem(self) -> None:
        self.assertIsNone(extract_theorem_statement("def foo := 1"))


if __name__ == "__main__":
    unittest.main()
