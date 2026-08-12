import unittest
from unittest.mock import patch

from app.auth import _cookie_flags, read_user_id, sign_user_id


class SessionCookieTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        token = sign_user_id("11111111-1111-1111-1111-111111111111")
        self.assertEqual(read_user_id(token), "11111111-1111-1111-1111-111111111111")

    def test_rejects_tampered_token(self) -> None:
        token = sign_user_id("11111111-1111-1111-1111-111111111111")
        self.assertIsNone(read_user_id(token + "x"))

    def test_samesite_none_forces_secure(self) -> None:
        with patch("app.auth.settings") as settings:
            settings.cookie_samesite = "none"
            settings.cookie_secure = False
            self.assertEqual(_cookie_flags(), ("none", True))

    def test_samesite_lax_respects_secure_flag(self) -> None:
        with patch("app.auth.settings") as settings:
            settings.cookie_samesite = "lax"
            settings.cookie_secure = False
            self.assertEqual(_cookie_flags(), ("lax", False))
            settings.cookie_secure = True
            self.assertEqual(_cookie_flags(), ("lax", True))


class GoogleAuthConfigTests(unittest.TestCase):
    def test_missing_client_id_is_service_unavailable(self) -> None:
        from fastapi import HTTPException

        from app.auth import verify_google_id_token

        with patch("app.auth.settings") as settings:
            settings.google_client_id = ""
            with self.assertRaises(HTTPException) as raised:
                verify_google_id_token("not-a-real-token")
            self.assertEqual(raised.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
