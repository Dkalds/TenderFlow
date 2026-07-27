"""Session auth endpoints for the web frontend.

Provides cookie-based session authentication (httpOnly + Secure + SameSite=Lax)
with CSRF protection. Complements the existing X-API-Key auth for machine clients.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
import urllib.parse
from asyncio import to_thread
from typing import Any

import httpx
from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field, field_validator

from config import settings
from db.sessions import create_session, revoke_session, validate_session
from db.users import (
    create_user,
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
    hash_password,
    oauth_email_allowed,
    oauth_email_is_admin,
    oauth_state_nonce,
    verify_google_id_token,
    verify_oauth_state,
    verify_password,
)
from shared.identity import user_key_from_email
from shared.password_policy import check_password_strength

log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_SESSION_COOKIE = "session"
_CSRF_COOKIE = "csrf_token"
_OAUTH_PKCE_COOKIE = "oauth_pkce"
_SESSION_MAX_AGE = 86400  # 24h
_OAUTH_MAX_AGE = 600


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


def _csrf_for_session(session_token: str) -> str:
    """Double-submit token bound to an opaque server-side session token."""
    return hmac.new(get_signing_key(), session_token.encode(), hashlib.sha256).hexdigest()


def _set_session_cookie(response: Response, user_id: int, request: Request) -> str:
    """Crea una sesión opaca revocable y sus cookies de sesión/CSRF."""
    session_token = create_session(
        user_id,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
        ttl_hours=_SESSION_MAX_AGE // 3600,
    )
    csrf_token = _csrf_for_session(session_token)
    secure = _is_secure()
    response.set_cookie(
        _SESSION_COOKIE,
        session_token,
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


def _login_client_key(request: Request, email: str) -> str:
    """Clave opaca por IP y cuenta para el lockout, sin persistir PII directa."""
    from api.middleware import _trusted_client_ip

    material = f"{_trusted_client_ip(request)}:{email.strip().lower()}"
    return hashlib.sha256(material.encode()).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Dependency: current session user
# ---------------------------------------------------------------------------


async def get_current_session_user(
    session: str | None = Cookie(default=None, alias=_SESSION_COOKIE),
) -> dict[str, Any]:
    """Dependency that reads the session cookie and returns user info.

    Raises 401 if the session is missing, invalid, or expired.
    """
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No session")
    session_record = validate_session(session)
    if session_record is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    user_id: int | None = session_record.get("user_id")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session payload"
        )
    user = get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    from db.totp import is_totp_required

    mfa_required = is_totp_required(int(user["id"]))
    return {
        "user_id": user["id"],
        "email": user.get("email"),
        "display_name": user.get("display_name"),
        "is_admin": bool(user.get("is_admin")),
        "csrf": _csrf_for_session(session),
        "session_token": session,
        "authenticated_at": session_record.get("authenticated_at"),
        "mfa_verified_at": session_record.get("mfa_verified_at"),
        "mfa_required": mfa_required,
        "user_key": user_key_from_email(user.get("email"), int(user["id"])),
    }


# ---------------------------------------------------------------------------
# CSRF validation dependency for mutations
# ---------------------------------------------------------------------------


async def require_csrf(
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


class RegisterRequest(BaseModel):
    """Datos para el alta self-service con email + password."""

    email: EmailStr
    password: str
    display_name: str | None = None


class UserInfo(BaseModel):
    """Public user info returned by auth endpoints."""

    user_id: int
    email: str | None = None
    display_name: str | None = None
    is_admin: bool = False
    mfa_required: bool = False


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/login", response_model=UserInfo)
async def login(body: LoginRequest, response: Response, request: Request) -> UserInfo:
    """Authenticate with email + password, set session cookie."""
    from db.rate_limits import clear_login_attempts, is_login_locked_out, record_failed_login

    client_key = _login_client_key(request, str(body.email))
    locked, retry_after = is_login_locked_out(client_key)
    if locked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Try again later.",
            headers={"Retry-After": str(max(1, int(retry_after)))},
        )
    user = get_user_by_email(body.email)
    if not user:
        record_failed_login(client_key)
        log.warning("login_failed", reason="user_not_found")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    pw_hash: str = user.get("password_hash", "") or ""
    if not verify_password(body.password, pw_hash):
        record_failed_login(client_key)
        log.warning("login_failed", user_id=user["id"], reason="bad_password")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    clear_login_attempts(client_key)
    _set_session_cookie(response, user["id"], request)
    from db.totp import is_totp_required

    log_access(auth_method="password", user_id=user["id"])
    log.info("login_success", user_id=user["id"])

    return UserInfo(
        user_id=user["id"],
        email=user.get("email"),
        display_name=user.get("display_name"),
        is_admin=is_admin(user["id"]),
        mfa_required=is_totp_required(user["id"]),
    )


@router.post("/register", response_model=UserInfo, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, response: Response, request: Request) -> UserInfo:
    """Alta self-service con email + password. Hace auto-login (set session cookie).

    Política de contraseña equilibrada: mínimo 10 caracteres con mayúsculas,
    minúsculas y al menos un dígito (sin exigir carácter especial). Registro
    abierto: cualquier email válido puede crear cuenta.
    """
    if not settings.ALLOW_SELF_REGISTRATION and settings.ENV != "dev":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Self-service registration is disabled. Contact an administrator.",
        )

    check = check_password_strength(
        body.password,
        min_length=10,
        require_special=False,
        label="contraseña",
    )
    if not check.is_strong:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=check.summary)

    if get_user_by_email(body.email, include_deactivated=True):
        log.warning("signup_rejected", reason="email_exists")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    display_name = (body.display_name or "").strip() or None
    user_id = create_user(
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=display_name,
    )

    _set_session_cookie(response, user_id, request)  # auto-login
    log_access(auth_method="password_signup", user_id=user_id)
    log.info("signup_success", user_id=user_id)

    return UserInfo(
        user_id=user_id,
        email=body.email,
        display_name=display_name,
        is_admin=False,
    )


# ---------------------------------------------------------------------------
# Dev-only quick login (no password required)
# ---------------------------------------------------------------------------

if settings.ENV == "dev":

    @router.post("/dev-login", response_model=UserInfo)
    async def dev_login(response: Response, request: Request) -> UserInfo:
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
        _set_session_cookie(response, user["id"], request)
        log_access(auth_method="dev_login", user_id=user["id"])
        log.info("dev_login_success", user_id=user["id"])
        return UserInfo(
            user_id=user["id"],
            email=user.get("email"),
            display_name=user.get("display_name"),
            is_admin=is_admin(user["id"]),
        )


@router.get("/me", response_model=UserInfo)
async def me(user: dict[str, Any] = Depends(get_current_session_user)) -> UserInfo:
    """Return info about the currently authenticated user."""
    return UserInfo(
        user_id=user["user_id"],
        email=user.get("email"),
        display_name=user.get("display_name"),
        is_admin=user.get("is_admin", False),
        mfa_required=bool(user.get("mfa_required")),
    )


@router.post("/logout")
async def logout(
    response: Response,
    user: dict[str, Any] = Depends(require_csrf),
) -> dict[str, str]:
    """Revoca la sesión server-side y borra sus cookies."""
    revoke_session(str(user["session_token"]))
    _clear_session_cookies(response)
    return {"detail": "Logged out"}


# ---------------------------------------------------------------------------
# TOTP MFA
# ---------------------------------------------------------------------------


class TotpCodeRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=16)

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        normalized = value.strip()
        if not re.fullmatch(r"(?:[0-9]{6}|[0-9a-fA-F]{16})", normalized):
            raise ValueError("MFA code must be a six-digit TOTP or a recovery code")
        return normalized.lower()


def _reject_if_mfa_locked(user_id: int) -> None:
    from db.rate_limits import is_mfa_locked_out

    locked, retry_after = is_mfa_locked_out(
        user_id,
        max_attempts=settings.MFA_MAX_FAILURES,
        window_seconds=float(settings.MFA_FAILURE_WINDOW_SECONDS),
    )
    if locked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed MFA attempts. Try again later.",
            headers={"Retry-After": str(max(1, int(retry_after)))},
        )


def _record_mfa_failure(user_id: int) -> None:
    from db.rate_limits import record_failed_mfa

    record_failed_mfa(user_id, window_seconds=float(settings.MFA_FAILURE_WINDOW_SECONDS))


async def require_recent_session_auth(
    user: dict[str, Any] = Depends(require_csrf),
) -> dict[str, Any]:
    """Require a recently-created browser session before changing MFA state."""
    from api.routes.dual_auth import require_recent_session

    # Reuse the canonical step-up policy.  Calling its inner dependency through
    # FastAPI would repeat CSRF validation, so provide the already validated
    # cookie principal directly to the same checks here.
    dependency = require_recent_session()
    user["auth_method"] = "session"
    return await dependency(user)


@router.post("/totp/setup")
async def setup_totp(
    response: Response,
    user: dict[str, Any] = Depends(require_recent_session_auth),
) -> dict[str, str]:
    """Inicia el alta de TOTP; el secreto solo se revela en esta respuesta."""
    from db.totp import generate_totp_secret, get_totp_secret, get_totp_uri, save_totp_secret

    user_id = int(user["user_id"])
    if get_totp_secret(user_id) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="TOTP already configured")
    secret = generate_totp_secret()
    save_totp_secret(user_id, secret, confirmed=False)
    response.headers["Cache-Control"] = "no-store"
    return {"otpauth_uri": get_totp_uri(secret, str(user.get("email") or user_id))}


@router.post("/totp/confirm")
async def confirm_totp(
    body: TotpCodeRequest,
    response: Response,
    user: dict[str, Any] = Depends(require_recent_session_auth),
) -> dict[str, Any]:
    """Confirma el primer código TOTP y entrega recovery codes una sola vez."""
    from db.sessions import mark_session_mfa_verified
    from db.totp import confirm_totp as confirm_totp_secret
    from db.totp import generate_recovery_codes, get_totp_secret, verify_totp

    user_id = int(user["user_id"])
    _reject_if_mfa_locked(user_id)
    record = get_totp_secret(user_id)
    if (
        record is None
        or record["confirmed"]
        or not body.code.isdecimal()
        or not verify_totp(record["secret"], body.code)
    ):
        _record_mfa_failure(user_id)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid TOTP code")
    confirm_totp_secret(user_id)
    mark_session_mfa_verified(str(user["session_token"]))
    from db.rate_limits import clear_mfa_attempts

    clear_mfa_attempts(user_id)
    response.headers["Cache-Control"] = "no-store"
    return {"status": "ok", "recovery_codes": generate_recovery_codes(user_id)}


@router.post("/totp/verify")
async def verify_totp_login(
    body: TotpCodeRequest,
    user: dict[str, Any] = Depends(require_csrf),
) -> dict[str, str]:
    """Eleva una sesión pendiente tras verificar TOTP o un recovery code."""
    from db.sessions import mark_session_mfa_verified
    from db.totp import get_totp_secret, use_recovery_code, verify_totp

    user_id = int(user["user_id"])
    _reject_if_mfa_locked(user_id)
    record = get_totp_secret(user_id)
    valid = bool(
        body.code.isdecimal()
        and record
        and record["confirmed"]
        and verify_totp(record["secret"], body.code)
    )
    if not valid and len(body.code) == 16:
        valid = use_recovery_code(user_id, body.code)
    if not valid:
        _record_mfa_failure(user_id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid MFA code")
    mark_session_mfa_verified(str(user["session_token"]))
    from db.rate_limits import clear_mfa_attempts

    clear_mfa_attempts(user_id)
    return {"status": "ok"}


@router.delete("/totp")
async def remove_totp(
    user: dict[str, Any] = Depends(require_recent_session_auth),
) -> dict[str, str]:
    """Desactiva MFA solo desde una sesión que ya superó MFA."""
    if user.get("mfa_required") and not user.get("mfa_verified_at"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Verify MFA before disabling it"
        )
    from db.totp import delete_totp

    delete_totp(int(user["user_id"]))
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Google OAuth with PKCE
# ---------------------------------------------------------------------------


@router.get("/oauth/google/authorize")
async def google_authorize(response: Response) -> dict[str, str]:
    """Redirect URL for Google OAuth with PKCE.

    Returns JSON with ``authorization_url`` so the SPA can redirect the user.
    The verifier remains in a short-lived HttpOnly cookie scoped to the OAuth
    callback; the signed state contains no credential material.
    """
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Google OAuth not configured",
        )

    state = generate_oauth_state()
    oidc_nonce = oauth_state_nonce(state)
    if oidc_nonce is None:
        raise RuntimeError("Generated OAuth state did not contain a valid nonce")
    verifier, challenge = generate_pkce_pair()

    response.set_cookie(
        _OAUTH_PKCE_COOKIE,
        verifier,
        httponly=True,
        secure=_is_secure(),
        samesite="lax",
        max_age=_OAUTH_MAX_AGE,
        path="/api/v1/auth/oauth/google",
    )

    params = urllib.parse.urlencode(
        {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": settings.OAUTH_REDIRECT_URI,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": oidc_nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "online",
            "prompt": "select_account",
        }
    )
    authorization_url = f"https://accounts.google.com/o/oauth2/v2/auth?{params}"
    log.info("oauth_authorize_redirect")
    return {"authorization_url": authorization_url}


def _oauth_error_redirect(frontend_url: str, error: str) -> Response:
    """Redirige a /login con un slug de error en vez de servir JSON crudo.

    Google entrega este callback mediante una navegación de nivel superior del
    navegador (no una llamada fetch del SPA), así que cualquier HTTPException
    lanzada aquí se le muestra al usuario tal cual — un blob JSON en blanco en
    vez de la pantalla de login. Redirigimos siempre a /login?error=<slug> para
    que el usuario vea un mensaje entendible y pueda reintentar.
    """
    redirect = RedirectResponse(url=f"{frontend_url}/login?error={error}", status_code=302)
    redirect.delete_cookie(_OAUTH_PKCE_COOKIE, path="/api/v1/auth/oauth/google")
    return redirect


@router.get("/oauth/google/callback", response_model=None)
async def google_callback(
    code: str,
    state: str,
    response: Response,
    request: Request,
    pkce_verifier: str | None = Cookie(default=None, alias=_OAUTH_PKCE_COOKIE),
) -> UserInfo | Response:
    """Handle Google OAuth callback: exchange code, validate, set session."""
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")

    if not verify_oauth_state(state):
        log.warning("oauth_callback_invalid_state", reason="nonce_or_timestamp")
        return _oauth_error_redirect(frontend_url, "invalid_state")
    oidc_nonce = oauth_state_nonce(state)
    if oidc_nonce is None:
        return _oauth_error_redirect(frontend_url, "invalid_state")

    if not pkce_verifier:
        log.warning("oauth_callback_missing_pkce_verifier")
        return _oauth_error_redirect(frontend_url, "invalid_state")

    # Exchange code for tokens
    try:
        async with httpx.AsyncClient(timeout=10.0) as oauth_client:
            token_resp = await oauth_client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET.get_secret_value(),
                    "redirect_uri": settings.OAUTH_REDIRECT_URI,
                    "grant_type": "authorization_code",
                    "code_verifier": pkce_verifier,
                },
            )
    except httpx.HTTPError as exc:
        log.warning("oauth_token_exchange_network_error", error_type=type(exc).__name__)
        return _oauth_error_redirect(frontend_url, "oauth_failed")
    if token_resp.status_code != 200:
        log.warning("oauth_token_exchange_failed", status=token_resp.status_code)
        return _oauth_error_redirect(frontend_url, "oauth_failed")

    tokens = token_resp.json()
    id_token_raw: str | None = tokens.get("id_token")
    if not id_token_raw:
        log.warning("oauth_token_exchange_missing_id_token")
        return _oauth_error_redirect(frontend_url, "oauth_failed")

    claims = await to_thread(
        verify_google_id_token,
        id_token_raw,
        audience=settings.GOOGLE_CLIENT_ID,
        expected_nonce=oidc_nonce,
    )
    if claims is None:
        return _oauth_error_redirect(frontend_url, "oauth_failed")

    email: str = str(claims.get("email", ""))
    if not email or not oauth_email_allowed(email):
        log.warning("oauth_email_not_allowed")
        return _oauth_error_redirect(frontend_url, "email_not_allowed")

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

    log_access(auth_method="google_oauth", user_id=user_id)
    log.info("oauth_login_success", user_id=user_id)

    # Redirect to frontend dashboard with session cookie
    redirect = RedirectResponse(url=f"{frontend_url}/resumen", status_code=302)
    redirect.delete_cookie(_OAUTH_PKCE_COOKIE, path="/api/v1/auth/oauth/google")
    _set_session_cookie(redirect, user_id, request)
    return redirect
