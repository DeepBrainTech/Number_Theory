import unittest

from app.research import (
    build_arxiv_search_query,
    normalize_literature_query,
    parse_arxiv_atom,
    parse_crossref,
    parse_oeis,
)


ARXIV_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1234.5678v1</id>
    <title>Bounded gaps between
      primes</title>
    <summary>  We prove something about prime gaps.  </summary>
    <published>2013-05-14T00:00:00Z</published>
    <author><name>Yitang Zhang</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/9999.0001v2</id>
    <title>Another paper</title>
    <summary>Second abstract.</summary>
    <published>2020-01-02T00:00:00Z</published>
    <author><name>A. Author</name></author>
    <author><name>B. Author</name></author>
  </entry>
</feed>
"""

OEIS_SAMPLE = {
    "results": [
        {
            "number": 45,
            "name": "Fibonacci numbers",
            "data": "0,1,1,2,3,5,8,13,21,34,55,89,144",
        }
    ]
}

CROSSREF_SAMPLE = {
    "message": {
        "items": [
            {
                "title": ["Primes in tuples I"],
                "author": [
                    {"given": "D. A.", "family": "Goldston"},
                    {"given": "J.", "family": "Pintz"},
                ],
                "issued": {"date-parts": [[2009, 9]]},
                "container-title": ["Annals of Mathematics"],
                "DOI": "10.4007/annals.2009.170.819",
                "URL": "https://doi.org/10.4007/annals.2009.170.819",
            }
        ]
    }
}


class ArxivParseTests(unittest.TestCase):
    def test_builds_math_nt_query(self) -> None:
        query = build_arxiv_search_query("2026年数论新论文")
        self.assertIn("cat:math.NT", query)
        self.assertIn("submittedDate", query)
        self.assertIn("2026", query)

    def test_builds_math_year_query_from_chinese(self) -> None:
        query = build_arxiv_search_query("2026年arXiv有哪些著名的数学论文")
        self.assertIn("cat:math", query)
        self.assertIn("submittedDate", query)
        self.assertIn("2026", query)

    def test_passes_through_arxiv_syntax(self) -> None:
        raw = "cat:math* AND submittedDate:[202601010000 TO 202612312359]"
        self.assertEqual(build_arxiv_search_query(raw), raw)


class LiteratureQueryTests(unittest.TestCase):
    def test_normalizes_chinese_math_year(self) -> None:
        query = normalize_literature_query("2026年arXiv有哪些著名的数学论文")
        self.assertIn("mathematics", query)
        self.assertIn("2026", query)

    def test_parses_entries(self) -> None:
        results = parse_arxiv_atom(ARXIV_SAMPLE, max_results=5)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["title"], "Bounded gaps between primes")
        self.assertEqual(results[0]["authors"], ["Yitang Zhang"])
        self.assertEqual(results[0]["published"], "2013-05-14")
        self.assertTrue(results[0]["url"].startswith("http://arxiv.org/abs/"))

    def test_respects_max_results(self) -> None:
        results = parse_arxiv_atom(ARXIV_SAMPLE, max_results=1)
        self.assertEqual(len(results), 1)


class OeisParseTests(unittest.TestCase):
    def test_parses_sequence(self) -> None:
        results = parse_oeis(OEIS_SAMPLE, max_results=3)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "A000045")
        self.assertEqual(results[0]["name"], "Fibonacci numbers")
        self.assertEqual(results[0]["terms"][:5], ["0", "1", "1", "2", "3"])

    def test_handles_list_payload(self) -> None:
        results = parse_oeis(OEIS_SAMPLE["results"], max_results=3)
        self.assertEqual(len(results), 1)

    def test_handles_empty(self) -> None:
        self.assertEqual(parse_oeis({"results": None}, max_results=3), [])


class CrossrefParseTests(unittest.TestCase):
    def test_parses_items(self) -> None:
        results = parse_crossref(CROSSREF_SAMPLE, max_results=5)
        self.assertEqual(len(results), 1)
        item = results[0]
        self.assertEqual(item["title"], "Primes in tuples I")
        self.assertEqual(item["authors"], ["D. A. Goldston", "J. Pintz"])
        self.assertEqual(item["year"], 2009)
        self.assertEqual(item["doi"], "10.4007/annals.2009.170.819")

    def test_handles_missing_message(self) -> None:
        self.assertEqual(parse_crossref({}, max_results=5), [])


if __name__ == "__main__":
    unittest.main()
