import unittest

from app.embedding import DIMENSIONS, expand_query, lexical_query


class EmbeddingTests(unittest.TestCase):
    def test_dimensions_match_openai_small(self) -> None:
        self.assertEqual(DIMENSIONS, 1536)

    def test_chinese_query_expansion(self) -> None:
        expanded = expand_query("如何使用欧几里得算法求最大公因数？")
        self.assertIn("Euclid algorithm", expanded)
        self.assertIn("greatest common divisor", expanded)
        fts_query = lexical_query("如何使用欧几里得算法求最大公因数？")
        self.assertNotIn("如何", fts_query)
        self.assertIn("euclid OR algorithm", fts_query)


if __name__ == "__main__":
    unittest.main()
