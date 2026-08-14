import unittest
from types import SimpleNamespace

from app.chat import collect_hosted_tool_results, tools_for
from app.modes import enforce_research_structure, resolve_answer_mode, system_prompt_for, validate_research_sections
from app.research import dedupe_literature, parse_semantic_scholar


class ToolsForTests(unittest.TestCase):
    def test_all_modes_include_literature_tools(self) -> None:
        literature = {
            "arxiv_search",
            "crossref_search",
            "semantic_scholar_search",
            "literature_search",
            "oeis_search",
        }
        for mode in ("general", "teach", "solve", "physics", "research"):
            tools = tools_for(mode)
            names = {tool["name"] for tool in tools if "name" in tool}
            types = {tool["type"] for tool in tools}
            self.assertIn("sage_calculate", names)
            self.assertTrue(literature.issubset(names))
            self.assertIn("web_search", types)


class PhysicsModeTests(unittest.TestCase):
    def test_requested_physics_mode_is_preserved(self) -> None:
        self.assertEqual(resolve_answer_mode("A block slides down an incline.", "physics"), "physics")

    def test_auto_detects_physics_questions(self) -> None:
        self.assertEqual(resolve_answer_mode("一个质量为 2 kg 的物体受到恒力后加速度是多少？"), "physics")

    def test_physics_prompt_requires_units_and_dimensional_checks(self) -> None:
        prompt = system_prompt_for("physics")
        self.assertIn("Known quantities & units", prompt)
        self.assertIn("check dimensions", prompt)


class GeneralModeTests(unittest.TestCase):
    def test_auto_uses_general_for_concept_questions(self) -> None:
        self.assertEqual(resolve_answer_mode("What is number theory?"), "general")

    def test_auto_uses_teach_for_explicit_teaching_request(self) -> None:
        self.assertEqual(resolve_answer_mode("Teach me number theory step by step."), "teach")

    def test_general_prompt_has_no_forced_lesson_template(self) -> None:
        prompt = system_prompt_for("general")
        self.assertIn("do not impose a lesson plan", prompt)
        self.assertNotIn("Teaching template", prompt)


class HostedWebSearchTests(unittest.TestCase):
    def test_collects_query_and_citations(self) -> None:
        response = SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="web_search_call",
                    status="completed",
                    action=SimpleNamespace(query="twin primes 2026"),
                ),
                SimpleNamespace(
                    type="message",
                    content=[
                        SimpleNamespace(
                            annotations=[
                                SimpleNamespace(
                                    type="url_citation",
                                    url="https://arxiv.org/abs/1234",
                                    title="A paper",
                                )
                            ]
                        )
                    ],
                ),
            ]
        )
        results = collect_hosted_tool_results(response)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["tool"], "web_search")
        self.assertTrue(results[0]["ok"])
        self.assertEqual(results[0]["query"], "twin primes 2026")
        self.assertEqual(results[0]["citations"][0]["url"], "https://arxiv.org/abs/1234")


class ResearchStructureTests(unittest.TestCase):
    def test_complete_outline_passes(self) -> None:
        answer = (
            "## Known results\nA\n"
            "## Derivation\nB\n"
            "## Computational evidence\nC\n"
            "## Conjectures\nD\n"
            "## Gaps & next experiments\nE\n"
        )
        ok, missing = validate_research_sections(answer)
        self.assertTrue(ok)
        self.assertEqual(missing, [])

    def test_missing_sections_flagged(self) -> None:
        answer = "## Known results\nOnly this.\n"
        ok, missing = validate_research_sections(answer)
        self.assertFalse(ok)
        self.assertIn("## Conjectures", missing)
        patched, notes = enforce_research_structure(answer)
        self.assertTrue(patched.startswith("[Research structure check]"))
        self.assertTrue(any("Missing research section" in note for note in notes))


class LiteratureDedupTests(unittest.TestCase):
    def test_dedupe_by_doi_and_title(self) -> None:
        records = [
            {"title": "Twin Primes", "doi": "10.1/abc", "source": "arXiv"},
            {"title": "Twin Primes", "doi": "10.1/abc", "source": "Crossref"},
            {"title": "Twin  Primes!", "doi": None, "source": "S2"},
            {"title": "Bounded Gaps", "doi": "10.2/xyz", "source": "S2"},
        ]
        unique = dedupe_literature(records)
        self.assertEqual(len(unique), 2)
        self.assertEqual(unique[0]["doi"], "10.1/abc")
        self.assertEqual(unique[1]["title"], "Bounded Gaps")

    def test_parse_semantic_scholar(self) -> None:
        payload = {
            "data": [
                {
                    "paperId": "abc",
                    "title": "Gaps between primes",
                    "authors": [{"name": "A. Author"}],
                    "year": 2014,
                    "abstract": "We prove...",
                    "externalIds": {"DOI": "10.1/xyz"},
                    "citationCount": 100,
                    "url": "https://example.com/p",
                }
            ]
        }
        results = parse_semantic_scholar(payload, max_results=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["doi"], "10.1/xyz")
        self.assertEqual(results[0]["source"], "Semantic Scholar")


if __name__ == "__main__":
    unittest.main()
