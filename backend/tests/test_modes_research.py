import unittest

from app.chat import tools_for
from app.modes import enforce_research_structure, validate_research_sections
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
        for mode in ("teach", "solve", "research"):
            names = {tool["name"] for tool in tools_for(mode)}
            self.assertIn("sage_calculate", names)
            self.assertTrue(literature.issubset(names))


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
