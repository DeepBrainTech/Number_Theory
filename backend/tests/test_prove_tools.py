import unittest
from unittest.mock import patch

from app.prove_prompts import qed_prompt
from app.prove_tools import html_to_text, validate_public_http_url


class HtmlTextTests(unittest.TestCase):
    def test_strips_script_and_tags(self) -> None:
        text = html_to_text(
            "<html><head><script>secret()</script></head>"
            "<body><h1>Theorem 1</h1><p>Let n be prime.</p></body></html>"
        )
        self.assertIn("Theorem 1", text)
        self.assertIn("Let n be prime.", text)
        self.assertNotIn("secret", text)


class QedPromptTests(unittest.TestCase):
    def test_fills_file_paths_and_keeps_runtime_tools(self) -> None:
        text = qed_prompt(
            "literature_survey.md",
            {
                "problem_file": "problem.md",
                "related_info_dir": "related_info",
                "proof_file": "proof.md",
                "error_file": "error.log",
                "output_dir": ".",
            },
        )
        self.assertIn("problem.md", text)
        self.assertNotIn("{problem_file}", text)
        self.assertIn("read_run_file", text)
        self.assertIn("fetch_url", text)


class PublicUrlTests(unittest.TestCase):
    def test_rejects_non_http(self) -> None:
        with self.assertRaises(ValueError):
            validate_public_http_url("file:///etc/passwd")
        with self.assertRaises(ValueError):
            validate_public_http_url("")

    def test_rejects_localhost(self) -> None:
        with self.assertRaises(ValueError):
            validate_public_http_url("http://localhost/admin")
        with self.assertRaises(ValueError):
            validate_public_http_url("http://127.0.0.1/")

    def test_accepts_public_host_shape(self) -> None:
        with patch("app.prove_tools.socket.getaddrinfo", return_value=[(0, 0, 0, "", ("1.1.1.1", 443))]):
            url = validate_public_http_url("https://arxiv.org/abs/1234.5678")
        self.assertTrue(url.startswith("https://arxiv.org/"))


if __name__ == "__main__":
    unittest.main()
