import unittest

from app.auto_prove import _parse_review


class ParseReviewTests(unittest.TestCase):
    def test_parses_json_fence(self) -> None:
        review = _parse_review(
            '```json\n{"pass": false, "issues": ["Missing base case"], '
            '"revision_instructions": "Add it."}\n```'
        )
        self.assertFalse(review["pass"])
        self.assertEqual(review["issues"], ["Missing base case"])
        self.assertEqual(review["revision_instructions"], "Add it.")

    def test_treats_unreadable_review_as_failure(self) -> None:
        review = _parse_review("This is not JSON")
        self.assertFalse(review["pass"])
        self.assertTrue(review["issues"])


if __name__ == "__main__":
    unittest.main()
