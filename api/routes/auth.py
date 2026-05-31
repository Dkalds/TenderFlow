"""Session auth endpoints for the web frontend.

Provides cookie-based session authentication (httpOnly + Secure + SameSite=Lax)
with CSRF protection. Complements the existing X-API-Key auth for machine clients.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.parse
from typing import Any

import httpx
from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, EmailStr

from config import settings
from db.users import (
    get_or_create_oauth_user,
    get_user_by_email,
    get_user_by_id,
    is_admin,
    log_access,
)
from observability.logging import get_logger
from shared.auth_core import (
    generate_oauth_state,
    generate_pkce_pair,
    get_signing_key,
    oauth_email_allowed,
    oauth_email_is_admin,
    validate_google_id_token,
    verify_oauth_state,
    verify_password,
)

log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_SESSION_COOKIE = "session"
_CSRF_COOKIE = "csrf_token"
_PKCE_COOKIE = "pkce_verifier"
_SESSION_MAX_AGE = 86400  # 24h


# ---------------------------------------------------------------------------
# Session payload helpers (HMAC-SHA256 signed JSON)
# ---------------------------------------------------------------------------


def _sign_session(payload: dict[str, Any]) -> str:
    """Serialize *payload* to JSON and sign with HMAC-SHA256.

    Format: ``{base64url_payload}.{hex_signature}``
    """
    import base64

    data = json.dumps(payload, separators=(",", ":")).encode()
    b64 = base64.urlsafe_b64encode(data).decode()
    sig = hmac.new(get_signing_key(), data, hashlib.sha256).hexdigest()
    return f"{b64}.{sig}"


def _verify_session(token: str) -> dict[str, Any] | None:
    """Verify signature and decode the session payload. Returns None on failure."""
    import base64

    parts = token.split(".", 1)
    if len(parts) != 2:
        return None
    b64, sig = parts
    try:
        data = base64.urlsafe_b64decode(b64)
    except Exception:
        return None
    expected = hmac.new(get_signing_key(), data, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload: dict[str, Any] = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    # Check expiry
    if payload.get("exp", 0) < time.time():
        return None
    return payload


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------


def _is_secure() -> bool:
    return settings.ENV in ("prod", "staging")


def _set_session_cookie(response: Response, payload: dict[str, Any]) -> str:
    """Set session and CSRF cookies. Returns the CSRF token."""
    csrf_token = os.urandom(16).hex()
    payload["csrf"] = csrf_token
    payload["exp"] = int(time.time()) + _SESSION_MAX_AGE
    signed = _sign_session(payload)
    secure = _is_secure()
    response.set_cookie(
        _SESSION_COOKIE,
        signed,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=_SESSION_MAX_AGE,
        path="/",
    )
    response.set_cookie(
        _CSRF_COOKIE,
        csrf_token,
        httponly=False,
        secure=secure,
        samesite="lax",
        max_age=_SESSION_MAX_AGE,
        path="/",
    )
    return csrf_token


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(_SESSION_COOKIE, path="/")
    response.delete_cookie(_CSRF_COOKIE, path="/")


# ---------------------------------------------------------------------------
# Dependency: current session user
# ---------------------------------------------------------------------------


def get_current_session_user(
    session: str | None = Cookie(default=None, alias=_SESSION_COOKIE),
) -> dict[str, Any]:
    """Dependency that reads the session cookie and returns user info.

    Raises 401 if the session is missing, invalid, or expired.
    """
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No session")
    payload = _verify_session(session)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    user_id: int | None = payload.get("user_id")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session payload"
        )
    user = get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return {
        "user_id": user["id"],
        "email": user.get("email"),
        "display_name": user.get("display_name"),
        "is_admin": bool(user.get("is_admin")),
        "csrf": payload.get("csrf"),
    }


# ---------------------------------------------------------------------------
# CSRF validation dependency for mutations
# ---------------------------------------------------------------------------


def require_csrf(
    user: dict[str, Any] = Depends(get_current_session_user),
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> dict[str, Any]:
    """Validates that X-CSRF-Token header matches the value stored in the session."""
    if not x_csrf_token or not hmac.compare_digest(x_csrf_token, user.get("csrf", "")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token mismatch")
    return user


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    """Credentials for email/password login."""

    email: EmailStr
    password: str


class UserInfo(BaseModel):
    """Public user info returned by auth endpoints."""

    user_id: int
    email: str | None = None
    display_name: str | None = None
    is_admin: bool = False


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/login", response_model=UserInfo)
def login(body: LoginRequest, response: Response) -> UserInfo:
    """Authenticate with email + password, set session cookie."""
    user = get_user_by_email(body.email)
    if not user:
        log.warning("login_failed", email=body.email, reason="user_not_found")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    pw_hash: str = user.get("password_hash", "") or ""
    if not verify_password(body.password, pw_hash):
        log.warning("login_failed", email=body.email, reason="bad_password")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    _set_session_cookie(response, {"user_id": user["id"]})
    log_access(auth_method="password", user_id=user["id"], email=body.email)
    log.info("login_success", user_id=user["id"], email=body.email)

    return UserInfo(
        user_id=user["id"],
        email=user.get("email"),
        display_name=user.get("display_name"),
        is_admin=is_admin(user["id"]),
    )


# ---------------------------------------------------------------------------
# Dev-only quick login (no password required)
# ---------------------------------------------------------------------------

if settings.ENV == "dev":

    @router.post("/dev-login", response_model=UserInfo)
    def dev_login(response: Response) -> UserInfo:
        """DEV ONLY: Set session cookie for user_id=1 without credentials.

        This endpoint is only available when ENV=dev. It allows quick
        login during local development without requiring Google OAuth
        or password setup.
        """
        user = get_user_by_id(1)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dev user (id=1) not found",
            )
        _set_session_cookie(response, {"user_id": user["id"]})
        log_access(auth_method="dev_login", user_id=user["id"], email=user.get("email", ""))
        log.info("dev_login_success", user_id=user["id"])
        return UserInfo(
            user_id=user["id"],
            email=user.get("email"),
            display_name=user.get("display_name"),
            is_admin=is_admin(user["id"]),
        )


@router.get("/me", response_model=UserInfo)
def me(user: dict[str, Any] = Depends(get_current_session_user)) -> UserInfo:
    """Return info about the currently authenticated user."""
    return UserInfo(
        user_id=user["user_id"],
        email=user.get("email"),
        display_name=user.get("display_name"),
        is_admin=user.get("is_admin", False),
    )


@router.post("/logout")
def logout(response: Response) -> dict[str, str]:
    """Clear session and CSRF cookies."""
    _clear_session_cookies(response)
    return {"detail": "Logged out"}


# ---------------------------------------------------------------------------
# Google OAuth with PKCE
# ---------------------------------------------------------------------------


@router.get("/oauth/google/authorize")
def google_authorize(response: Response) -> dict[str, str]:
    """Redirect URL for Google OAuth with PKCE.

    Returns JSON with ``authorization_url`` so the SPA can redirect the user.
    Also sets a signed cookie with the PKCE verifier.
    """
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Google OAuth not configured",
        )

    state = generate_oauth_state()
    verifier, challenge = generate_pkce_pair()

    # Store verifier in a signed temporary cookie
    verifier_payload = _sign_session({"v": verifier, "exp": int(time.time()) + 600})
    secure = _is_secure()
    response.set_cookie(
        _PKCE_COOKIE,
        verifier_payload,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=600,
        path="/api/v1/auth/oauth/google/callback",
    )

    params = urllib.parse.urlencode(
        {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": settings.OAUTH_REDIRECT_URI,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "online",
            "prompt": "select_account",
        }
    )
    authorization_url = f"https://accounts.google.com/o/oauth2/v2/auth?{params}"
    log.info("oauth_authorize_redirect", state=state[:16] + "...")
    return {"authorization_url": authorization_url}


@router.get("/oauth/google/callback")
def google_callback(
    code: str,
    state: str,
    response: Response,
    pkce_verifier: str | None = Cookie(default=None, alias=_PKCE_COOKIE),
) -> UserInfo:
    """Handle Google OAuth callback: exchange code, validate, set session."""
    # Validate state
    if not verify_oauth_state(state):
        log.warning("oauth_callback_invalid_state")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state")

    # Recover PKCE verifier
    if not pkce_verifier:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing PKCE cookie")
    pkce_payload = _verify_session(pkce_verifier)
    if pkce_payload is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid PKCE cookie")
    verifier: str = pkce_payload.get("v", "")

    # Exchange code for tokens
    token_resp = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET.get_secret_value(),
            "redirect_uri": settings.OAUTH_REDIRECT_URI,
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        },
        timeout=10,
    )
    if token_resp.status_code != 200:
        log.warning("oauth_token_exchange_failed", status=token_resp.status_code)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Token exchange failed")

    tokens = token_resp.json()
    id_token_raw: str | None = tokens.get("id_token")
    if not id_token_raw:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="No id_token in response"
        )

    # Decode id_token (header validation already done by Google's token endpoint)
    import base64

    parts = id_token_raw.split(".")
    if len(parts) != 3:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Malformed id_token")
    padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
    try:
        claims: dict[str, Any] = json.loads(base64.urlsafe_b64decode(padded))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Cannot decode id_token"
        ) from exc

    # Validate claims
    if not validate_google_id_token(claims, audience=settings.GOOGLE_CLIENT_ID):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid id_token claims"
        )

    email: str = str(claims.get("email", ""))
    if not email or not oauth_email_allowed(email):
        log.warning("oauth_email_not_allowed", email=email)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Email not allowed")

    # Get or create user
    user_id = get_or_create_oauth_user(
        email=email,
        oauth_provider="google",
        oauth_sub=str(claims.get("sub", "")),
        display_name=str(claims.get("name", "")),
    )

    # Promote to admin if in admin list
    if oauth_email_is_admin(email):
        from db.users import set_admin

        set_admin(user_id, True)

    log_access(auth_method="google_oauth", user_id=user_id, email=email)
    log.info("oauth_login_success", user_id=user_id, email=email)

    # Redirect to frontend dashboard with session cookie
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")
    from fastapi.responses import RedirectResponse

    redirect = RedirectResponse(url=f"{frontend_url}/resumen", status_code=302)
    _set_session_cookie(redirect, {"user_id": user_id})
    redirect.delete_cookie(_PKCE_COOKIE, path="/api/v1/auth/oauth/google/callback")
    return redirect
