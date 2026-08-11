"""Autenticación dual con una única identidad y CSRF centralizado.

Una API key es una credencial ligada a un usuario; jamás sustituye su identidad
ni convierte por sí misma a alguien en administrador.
"""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import (
    BackgroundTasks,
    Cookie,
    Depends,
    Header,
    HTTPException,
    Request,
    Security,
    status,
)
from fastapi.security import APIKeyHeader

from api.concurrency import run_db
from config import settings
from observability.logging import get_logger
from shared.identity import user_key_from_email

log = get_logger(__name__)

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


async def require_any_auth(
    request: Request,
    api_key_raw: str | None = Security(_API_KEY_HEADER),
    session: str | None = Cookie(default=None, alias="session"),
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
) -> dict[str, Any]:
    """Acepta sesión o API key, devolviendo un principal coherente.

    Las mutaciones autenticadas con cookie exigen CSRF. Las API keys sin un
    usuario propietario se rechazan en producción para impedir que una misma
    persona se fragmente en identidades por credencial.

    La validación de la API key delega en
    ``api.auth.validate_api_key_credential`` — el mismo núcleo (comparación en
    tiempo constante, defensa anti-timing, 503 ante error de BD, expiración,
    scopes y ``last_used``) que usa ``require_api_key``.
    """
    if session:
        from api.routes.auth import get_current_session_user

        session_user = await get_current_session_user(session)
        if session_user.get("mfa_required") and not session_user.get("mfa_verified_at"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="MFA verification required for this session.",
            )
        if request.method.upper() in _UNSAFE_METHODS:
            expected = str(session_user.get("csrf") or "")
            if not x_csrf_token or not hmac.compare_digest(x_csrf_token, expected):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token mismatch"
                )
        session_user["auth_method"] = "session"
        session_user["user_key"] = user_key_from_email(
            session_user.get("email"), int(session_user["user_id"])
        )
        return session_user

    if api_key_raw:
        from api.auth import validate_api_key_credential
        from db.users import get_user_by_id

        ctx = await validate_api_key_credential(
            api_key_raw,
            method=request.method,
            path=request.url.path,
            background_tasks=background_tasks,
        )
        user_id = ctx.user_id
        if user_id is None:
            # El núcleo ya rechazó keys sin propietario en prod/staging.
            # Compatibilidad temporal exclusiva de desarrollo/tests.
            user_id = ctx.key_id
            owner: dict[str, Any] | None = None
        else:
            # `get_user_by_id` es síncrono (psycopg3): sin `run_db` bloquearía
            # el event loop en cada petición autenticada por API key.
            owner = await run_db(get_user_by_id, user_id)
            if owner is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="API key owner inactive"
                )

        scopes = ctx.scopes
        email = owner.get("email") if owner is not None else None
        return {
            "user_id": user_id,
            "api_key_id": ctx.key_id,
            "email": email,
            "display_name": owner.get("display_name") if owner is not None else None,
            "is_admin": bool(owner and owner.get("is_admin"))
            and ("*" in scopes or "admin" in scopes),
            "auth_method": "api_key",
            "key_hash": ctx.key_hash,
            "scopes": scopes,
            "user_key": user_key_from_email(email, user_id),
        }

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Provide session cookie or X-API-Key header.",
    )


async def require_admin(user: dict[str, Any] = Depends(require_any_auth)) -> dict[str, Any]:
    """Exige que el principal autenticado (sesión o API key) sea admin.

    Antes triplicado idénticamente en admin_users.py/feature_flags.py/
    webhooks.py — un solo sitio evita que una copia diverja de las otras dos.
    """
    if not user.get("is_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required.")
    return user


def require_recent_session() -> Callable[..., Awaitable[dict[str, Any]]]:
    """Require a freshly authenticated browser session for destructive actions.

    API keys are excellent for automation but should not be sufficient to
    delete an account or weaken MFA.  A session may be used only while its
    original authentication is recent; TOTP-enabled accounts must also have a
    recent successful second-factor verification.
    """

    async def _dependency(ctx: dict[str, Any] = Depends(require_any_auth)) -> dict[str, Any]:
        if ctx.get("auth_method") != "session":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This operation requires a recent browser session.",
            )

        def _parse_timestamp(value: object) -> datetime | None:
            if not isinstance(value, str) or not value:
                return None
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
            return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)

        now = datetime.now(UTC)
        authenticated_at = _parse_timestamp(ctx.get("authenticated_at"))
        if (
            authenticated_at is None
            or (now - authenticated_at).total_seconds() > settings.SENSITIVE_ACTION_MAX_AGE_SECONDS
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Reauthenticate before performing this sensitive operation.",
            )

        if ctx.get("mfa_required"):
            verified_at = _parse_timestamp(ctx.get("mfa_verified_at"))
            if (
                verified_at is None
                or (now - verified_at).total_seconds() > settings.MFA_STEP_UP_MAX_AGE_SECONDS
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Verify MFA again before performing this sensitive operation.",
                )
        return ctx

    _dependency.__name__ = "require_recent_session"
    return _dependency
