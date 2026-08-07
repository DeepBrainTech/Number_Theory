import unittest

from app.ingestion.catalog import SKIPPED_PDFS, get_book, list_books
from app.ingestion.chunking import classify, split_long_paragraph
from app.ingestion.profiles import get_profile, resolve_profile
from app.modes import resolve_answer_mode, system_prompt_for


class ChunkingTests(unittest.TestCase):
    def test_classify_theorem_and_proof(self) -> None:
        self.assertEqual(classify("Theorem 2.1. Something.")[0], "theorem")
        self.assertEqual(classify("Proof. Immediate.")[0], "proof")
        self.assertEqual(classify("Definition. A monic polynomial...")[0], "definition")
        self.assertEqual(classify("定理 1. 素数无穷。")[0], "theorem")

    def test_split_keeps_short_paragraph(self) -> None:
        text = "A short paragraph stays intact."
        self.assertEqual(split_long_paragraph(text), [text])

    def test_hill_profiles_cover_all_chapters(self) -> None:
        book = get_book("hill")
        self.assertEqual(len(book.chapters or ()), 5)
        profile = get_profile("hill-ch2")
        self.assertEqual(profile.start_page, 42)
        self.assertEqual(profile.end_page, 67)
        self.assertEqual(profile.printed_page(42), 27)

    def test_resolve_profile_by_pages(self) -> None:
        profile = resolve_profile(profile_key=None, start_page=16, end_page=41)
        self.assertEqual(profile.key, "hill-ch1")

    def test_skips_draft_and_scans(self) -> None:
        names = {item.filename for item in SKIPPED_PDFS}
        self.assertIn("Multiplicative number theory.pdf", names)
        self.assertIn("037_解析数论基础.pdf", names)
        keys = {book.key for book in list_books()}
        self.assertIn("hill", keys)
        self.assertIn("mv1", keys)
        self.assertNotIn("granville-draft", keys)


class ModeTests(unittest.TestCase):
    def test_explicit_mode_wins(self) -> None:
        self.assertEqual(resolve_answer_mode("prove that 2 is prime", "teach"), "teach")
        self.assertEqual(resolve_answer_mode("what is a ring?", "solve"), "solve")

    def test_auto_detects_solve_and_teach(self) -> None:
        self.assertEqual(resolve_answer_mode("Prove that gcd(a,b)=gcd(b,a).", "auto"), "solve")
        self.assertEqual(resolve_answer_mode("Explain Euclid’s algorithm.", "auto"), "teach")
        self.assertEqual(resolve_answer_mode("多项式环是什么？", "auto"), "teach")

    def test_auto_detects_research(self) -> None:
        self.assertEqual(
            resolve_answer_mode("What is known about the twin prime conjecture?", "auto"),
            "research",
        )
        self.assertEqual(
            resolve_answer_mode("给我孪生素数猜想的研究现状综述", "auto"),
            "research",
        )
        self.assertEqual(resolve_answer_mode("anything at all", "research"), "research")

    def test_prompts_differ(self) -> None:
        teach = system_prompt_for("teach")
        solve = system_prompt_for("solve")
        research = system_prompt_for("research")
        self.assertIn("teaching mode", teach)
        self.assertIn("problem-solving mode", solve)
        self.assertIn("research mode", research)
        self.assertIn("## Known results", research)
        self.assertIn("## Conjectures", research)
        self.assertEqual(len({teach, solve, research}), 3)

    def test_teach_depth_changes_prompt(self) -> None:
        hint = system_prompt_for("teach", "hint")
        full = system_prompt_for("teach", "full")
        self.assertIn("HINT ONLY", hint)
        self.assertIn("FULL SOLUTION", full)
        self.assertNotEqual(hint, full)


if __name__ == "__main__":
    unittest.main()
