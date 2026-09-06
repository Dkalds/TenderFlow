"""Session auth endpoints for the web frontend.

Provides cookie-based session authentication (httpOnly + Secure + SameSite=Lax)
with CSRF protection. Complements the existing X-API-Key auth for machine clients.
"""

from __future__ import annotations

import hashlib
import os
import re
import urllib.parse
from asyncio import to_thread
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Cookie,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field, field_validator

from api.concurrency import run_db
from config import settings
from db.sessions import create_session, revoke_session, validate_session_principal
from db.users import (
    admin_granted_by,
    create_user,
    get_or_create_oauth_user,
    get_user_by_email,
    get_user_by_id,
    is_admin,
    log_access,
    set_admin,
)
from observability.logging import get_logger
from shared.auth_core import (
    csv_set,
    generate_oauth_state,
    generate_pkce_pair,
    hash_password,
    oauth_email_allowed,
    oauth_email_is_admin,
    oauth_state_nonce,
    verify_google_id_token,
    verify_oauth_state,
    verify_password,
)
from shared.csrf import csrf_token_valido, generate_csrf_token
from shared.dto import DetailMessage, StatusOk
from shared.identity import fetch_discovery_document, user_key_from_email, verify_oidc_id_token
from shared.password_policy import check_password_strength

log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_SESSION_COOKIE = "session"
_CSRF_COOKIE = "csrf_token"
_OAUTH_PKCE_COOKIE = "oauth_pkce"
_OAUTH_TELEMETRY_COOKIE = "oauth_login"
#: Proveedor con el que se entró, para que la analítica pueda distinguirlos.
#: Va aparte de `_OAUTH_TELEMETRY_COOKIE` — ver el comentario en el callback.
_OAUTH_TELEMETRY_PROVIDER_COOKIE = "oauth_login_provider"
_SESSION_MAX_AGE = 86400  # 24h
_OAUTH_MAX_AGE = 600
_RESET_REQUEST_RESPONSE = "Si existe una cuenta local activa, recibirás un enlace de recuperación."


async def _oauth_access_allowed(email: str) -> bool:
    """Allowlist estática o grant dinámico; cualquier fallo dinámico deniega."""
    if oauth_email_allowed(email):
        return True
    try:
        from db.access_grants import is_access_granted

        return bool(await run_db(is_access_granted, email))
    except Exception:
        log.exception("oauth_dynamic_allowlist_unavailable")
        return False


def _activar_invitaciones(user_id: int, email: str | None) -> None:
    """Convierte en membresías activas las invitaciones pendientes de ese correo.

    Se llama desde el alta local y desde el callback OAuth, dentro del mismo
    salto al threadpool que el resto del trabajo de BD. Importación diferida
    para no arrastrar ``services`` al import de este módulo, que es el que
    carga ``api.app`` en el arranque.
    """
    from services.organizations import accept_invitations_for_email

    accept_invitations_for_email(user_id, email)


async def _password_reset_rate_allowed(request: Request, email: str | None = None) -> bool:
    """Cuotas independientes por IP y sujeto; un fallo del limiter deniega."""
    from api.middleware import _trusted_client_ip
    from services.rate_limiting import get_rate_limiter

    client_ip = _trusted_client_ip(request)
    email_key = hashlib.sha256((email or "").strip().lower().encode()).hexdigest()[:16]

    def _check() -> bool:
        limiter = get_rate_limiter()
        ip_allowed = limiter.check(
            f"password-reset:ip:{client_ip}", max_calls=5, window_seconds=900
        )
        if not ip_allowed:
            return False
        if email:
            return limiter.check(
                f"password-reset:subject:{email_key}", max_calls=3, window_seconds=3600
            )
        return True

    try:
        return bool(await run_db(_check))
    except Exception:
        log.exception("password_reset_rate_limiter_unavailable")
        return False


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------


def _is_secure() -> bool:
    return settings.ENV in ("prod", "staging")


def _csrf_for_session(session_token: str) -> str:
    """Emite el token double-submit de la sesión, en el formato de ``shared.csrf``.

    Delega en :func:`shared.csrf.generate_csrf_token`: con ``kid`` (sobrevive a
    una rotación de ``SIGNING_KEY``) y con caducidad propia. Antes derivaba
    aquí mismo un HMAC plano sin ninguna de las dos cosas, mientras el módulo
    que sí las tenía no lo usaba nadie.

    **No es determinista**: cada llamada lleva su propio timestamp, así que la
    validación es :func:`shared.csrf.csrf_token_valido` y no una comparación
    con el valor «esperado». Eso es lo que permite la rotación.
    """
    return generate_csrf_token(session_token)


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


def _session_principal(session: str | None) -> dict[str, Any]:
    """Resuelve el principal de la cookie de sesión, sin gate de MFA.

    Síncrona a propósito: hace tres viajes a BD (``validate_session``,
    ``get_user_by_id``, ``is_totp_required``) y es la dependencia de casi toda
    la API autenticada por cookie. Sus dos llamadores async la despachan con un
    único ``run_db`` para que ese trabajo no corra sobre el event loop.

    Raises 401 if the session is missing, invalid, or expired.

    Función **síncrona**: las dependencias que la usan la despachan al
    threadpool con ``run_db``. Llamarla directamente desde un ``async def``
    bloquea el event loop durante todo el viaje a la BD, y esta es la
    dependencia base de todo el SPA.
    """
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No session")
    principal = validate_session_principal(session)
    if principal is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    user_id = principal.get("id")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session payload"
        )
    email = principal.get("email")
    return {
        "user_id": user_id,
        "email": email,
        "display_name": principal.get("display_name"),
        "is_admin": bool(principal.get("is_admin")),
        "csrf": _csrf_for_session(session),
        "session_token": session,
        "authenticated_at": principal.get("authenticated_at"),
        "mfa_verified_at": principal.get("mfa_verified_at"),
        "mfa_required": bool(principal.get("mfa_required")),
        "user_key": user_key_from_email(email, int(user_id)),
    }


def _reject_pending_mfa(user: dict[str, Any]) -> None:
    """Corta una sesión cuyo segundo factor todavía no se verificó."""
    if user.get("mfa_required") and not user.get("mfa_verified_at"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="MFA verification required for this session.",
        )


async def get_current_session_user(
    session: str | None = Cookie(default=None, alias=_SESSION_COOKIE),
) -> dict[str, Any]:
    """Dependency that reads the session cookie and returns user info.

    El gate de MFA vive aquí y no en cada ruta: cuando solo lo aplicaba
    ``dual_auth.require_any_auth``, los 35 endpoints de ``analytics`` y
    ``GET /exports/download`` colgaban directamente de esta dependencia y una
    contraseña robada bastaba para leer todo el BI. Al gatear la dependencia
    base, una ruta nueva nace protegida; lo que debe funcionar *antes* de
    completar MFA usa explícitamente :func:`get_session_user_pending_mfa`.
    """
    user = await run_db(_session_principal, session)
    _reject_pending_mfa(user)
    return user


async def get_session_user_pending_mfa(
    session: str | None = Cookie(default=None, alias=_SESSION_COOKIE),
) -> dict[str, Any]:
    """Variante sin gate, solo para el propio flujo de segundo factor.

    La usan ``POST /auth/totp/verify`` (donde se verifica el factor),
    ``POST /auth/logout`` y ``GET /auth/me`` (el SPA lo consulta para saber que
    debe pedir el TOTP). Sin estas excepciones, un usuario con MFA quedaría
    encerrado fuera de su propia cuenta.

    No se expone ``allow_pending_mfa`` como parámetro de la dependencia a
    propósito: FastAPI lo interpretaría como query param y el bypass sería
    invocable desde la URL.
    """
    return await run_db(_session_principal, session)


# ---------------------------------------------------------------------------
# CSRF validation dependency for mutations
# ---------------------------------------------------------------------------


def _reject_bad_csrf(user: dict[str, Any], x_csrf_token: str | None) -> None:
    """Valida el double-submit token contra la sesión que lo emitió.

    ``max_age`` es la vida de la sesión y no el default de una hora de
    ``shared.csrf``: la cookie CSRF se emite una sola vez, en el login, así que
    caducarla antes que la sesión dejaría al usuario con una sesión viva y
    todas sus mutaciones en 403 — un logout disfrazado de error.
    """
    if not csrf_token_valido(
        x_csrf_token,
        str(user.get("session_token") or ""),
        max_age=_SESSION_MAX_AGE,
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token mismatch")


async def require_csrf(
    user: dict[str, Any] = Depends(get_current_session_user),
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> dict[str, Any]:
    """Validates that X-CSRF-Token header matches the value stored in the session."""
    _reject_bad_csrf(user, x_csrf_token)
    return user


async def require_csrf_pending_mfa(
    user: dict[str, Any] = Depends(get_session_user_pending_mfa),
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> dict[str, Any]:
    """Igual que :func:`require_csrf` pero admite sesiones pendientes de MFA.

    ``/auth/logout`` y ``/auth/totp/verify`` son mutaciones y siguen exigiendo
    CSRF; lo que no pueden exigir es un segundo factor que aún no se verificó.
    """
    _reject_bad_csrf(user, x_csrf_token)
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


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=32, max_length=200)
    password: str = Field(min_length=10, max_length=512)


class UserInfo(BaseModel):
    """Public user info returned by auth endpoints."""

    user_id: int
    email: str | None = None
    display_name: str | None = None
    is_admin: bool = False
    mfa_required: bool = False


class TotpSetupResult(BaseModel):
    """Alta de TOTP: el secreto viaja solo aquí, como URI otpauth."""

    otpauth_uri: str


class TotpConfirmResult(BaseModel):
    """Confirmación de TOTP: los recovery codes se entregan una sola vez."""

    status: str
    recovery_codes: list[str]


class OAuthAuthorizeResult(BaseModel):
    """URL de autorización de Google para que el SPA redirija."""

    authorization_url: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/login", response_model=UserInfo)
async def login(body: LoginRequest, response: Response, request: Request) -> UserInfo:
    """Authenticate with email + password, set session cookie."""
    # Nota de implementación (deliberadamente FUERA del docstring: FastAPI lo
    # publica como descripción del endpoint en el OpenAPI, y de ahí baja al
    # cliente TypeScript generado — un detalle de threadpool no es contrato
    # público). Todo el trabajo (seis viajes a BD y el `verify_password` de
    # argon2, caro por diseño) va en un solo salto al threadpool: ejecutado
    # sobre el event loop, cada login serializaba la API entera mientras
    # duraba el KDF.
    from db.rate_limits import clear_login_attempts, is_login_locked_out, record_failed_login
    from db.totp import is_totp_required

    client_key = _login_client_key(request, str(body.email))

    def _authenticate() -> UserInfo:
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
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
            )

        pw_hash: str = user.get("password_hash", "") or ""
        if not verify_password(body.password, pw_hash):
            record_failed_login(client_key)
            log.warning("login_failed", user_id=user["id"], reason="bad_password")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
            )

        clear_login_attempts(client_key)
        _set_session_cookie(response, user["id"], request)

        log_access(auth_method="password", user_id=user["id"])
        log.info("login_success", user_id=user["id"])

        return UserInfo(
            user_id=user["id"],
            email=user.get("email"),
            display_name=user.get("display_name"),
            is_admin=is_admin(user["id"]),
            mfa_required=is_totp_required(user["id"]),
        )

    return await run_db(_authenticate)


@router.post("/register", response_model=UserInfo, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, response: Response, request: Request) -> UserInfo:
    """Alta self-service con email + password. Hace auto-login (set session cookie).

    Política de contraseña equilibrada: mínimo 10 caracteres con mayúsculas,
    minúsculas y al menos un dígito (sin exigir carácter especial).

    **El alta NO es abierta.** Está cerrada por defecto
    (``ALLOW_SELF_REGISTRATION=False``) y en producción responde 403: el acceso
    a TenderFlow es por invitación y se concede a mano desde el panel de
    solicitudes. Este docstring decía «Registro abierto: cualquier email válido
    puede crear cuenta» dos líneas por encima del guard que lo impide.
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

    display_name = (body.display_name or "").strip() or None

    def _create_account() -> int:
        """BD + ``hash_password`` (argon2) fuera del event loop."""
        if get_user_by_email(body.email, include_deactivated=True):
            log.warning("signup_rejected", reason="email_exists")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
            )
        new_id = create_user(
            email=body.email,
            password_hash=hash_password(body.password),
            display_name=display_name,
        )
        # Registrarse con el correo al que se invitó es la prueba de que se
        # controla ese buzón: aquí es donde la invitación pendiente se convierte
        # en membresía activa y la organización aparece en GET /organizations.
        _activar_invitaciones(new_id, str(body.email))
        _set_session_cookie(response, new_id, request)  # auto-login
        log_access(auth_method="password_signup", user_id=new_id)
        return new_id

    user_id = await run_db(_create_account)
    log.info("signup_success", user_id=user_id)

    return UserInfo(
        user_id=user_id,
        email=body.email,
        display_name=display_name,
        is_admin=False,
    )


# ---------------------------------------------------------------------------
# Password recovery for local accounts
# ---------------------------------------------------------------------------


@router.post(
    "/password-reset/request",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DetailMessage,
)
async def request_password_reset(
    body: PasswordResetRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> DetailMessage:
    """Emite una respuesta indistinguible exista o no la cuenta."""
    email = str(body.email).strip().lower()
    if not await _password_reset_rate_allowed(request, email):
        return DetailMessage(detail=_RESET_REQUEST_RESPONSE)

    from services.password_reset import issue_password_reset, send_password_reset_email

    try:
        created, token = await run_db(issue_password_reset, email)
    except Exception:
        log.exception("password_reset_request_failed")
        return DetailMessage(detail=_RESET_REQUEST_RESPONSE)
    if created and token is not None:
        background_tasks.add_task(send_password_reset_email, email, token)
    return DetailMessage(detail=_RESET_REQUEST_RESPONSE)


@router.post("/password-reset/confirm", response_model=StatusOk)
async def confirm_password_reset(
    body: PasswordResetConfirm,
    request: Request,
) -> StatusOk:
    """Consume un token una sola vez, cambia la contraseña y revoca sesiones."""
    if not await _password_reset_rate_allowed(request):
        raise HTTPException(status_code=429, detail="Demasiados intentos. Inténtalo más tarde.")

    password_check = check_password_strength(
        body.password,
        min_length=10,
        label="password",
    )
    if not password_check.is_strong:
        raise HTTPException(status_code=400, detail=password_check.summary)

    from db.password_reset import consume_reset_token
    from services.password_reset import token_hash

    def _consume() -> int | None:
        password_digest = hash_password(body.password)
        return consume_reset_token(token_hash(body.token), password_digest)

    user_id = await run_db(_consume)
    if user_id is None:
        raise HTTPException(status_code=400, detail="El enlace no es válido o ha caducado.")
    log.info("password_reset_completed", user_id=user_id)
    return StatusOk(status="ok")


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

        def _dev_login() -> UserInfo:
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

        return await run_db(_dev_login)


@router.get("/me", response_model=UserInfo)
async def me(user: dict[str, Any] = Depends(get_session_user_pending_mfa)) -> UserInfo:
    """Return info about the currently authenticated user.

    Accesible con MFA pendiente: es la respuesta que le dice al SPA que debe
    pedir el TOTP. Solo devuelve identidad, nunca datos de negocio.
    """
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
    user: dict[str, Any] = Depends(require_csrf_pending_mfa),
) -> DetailMessage:
    """Revoca la sesión server-side y borra sus cookies.

    Debe funcionar con MFA pendiente: abandonar un login a medias no puede
    requerir completarlo.
    """
    await run_db(revoke_session, str(user["session_token"]))
    _clear_session_cookies(response)
    return DetailMessage(detail="Logged out")


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
) -> TotpSetupResult:
    """Inicia el alta de TOTP; el secreto solo se revela en esta respuesta."""
    from db.totp import generate_totp_secret, get_totp_secret, get_totp_uri, save_totp_secret

    user_id = int(user["user_id"])

    def _setup() -> str:
        if get_totp_secret(user_id) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="TOTP already configured"
            )
        secret = generate_totp_secret()
        save_totp_secret(user_id, secret, confirmed=False)
        return get_totp_uri(secret, str(user.get("email") or user_id))

    otpauth_uri = await run_db(_setup)
    response.headers["Cache-Control"] = "no-store"
    return TotpSetupResult(otpauth_uri=otpauth_uri)


@router.post("/totp/confirm")
async def confirm_totp(
    body: TotpCodeRequest,
    response: Response,
    user: dict[str, Any] = Depends(require_recent_session_auth),
) -> TotpConfirmResult:
    """Confirma el primer código TOTP y entrega recovery codes una sola vez."""
    from db.rate_limits import clear_mfa_attempts
    from db.sessions import mark_session_mfa_verified
    from db.totp import confirm_totp as confirm_totp_secret
    from db.totp import generate_recovery_codes, get_totp_secret, verify_totp

    user_id = int(user["user_id"])

    def _confirm() -> list[str]:
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
        clear_mfa_attempts(user_id)
        return generate_recovery_codes(user_id)

    recovery_codes = await run_db(_confirm)
    response.headers["Cache-Control"] = "no-store"
    return TotpConfirmResult(status="ok", recovery_codes=recovery_codes)


@router.post("/totp/verify")
async def verify_totp_login(
    body: TotpCodeRequest,
    user: dict[str, Any] = Depends(require_csrf_pending_mfa),
) -> StatusOk:
    """Eleva una sesión pendiente tras verificar TOTP o un recovery code.

    Es la única ruta que *tiene* que aceptar una sesión sin MFA verificado:
    gatearla dejaría a todo usuario con TOTP sin forma de completar el login.
    """
    from db.rate_limits import clear_mfa_attempts
    from db.sessions import mark_session_mfa_verified
    from db.totp import get_totp_secret, use_recovery_code, verify_totp

    user_id = int(user["user_id"])

    def _verify() -> None:
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
        clear_mfa_attempts(user_id)

    await run_db(_verify)
    return StatusOk(status="ok")


@router.delete("/totp")
async def remove_totp(
    user: dict[str, Any] = Depends(require_recent_session_auth),
) -> StatusOk:
    """Desactiva MFA solo desde una sesión que ya superó MFA."""
    if user.get("mfa_required") and not user.get("mfa_verified_at"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Verify MFA before disabling it"
        )
    from db.totp import delete_totp

    await run_db(delete_totp, int(user["user_id"]))
    return StatusOk(status="ok")


# ---------------------------------------------------------------------------
# OIDC con PKCE — tabla de proveedores (S1.2, D17)
# ---------------------------------------------------------------------------
#
# Hasta 2026-09 este bloque era el flujo de Google escrito en línea. Ahora los
# proveedores son datos y el flujo es uno solo: PKCE, `state`, `nonce`, la
# allowlist (estática + `access_grants`) y el alta del usuario son idénticos
# para todos, y lo único que cambia por proveedor son sus endpoints, sus
# credenciales y cómo se verifica su `id_token`.
#
# Google conserva su verificador específico (`shared.auth_core.
# verify_google_id_token`) a propósito: es el camino que hoy funciona en
# producción y el riesgo de este stream está justamente en tocarlo. Lo genérico
# —descubrimiento OpenID + JWKS— sirve a Microsoft y a cualquier proveedor que
# venga después.


@dataclass(frozen=True)
class _OAuthEndpoints:
    """Las cuatro URLs que el flujo necesita de un proveedor."""

    authorize_url: str
    token_url: str
    jwks_uri: str
    issuer: str


@dataclass(frozen=True)
class _OAuthProvider:
    """Un proveedor OIDC: credenciales, endpoints y verificación de su token."""

    name: str
    #: Etiqueta para mensajes de error de configuración.
    label: str
    #: ``(client_id, client_secret)``; se lee en cada uso para que un cambio de
    #: entorno no exija reiniciar ni invalidar una constante de módulo.
    credentials: Callable[[], tuple[str, str]]
    #: Endpoints fijos, o ``None`` si salen del documento de descubrimiento.
    static_endpoints: _OAuthEndpoints | None
    #: URL del ``.well-known/openid-configuration``, si aplica.
    discovery_url: Callable[[], str] | None
    scope: str
    #: Parámetros propios del proveedor en la URL de autorización.
    extra_authorize_params: Mapping[str, str] = field(default_factory=dict)
    #: ``True`` cuando el proveedor tiene su propio verificador ya probado.
    usa_verificador_google: bool = False


def _google_credentials() -> tuple[str, str]:
    return settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET.get_secret_value()


def _microsoft_credentials() -> tuple[str, str]:
    from config.settings import oauth_microsoft_client_id, oauth_microsoft_client_secret

    return oauth_microsoft_client_id(), oauth_microsoft_client_secret()


def _microsoft_discovery_url() -> str:
    from config.settings import oauth_microsoft_tenant

    tenant = urllib.parse.quote(oauth_microsoft_tenant(), safe="")
    return f"https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration"


#: Tabla de proveedores. Su gemelo en SQL es el ``CHECK`` de
#: ``v105_users_oauth_provider``; ``tests/test_s1_oauth_providers.py`` comprueba
#: que no divergen — un proveedor que la BD no admite guardaría identidades
#: duplicadas de la misma persona.
_PROVIDERS: dict[str, _OAuthProvider] = {
    "google": _OAuthProvider(
        name="google",
        label="Google",
        credentials=_google_credentials,
        static_endpoints=_OAuthEndpoints(
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",  # noqa: S106 - URL pública, no un secreto
            # Google verifica con su propio camino: estos dos no se usan y se
            # dejan por completitud del registro.
            jwks_uri="https://www.googleapis.com/oauth2/v3/certs",
            issuer="https://accounts.google.com",
        ),
        discovery_url=None,
        scope="openid email profile",
        extra_authorize_params={"access_type": "online", "prompt": "select_account"},
        usa_verificador_google=True,
    ),
    "microsoft": _OAuthProvider(
        name="microsoft",
        label="Microsoft",
        credentials=_microsoft_credentials,
        static_endpoints=None,
        discovery_url=_microsoft_discovery_url,
        # `offline_access` queda fuera: no se guarda refresh token, la sesión de
        # TenderFlow es propia y dura 24 h.
        scope="openid email profile",
        extra_authorize_params={"prompt": "select_account"},
    ),
}

#: Nombres admitidos, en el orden en que se ofrecen en la pantalla de login.
OAUTH_PROVIDERS: tuple[str, ...] = tuple(_PROVIDERS)


def _provider_or_404(provider: str) -> _OAuthProvider:
    configurado = _PROVIDERS.get(provider)
    if configurado is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proveedor OAuth desconocido: {provider}",
        )
    return configurado


def _provider_credentials(provider: _OAuthProvider) -> tuple[str, str]:
    client_id, client_secret = provider.credentials()
    if not client_id:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"{provider.label} OAuth not configured",
        )
    return client_id, client_secret


def _pkce_cookie_path(provider: _OAuthProvider) -> str:
    """El verifier solo viaja al callback de SU proveedor."""
    return f"/api/v1/auth/oauth/{provider.name}"


def _provider_redirect_uri(provider: _OAuthProvider) -> str:
    """Redirect URI del proveedor, derivado del de Google.

    ``OAUTH_REDIRECT_URI`` apunta al callback de Google y es la única variable
    que conoce el host público de la API. Los demás proveedores comparten host
    y solo cambian el segmento del proveedor, así que derivarlo evita una
    variable por proveedor que se olvidaría de actualizar en el próximo cambio
    de dominio (S1.3).
    """
    base = settings.OAUTH_REDIRECT_URI
    if provider.name == "google":
        return base
    return base.replace("/oauth/google/callback", f"/oauth/{provider.name}/callback")


async def _provider_endpoints(provider: _OAuthProvider) -> _OAuthEndpoints:
    """Endpoints fijos o leídos del documento de descubrimiento del proveedor."""
    if provider.static_endpoints is not None:
        return provider.static_endpoints
    if provider.discovery_url is None:  # pragma: no cover - configuración imposible
        raise RuntimeError(f"El proveedor {provider.name} no declara endpoints")
    document = await to_thread(fetch_discovery_document, provider.discovery_url())
    try:
        return _OAuthEndpoints(
            authorize_url=str(document["authorization_endpoint"]),
            token_url=str(document["token_endpoint"]),
            jwks_uri=str(document["jwks_uri"]),
            issuer=str(document["issuer"]),
        )
    except KeyError as exc:
        raise RuntimeError(
            f"El documento de descubrimiento de {provider.name} no trae {exc}"
        ) from exc


def _verify_provider_id_token(
    provider: _OAuthProvider,
    raw_token: str,
    *,
    endpoints: _OAuthEndpoints,
    audience: str,
    expected_nonce: str,
) -> dict[str, Any] | None:
    """Verifica el ``id_token`` con el camino que corresponde al proveedor."""
    if provider.usa_verificador_google:
        # Búsqueda del nombre en el módulo (no una referencia capturada) para
        # que los tests que ya existían puedan seguir sustituyéndolo.
        return verify_google_id_token(raw_token, audience=audience, expected_nonce=expected_nonce)
    return verify_oidc_id_token(
        raw_token,
        jwks_uri=endpoints.jwks_uri,
        issuer=endpoints.issuer,
        audience=audience,
        expected_nonce=expected_nonce,
    )


def _email_from_claims(claims: Mapping[str, Any]) -> str:
    """Correo del token. Entra ID no siempre manda ``email``.

    Con cuentas de trabajo, Microsoft emite ``preferred_username`` (el UPN) y
    solo incluye ``email`` si el tenant lo tiene poblado. Sin este respaldo, un
    login de Microsoft perfectamente válido acabaría en «email_not_allowed».
    """
    for clave in ("email", "preferred_username", "upn"):
        valor = str(claims.get(clave, "") or "").strip()
        if "@" in valor:
            return valor
    return ""


async def _authorize_url(provider: _OAuthProvider, response: Response) -> OAuthAuthorizeResult:
    """URL de autorización con PKCE, idéntica para todos los proveedores."""
    client_id, _ = _provider_credentials(provider)
    endpoints = await _provider_endpoints(provider)

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
        path=_pkce_cookie_path(provider),
    )

    params = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": _provider_redirect_uri(provider),
            "response_type": "code",
            "scope": provider.scope,
            "state": state,
            "nonce": oidc_nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            **provider.extra_authorize_params,
        }
    )
    log.info("oauth_authorize_redirect", provider=provider.name)
    return OAuthAuthorizeResult(authorization_url=f"{endpoints.authorize_url}?{params}")


@router.get("/oauth/google/authorize")
async def google_authorize(response: Response) -> OAuthAuthorizeResult:
    """Redirect URL for Google OAuth with PKCE.

    Returns JSON with ``authorization_url`` so the SPA can redirect the user.
    The verifier remains in a short-lived HttpOnly cookie scoped to the OAuth
    callback; the signed state contains no credential material.
    """
    return await _authorize_url(_PROVIDERS["google"], response)


@router.get("/oauth/{provider}/authorize")
async def oauth_authorize(provider: str, response: Response) -> OAuthAuthorizeResult:
    """URL de autorización del proveedor OIDC indicado (``google``, ``microsoft``).

    Devuelve JSON con ``authorization_url`` para que el SPA redirija. El
    verifier PKCE queda en una cookie HttpOnly de vida corta, limitada al
    callback de ese proveedor; el ``state`` firmado no lleva material sensible.
    """
    return await _authorize_url(_provider_or_404(provider), response)


def _sync_oauth_admin(user_id: int, email: str) -> None:
    """Refleja ``OAUTH_ADMIN_EMAILS`` sobre ``is_admin`` en ambos sentidos.

    Antes solo promovía: sacar a alguien de la lista no le quitaba admin nunca,
    así que revocar un administrador exigía acordarse de tocar la BD a mano.

    La sincronización se salta cuando la lista está vacía, porque ese caso no
    significa "nadie es admin" sino "OAuth no gobierna el flag": la otra fuente
    legítima es el panel (``admin_users.admin_set_admin``), y degradar ahí
    desadministraría a todos sus promovidos en el próximo login.

    **Precedencia, con la lista configurada:** OAuth solo gobierna *sus
    propias* concesiones. Antes mandaba sobre el panel —a quien se promovía con
    ``admin_users.admin_set_admin`` y además entraba con Google se le retiraba
    el flag en su siguiente login—, porque ``users.is_admin`` era un booleano
    sin procedencia y no se podía distinguir el origen. Con
    ``users.admin_granted_by`` (v75) sí se puede: esta función degrada
    únicamente lo que concedió ella (``'oauth'``), y deja intactas tanto las
    concesiones del panel como las de procedencia desconocida (``NULL``:
    anteriores a la migración, nadie puede afirmar quién las hizo).
    """
    if not csv_set(settings.OAUTH_ADMIN_EMAILS):
        return
    should_be_admin = oauth_email_is_admin(email)
    if should_be_admin:
        set_admin(user_id, True, granted_by="oauth")
        return
    if not is_admin(user_id):
        return
    origen = admin_granted_by(user_id)
    if origen != "oauth":
        # Concesión del panel (o previa a v75): OAuth no la otorgó, así que no
        # la retira. Se deja constancia porque es un desacuerdo entre las dos
        # fuentes y conviene poder verlo.
        log.info(
            "oauth_admin_preserved",
            user_id=user_id,
            granted_by=origen or "desconocido",
            hint=(
                "El email no está en OAUTH_ADMIN_EMAILS pero la concesión no vino "
                "de OAuth: se conserva. Para revocarla, usá el panel de administración."
            ),
        )
        return
    log.warning(
        "oauth_admin_revoked",
        user_id=user_id,
        hint=(
            "La cuenta tenía is_admin concedido por OAuth y su email ya no está "
            "en OAUTH_ADMIN_EMAILS."
        ),
    )
    set_admin(user_id, False)


def _oauth_error_redirect(frontend_url: str, error: str, provider: str = "google") -> Response:
    """Redirige a /login con un slug de error en vez de servir JSON crudo.

    El proveedor entrega este callback mediante una navegación de nivel
    superior del navegador (no una llamada fetch del SPA), así que cualquier
    HTTPException lanzada aquí se le muestra al usuario tal cual — un blob JSON
    en blanco en vez de la pantalla de login. Redirigimos siempre a
    /login?error=<slug> para que el usuario vea un mensaje entendible y pueda
    reintentar.
    """
    redirect = RedirectResponse(url=f"{frontend_url}/login?error={error}", status_code=302)
    redirect.delete_cookie(_OAUTH_PKCE_COOKIE, path=f"/api/v1/auth/oauth/{provider}")
    return redirect


async def _oauth_callback_impl(
    provider: _OAuthProvider,
    *,
    code: str,
    state: str,
    request: Request,
    pkce_verifier: str | None,
) -> Response:
    """Canje del código, verificación del ``id_token`` y alta de la sesión.

    Es el cuerpo compartido de los callbacks: lo único que varía por proveedor
    son sus endpoints, sus credenciales y cómo se verifica su ``id_token``.
    """
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")

    if not verify_oauth_state(state):
        log.warning("oauth_callback_invalid_state", reason="nonce_or_timestamp")
        return _oauth_error_redirect(frontend_url, "invalid_state", provider.name)
    oidc_nonce = oauth_state_nonce(state)
    if oidc_nonce is None:
        return _oauth_error_redirect(frontend_url, "invalid_state", provider.name)

    if not pkce_verifier:
        log.warning("oauth_callback_missing_pkce_verifier")
        return _oauth_error_redirect(frontend_url, "invalid_state", provider.name)

    # Sin `_provider_credentials`: esa función lanza 501 y este callback NUNCA
    # puede lanzar —el navegador llega por navegación de nivel superior y vería
    # el JSON crudo—. Con el proveedor sin configurar, el canje del código falla
    # y se sale por el redirect de error, que es lo que hacía antes de S1.2.
    client_id, client_secret = provider.credentials()
    try:
        endpoints = await _provider_endpoints(provider)
    except Exception:
        log.exception("oauth_discovery_unavailable", provider=provider.name)
        return _oauth_error_redirect(frontend_url, "oauth_failed", provider.name)

    # Exchange code for tokens
    try:
        async with httpx.AsyncClient(timeout=10.0) as oauth_client:
            token_resp = await oauth_client.post(
                endpoints.token_url,
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": _provider_redirect_uri(provider),
                    "grant_type": "authorization_code",
                    "code_verifier": pkce_verifier,
                },
            )
    except httpx.HTTPError as exc:
        log.warning("oauth_token_exchange_network_error", error_type=type(exc).__name__)
        return _oauth_error_redirect(frontend_url, "oauth_failed", provider.name)
    if token_resp.status_code != 200:
        log.warning("oauth_token_exchange_failed", status=token_resp.status_code)
        return _oauth_error_redirect(frontend_url, "oauth_failed", provider.name)

    tokens = token_resp.json()
    id_token_raw: str | None = tokens.get("id_token")
    if not id_token_raw:
        log.warning("oauth_token_exchange_missing_id_token")
        return _oauth_error_redirect(frontend_url, "oauth_failed", provider.name)

    claims = await to_thread(
        _verify_provider_id_token,
        provider,
        id_token_raw,
        endpoints=endpoints,
        audience=client_id,
        expected_nonce=oidc_nonce,
    )
    if claims is None:
        return _oauth_error_redirect(frontend_url, "oauth_failed", provider.name)

    email: str = _email_from_claims(claims)
    if not email or not await _oauth_access_allowed(email):
        log.warning("oauth_email_not_allowed", provider=provider.name)
        return _oauth_error_redirect(frontend_url, "email_not_allowed", provider.name)

    from db.totp import is_totp_required

    def _provision_user() -> tuple[int, bool]:
        """Alta/actualización del usuario OAuth y su gate de MFA, en threadpool."""
        new_id = get_or_create_oauth_user(
            email=email,
            oauth_provider=provider.name,
            oauth_sub=str(claims.get("sub", "")),
            display_name=str(claims.get("name", "")),
        )
        _sync_oauth_admin(new_id, email)
        # Entrar por OAuth con el correo invitado demuestra que se controla ese
        # buzón: es el momento en que la membresía `invited` pasa a `active`.
        _activar_invitaciones(new_id, email)
        log_access(auth_method=f"{provider.name}_oauth", user_id=new_id)
        return new_id, is_totp_required(new_id)

    user_id, mfa_required = await run_db(_provision_user)
    log.info("oauth_login_success", user_id=user_id, provider=provider.name)

    # Con MFA confirmado la sesión nace pendiente: mandarla al dashboard la
    # dejaría en una pantalla que responde 403 en todo. El SPA lee `?mfa=required`
    # y muestra la verificación del segundo factor sobre la sesión ya creada.
    destino = "/login?mfa=required" if mfa_required else "/resumen"
    redirect = RedirectResponse(url=f"{frontend_url}{destino}", status_code=302)
    redirect.delete_cookie(_OAUTH_PKCE_COOKIE, path=_pkce_cookie_path(provider))
    if not mfa_required:
        secure = settings.ENV in ("prod", "staging")
        redirect.set_cookie(
            _OAUTH_TELEMETRY_COOKIE,
            "1",
            max_age=120,
            httponly=False,
            secure=secure,
            samesite="lax",
            path="/",
        )
        # Cookie aparte y no un valor distinto en la anterior: el componente que
        # la lee (`web/src/components/oauth-login-telemetry.tsx`) compara contra
        # `oauth_login=1` exacto, así que cambiarle el valor apagaría el evento
        # que ya funciona. Solo lleva el nombre del proveedor — ni correo, ni id,
        # ni nada que identifique a la persona.
        redirect.set_cookie(
            _OAUTH_TELEMETRY_PROVIDER_COOKIE,
            provider.name,
            max_age=120,
            httponly=False,
            secure=secure,
            samesite="lax",
            path="/",
        )
    await run_db(_set_session_cookie, redirect, user_id, request)
    return redirect


# status_code=302: el callback SIEMPRE redirige (éxito → /resumen, error →
# /login?error=<slug>) — nunca sirve JSON. Sin esto, OpenAPI documentaba un
# 200 application/json {} que no existe (operación opaca en el ratchet).
@router.get("/oauth/google/callback", response_model=None, status_code=302)
async def google_callback(
    code: str,
    state: str,
    response: Response,
    request: Request,
    pkce_verifier: str | None = Cookie(default=None, alias=_OAUTH_PKCE_COOKIE),
) -> Response:
    """Handle Google OAuth callback: exchange code, validate, set session."""
    return await _oauth_callback_impl(
        _PROVIDERS["google"],
        code=code,
        state=state,
        request=request,
        pkce_verifier=pkce_verifier,
    )


@router.get("/oauth/{provider}/callback", response_model=None, status_code=302)
async def oauth_callback(
    provider: str,
    code: str,
    state: str,
    response: Response,
    request: Request,
    pkce_verifier: str | None = Cookie(default=None, alias=_OAUTH_PKCE_COOKIE),
) -> Response:
    """Callback OIDC: canjea el código, valida el token y abre la sesión.

    Siempre redirige (éxito → /resumen, error → /login?error=<slug>): el
    navegador llega aquí por navegación de nivel superior, no por fetch.
    """
    return await _oauth_callback_impl(
        _provider_or_404(provider),
        code=code,
        state=state,
        request=request,
        pkce_verifier=pkce_verifier,
    )
