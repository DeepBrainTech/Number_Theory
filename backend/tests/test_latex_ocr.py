import unittest

from app.latex_ocr import decode_image, parse_latex_payload, wrap_latex


class LatexOcrTests(unittest.TestCase):
    def test_parse_inline_payload(self) -> None:
        data = parse_latex_payload(
            '{"latex":"x \\\\equiv 2 \\\\pmod 7","display":false,"confidence":"high","notes":[]}'
        )
        self.assertEqual(data["latex"], "x \\equiv 2 \\pmod 7")
        self.assertFalse(data["display"])
        self.assertEqual(data["confidence"], "high")

    def test_wrap_inline_and_display(self) -> None:
        self.assertEqual(wrap_latex("n^2", display=False), "$n^2$")
        self.assertIn("$$\n", wrap_latex("n^2", display=True))

    def test_decode_data_url(self) -> None:
        import base64

        raw = b"fakepng"
        url = f"data:image/png;base64,{base64.b64encode(raw).decode()}"
        decoded, media = decode_image(url)
        self.assertEqual(decoded, raw)
        self.assertEqual(media, "image/png")

    def test_rejects_invalid_base64(self) -> None:
        with self.assertRaises(ValueError):
            decode_image("data:image/png;base64,%%%not-valid%%%")


if __name__ == "__main__":
    unittest.main()
