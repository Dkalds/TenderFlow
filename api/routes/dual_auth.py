"""Autenticación dual con una única identidad y CSRF centralizado.

Una API key es una credencial ligada a un usuario; jamás sustituye su identidad
ni convierte por sí misma a alguien en administrador.
"""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import Cookie, Depends, Header, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

from api.scopes import has_scope, required_scope_for_request
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
) -> dict[str, Any]:
    """Acepta sesión o API key, devolviendo un principal coherente.

    Las mutaciones autenticadas con cookie exigen CSRF. Las API keys sin un
    usuario propietario se rechazan en producción para impedir que una misma
    persona se fragmente en identidades por credencial.
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
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token mismatch")
        session_user["auth_method"] = "session"
        session_user["user_key"] = user_key_from_email(
            session_user.get("email"), int(session_user["user_id"])
        )
        return session_user

    if api_key_raw:
        from api.auth import hash_api_key
        from db.connection import now_utc_iso
        from db.users import get_user_by_id
        from services import auth as auth_service

        key_hash = hash_api_key(api_key_raw)
        record = auth_service.lookup_active_key(key_hash)
        if record is not None and record.expires_at and now_utc_iso() > record.expires_at:
            record = None
        if record is not None:
            user_id = record.user_id
            if user_id is None:
                if settings.ENV in ("prod", "staging"):
                    log.warning("unbound_api_key_rejected", key_id=record.key_id)
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key not bound")
                # Compatibilidad temporal exclusiva de desarrollo/tests.
                user_id = record.key_id
                owner: dict[str, Any] | None = None
            else:
                owner = get_user_by_id(user_id)
                if owner is None:
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key owner inactive")

            scopes = frozenset(s.strip() for s in record.scopes.split(",") if s.strip())
            required_scope = required_scope_for_request(request.method, request.url.path)
            if not has_scope(scopes, required_scope):
                log.warning(
                    "api_key_scope_denied",
                    key_id=record.key_id,
                    required=required_scope,
                    available=sorted(scopes),
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="API key scope insufficient.",
                )
            email = owner.get("email") if owner is not None else None
            return {
                "user_id": user_id,
                "api_key_id": record.key_id,
                "email": email,
                "display_name": owner.get("display_name") if owner is not None else None,
                "is_admin": bool(owner and owner.get("is_admin")) and ("*" in scopes or "admin" in scopes),
                "auth_method": "api_key",
                "key_hash": key_hash,
                "scopes": scopes,
                "user_key": user_key_from_email(email, user_id),
            }

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Provide session cookie or X-API-Key header.",
    )


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
        if authenticated_at is None or (now - authenticated_at).total_seconds() > settings.SENSITIVE_ACTION_MAX_AGE_SECONDS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Reauthenticate before performing this sensitive operation.",
            )

        if ctx.get("mfa_required"):
            verified_at = _parse_timestamp(ctx.get("mfa_verified_at"))
            if verified_at is None or (now - verified_at).total_seconds() > settings.MFA_STEP_UP_MAX_AGE_SECONDS:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Verify MFA again before performing this sensitive operation.",
                )
        return ctx

    _dependency.__name__ = "require_recent_session"
    return _dependency
