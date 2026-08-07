import unittest

from app.retrieval import BLOCK_WEIGHTS, STRUCTURED_BLOCK_TYPES, fuse_channels


def row(chunk_id: int, block_type: str = "exposition", **overrides):
    base = {
        "id": chunk_id,
        "block_type": block_type,
        "heading": None,
        "content": f"chunk {chunk_id}",
        "pdf_page": 1,
        "printed_page": 1,
        "parent_ordinal": None,
        "raw_score": 1.0,
    }
    base.update(overrides)
    return base


class FusionTests(unittest.TestCase):
    def test_multi_channel_hit_outranks_single_channel(self) -> None:
        shared = row(1)
        only_lexical = row(2)
        results = fuse_channels(
            [([shared, only_lexical], 1.0), ([shared], 1.0)],
            limit=2,
        )
        self.assertEqual(results[0]["chunk_id"], 1)

    def test_block_type_boost_prefers_theorem_over_exposition(self) -> None:
        theorem = row(1, "theorem")
        exposition = row(2, "exposition")
        # Same rank in the same channel order → boost decides.
        results = fuse_channels([([exposition, theorem], 1.0), ([theorem, exposition], 1.0)], limit=2)
        self.assertEqual(results[0]["block_type"], "theorem")

    def test_channel_weight_matters(self) -> None:
        heavy = row(1)
        light = row(2)
        results = fuse_channels([([heavy], 2.0), ([light], 0.5)], limit=2)
        self.assertEqual(results[0]["chunk_id"], 1)

    def test_limit_and_shape(self) -> None:
        rows = [row(index) for index in range(10)]
        results = fuse_channels([(rows, 1.0)], limit=3)
        self.assertEqual(len(results), 3)
        for item in results:
            self.assertIn("chunk_id", item)
            self.assertIn("score", item)
            self.assertIn("parent_ordinal", item)

    def test_structured_types_have_boost(self) -> None:
        for block_type in STRUCTURED_BLOCK_TYPES:
            self.assertGreater(BLOCK_WEIGHTS[block_type], 1.0)


if __name__ == "__main__":
    unittest.main()
