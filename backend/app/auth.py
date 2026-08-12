"""Google sign-in and signed session cookies."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request, Response
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import settings
from .db import connection

COOKIE_NAME = "nt_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret, salt="nt-session")


def sign_user_id(user_id: str) -> str:
    return _serializer().dumps({"uid": user_id})


def read_user_id(token: str) -> str | None:
    try:
        data = _serializer().loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return None
    uid = data.get("uid") if isinstance(data, dict) else None
    return str(uid) if uid else None


def public_user(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "email": row.get("email"),
        "name": row.get("name"),
        "picture": row.get("picture"),
    }


def get_user(user_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT id::text AS id, email, name, picture
            FROM users
            WHERE id = %s::uuid
            """,
            (user_id,),
        ).fetchone()
    return public_user(dict(row)) if row else None


def upsert_google_user(*, sub: str, email: str | None, name: str | None, picture: str | None) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute(
            """
            INSERT INTO users (google_sub, email, name, picture)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (google_sub) DO UPDATE SET
                email = EXCLUDED.email,
                name = EXCLUDED.name,
                picture = EXCLUDED.picture,
                updated_at = NOW()
            RETURNING id::text AS id, email, name, picture
            """,
            (sub, email, name, picture),
        ).fetchone()
        conn.commit()
    return public_user(dict(row))


def verify_google_id_token(token: str) -> dict[str, Any]:
    if not settings.google_client_id:
        raise HTTPException(status_code=503, detail="Google login is not configured.")
    try:
        info = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            settings.google_client_id,
        )
    except Exception as exc:  # noqa: BLE001 - invalid tokens become 401
        raise HTTPException(status_code=401, detail="Invalid Google token.") from exc
    issuer = info.get("iss")
    if issuer not in {"accounts.google.com", "https://accounts.google.com"}:
        raise HTTPException(status_code=401, detail="Invalid Google token.")
    if not info.get("sub"):
        raise HTTPException(status_code=401, detail="Invalid Google token.")
    return info


def _cookie_flags() -> tuple[str, bool]:
    """Return (samesite, secure). SameSite=None always implies Secure."""
    samesite = settings.cookie_samesite if settings.cookie_samesite in {"lax", "strict", "none"} else "lax"
    secure = settings.cookie_secure or samesite == "none"
    return samesite, secure


def set_session_cookie(response: Response, user_id: str) -> None:
    samesite, secure = _cookie_flags()
    response.set_cookie(
        COOKIE_NAME,
        sign_user_id(user_id),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite=samesite,  # type: ignore[arg-type]
        secure=secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    samesite, secure = _cookie_flags()
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        secure=secure,
        httponly=True,
        samesite=samesite,  # type: ignore[arg-type]
    )


def current_user(request: Request) -> dict[str, Any]:
    token = request.cookies.get(COOKIE_NAME)
    user_id = read_user_id(token) if token else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Not signed in.")
    user = get_user(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Not signed in.")
    return user
