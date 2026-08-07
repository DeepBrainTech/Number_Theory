import unittest

from app.gating import LEVEL_LABELS, _assign_level, _heuristic_premise_flags


class GatingTests(unittest.TestCase):
    def test_lean_aligned_reaches_v4(self) -> None:
        level, notes, blocked = _assign_level(
            premise_ok=True,
            conflict=False,
            sage_ok=False,
            lean_ok=True,
            lean_aligned=True,
            critic_ok=True,
        )
        self.assertEqual(level, "V4")
        self.assertFalse(blocked)
        self.assertTrue(any("matches the question" in note for note in notes))

    def test_lean_misaligned_does_not_claim_v4(self) -> None:
        level, notes, blocked = _assign_level(
            premise_ok=True,
            conflict=False,
            sage_ok=False,
            lean_ok=True,
            lean_aligned=False,
            critic_ok=True,
        )
        self.assertEqual(level, "V1")
        self.assertFalse(blocked)
        self.assertTrue(any("not V4" in note for note in notes))

    def test_conflict_blocks_as_v0(self) -> None:
        level, notes, blocked = _assign_level(
            premise_ok=True,
            conflict=True,
            sage_ok=True,
            lean_ok=False,
            lean_aligned=None,
            critic_ok=False,
        )
        self.assertEqual(level, "V0")
        self.assertTrue(blocked)
        self.assertTrue(any("conflicts" in note.lower() for note in notes))

    def test_sage_maps_to_v2(self) -> None:
        level, _, blocked = _assign_level(
            premise_ok=True,
            conflict=False,
            sage_ok=True,
            lean_ok=False,
            lean_aligned=None,
            critic_ok=False,
        )
        self.assertEqual(level, "V2")
        self.assertFalse(blocked)

    def test_independent_critique_reaches_v3(self) -> None:
        level, notes, blocked = _assign_level(
            premise_ok=True,
            conflict=False,
            sage_ok=False,
            lean_ok=False,
            lean_aligned=None,
            critic_ok=True,
        )
        self.assertEqual(level, "V3")
        self.assertFalse(blocked)
        self.assertTrue(any("independent" in note.lower() for note in notes))

    def test_critique_plus_sage_still_v3(self) -> None:
        level, _, _ = _assign_level(
            premise_ok=True,
            conflict=False,
            sage_ok=True,
            lean_ok=False,
            lean_aligned=None,
            critic_ok=True,
        )
        self.assertEqual(level, "V3")

    def test_premise_only_is_v1_without_critique(self) -> None:
        level, _, _ = _assign_level(
            premise_ok=True,
            conflict=False,
            sage_ok=False,
            lean_ok=False,
            lean_aligned=None,
            critic_ok=False,
        )
        self.assertEqual(level, "V1")

    def test_labels_cover_all_levels(self) -> None:
        for key in ("retrieval_only", "V0", "V1", "V2", "V3", "V4"):
            self.assertIn(key, LEVEL_LABELS)

    def test_heuristic_flags_universal_claims(self) -> None:
        notes = _heuristic_premise_flags("证明素数无穷", "素数一定有某种分布。")
        self.assertTrue(notes)


if __name__ == "__main__":
    unittest.main()
