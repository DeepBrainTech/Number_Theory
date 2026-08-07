import unittest

from app.ingestion.manifest import (
    DEFAULT_DEPLOY_TARGETS,
    expand_manifest,
    expand_target,
)


class DeployManifestTests(unittest.TestCase):
    def test_default_targets_resolve(self) -> None:
        from pathlib import Path

        pdf_root = Path(__file__).resolve().parents[2] / "pdf"
        units = expand_manifest(pdf_root, DEFAULT_DEPLOY_TARGETS)
        keys = {unit.profile.key for unit in units}
        hill_pdf = pdf_root / "1017984325-Introduction-to-Number-Theory-2026 (1).pdf"
        if hill_pdf.is_file():
            self.assertIn("hill-ch1", keys)
            self.assertIn("hill-ch5", keys)
        if keys:
            self.assertTrue(all(k.endswith("-body") or "-ch" in k for k in keys))

    def test_manifest_has_expected_books_when_pdfs_present(self) -> None:
        from pathlib import Path

        pdf_root = Path(__file__).resolve().parents[2] / "pdf"
        units = expand_manifest(pdf_root, DEFAULT_DEPLOY_TARGETS)
        if not units:
            self.skipTest("No PDFs present")
        book_keys = {unit.book.key for unit in units}
        self.assertIn("hill", book_keys)
        self.assertNotIn("wustholz", book_keys)

    def test_profile_target_without_pdf_is_empty(self) -> None:
        from pathlib import Path

        units = expand_target(Path("/nonexistent/pdf"), "profile:hill-ch1")
        self.assertEqual(units, [])

    def test_book_target_expands_chapters(self) -> None:
        from pathlib import Path

        pdf_root = Path(__file__).resolve().parents[2] / "pdf"
        units = expand_target(pdf_root, "book:hill")
        if not units:
            self.skipTest("Hill PDF not present")
        keys = {unit.profile.key for unit in units}
        self.assertIn("hill-ch1", keys)
        self.assertIn("hill-ch5", keys)


if __name__ == "__main__":
    unittest.main()
