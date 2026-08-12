import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.auto_prove import (
    LoopState,
    RunStore,
    _parse_review,
    clamp_decision,
    extract_easy_proof,
    extract_section,
    extract_yaml,
    parse_difficulty,
    parse_regulator_decision,
    parse_verdict,
)
from app.prove_prompts import load_prompt, qed_prompt, skill_text


class ParseReviewTests(unittest.TestCase):
    def test_parses_json_fence(self) -> None:
        review = _parse_review(
            '```json\n{"pass": false, "issues": ["Missing base case"], '
            '"revision_instructions": "Add it."}\n```'
        )
        self.assertFalse(review["pass"])
        self.assertEqual(review["issues"], ["Missing base case"])
        self.assertEqual(review["revision_instructions"], "Add it.")

    def test_parses_json_after_markdown_report(self) -> None:
        review = _parse_review(
            "# Structural\nPhase 1 FAIL\n\n"
            '{"pass": false, "issues": ["Changed quantifier"], "revision_instructions": "Restore forall."}'
        )
        self.assertFalse(review["pass"])
        self.assertEqual(review["issues"], ["Changed quantifier"])

    def test_treats_unreadable_review_as_failure(self) -> None:
        review = _parse_review("This is not JSON")
        self.assertFalse(review["pass"])
        self.assertTrue(review["issues"])


class ParseHelpersTests(unittest.TestCase):
    def test_regulator_decision_heading(self) -> None:
        self.assertEqual(
            parse_regulator_decision("## Decision: REVISE_PLAN\n\nThe plan is missing a lemma."),
            "REVISE_PLAN",
        )
        self.assertEqual(parse_regulator_decision("Decision: REWRITE"), "REWRITE")
        self.assertEqual(parse_regulator_decision("no decision here"), "REVISE_PROOF")

    def test_qed_verdict(self) -> None:
        self.assertTrue(parse_verdict("DONE"))
        self.assertFalse(parse_verdict("CONTINUE"))

    def test_difficulty_heading(self) -> None:
        text = "# Difficulty Evaluation\n\n## Classification: Hard\n\n## Justification\nOpen."
        self.assertEqual(parse_difficulty(text), "hard")

    def test_extract_sections(self) -> None:
        text = "# Related Work\n\nTheorem A.\n\n# Easy Proof\n\nLet n be given.\n"
        self.assertEqual(extract_section(text, "Related Work"), "Theorem A.")
        self.assertEqual(extract_section(text, "Easy Proof"), "Let n be given.")

    def test_extract_easy_proof_prefers_heading(self) -> None:
        text = (
            "# Difficulty Evaluation\n\n## Classification: Easy\n\n"
            "# Easy Proof\n\n# 证明\n\nLet a=b=c=1/3.\n"
        )
        self.assertIn("Let a=b=c=1/3.", extract_easy_proof(text))

    def test_extract_easy_proof_accepts_proof_file_heading(self) -> None:
        text = (
            "## Classification: Easy\n\n"
            "## `proof_file`\n\n# 证明\n\nBecause a+b+c=1, done.\n"
        )
        proof = extract_easy_proof(text)
        self.assertIn("Because a+b+c=1", proof)
        self.assertIn("# 证明", proof)

    def test_extract_yaml_fence(self) -> None:
        text = "Here is the plan:\n```yaml\nsteps: []\n```\n"
        self.assertEqual(extract_yaml(text), "steps: []")

    def test_clamp_escalates_when_budget_exhausted(self) -> None:
        limits = {"max_proof_attempts": 1, "max_revisions": 1, "max_decompositions": 1}
        state = LoopState(attempt=1, revision=1, proof=1)
        self.assertEqual(clamp_decision("REVISE_PROOF", state, limits), "FINAL")
        limits = {"max_proof_attempts": 3, "max_revisions": 2, "max_decompositions": 2}
        self.assertEqual(clamp_decision("REVISE_PROOF", state, limits), "REVISE_PROOF")
        self.assertEqual(clamp_decision("REVISE_PLAN", state, limits), "REVISE_PLAN")


class PromptLoadTests(unittest.TestCase):
    def test_verbatim_qed_prompts_are_available(self) -> None:
        self.assertIn("Verdict Task: Decomposition Proof Verification", qed_prompt("decomposition-prover/verdict_proof.md"))
        self.assertIn("Proof Effort Summary Task", qed_prompt("proof_effort_summary.md"))

    def test_skill_and_role_prompts_load(self) -> None:
        self.assertIn("Cardinal Rule", skill_text())
        for name in (
            "literature_survey.md",
            "decomposition.md",
            "prover.md",
            "structural.md",
            "detailed.md",
            "regulator.md",
        ):
            body = load_prompt(name)
            self.assertGreater(len(body), 200, name)


class RunStoreTests(unittest.TestCase):
    def test_writes_nested_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.auto_prove.settings") as settings:
                settings.auto_prove_runs_dir = Path(tmp)
                run_id, store = RunStore.create("testrun")
                self.assertEqual(run_id, "testrun")
                store.write("attempt_1/revision_1/proof_1/proof.md", "QED.")
                self.assertEqual(store.read("attempt_1/revision_1/proof_1/proof.md").strip(), "QED.")
                store.log("hello")
                self.assertIn("hello", (store.root / "log.txt").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
