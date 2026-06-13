"""Dual authentication — accepts either session cookie or API key.

Allows endpoints to be called by both the web frontend (session cookie)
and machine clients (X-API-Key header).
"""

from __future__ import annotations

from typing import Any

from fastapi import Cookie, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from observability.logging import get_logger

log = get_logger(__name__)

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_any_auth(
    api_key_raw: str | None = Security(_API_KEY_HEADER),
    session: str | None = Cookie(default=None, alias="session"),
) -> dict[str, Any]:
    """Accept either session cookie or API key. Returns a unified user dict.

    Priority: session cookie first (for browser requests), then API key.
    Returns dict with at least: user_id, email, is_admin.
    """
    # Try session cookie first
    if session:
        try:
            from api.routes.auth import _verify_session
            from db.users import get_user_by_id

            payload = _verify_session(session)
            if payload is not None:
                user_id = payload.get("user_id")
                if user_id is not None:
                    user = get_user_by_id(user_id)
                    if user is not None:
                        return {
                            "user_id": user["id"],
                            "email": user.get("email"),
                            "display_name": user.get("display_name"),
                            "is_admin": bool(user.get("is_admin")),
                            "auth_method": "session",
                        }
        except Exception:
            pass  # Fall through to API key

    # Try API key
    if api_key_raw:
        try:
            from api.auth import hash_api_key
            from db.connection import now_utc_iso
            from services import auth as auth_service

            key_hash = hash_api_key(api_key_raw)
            record = auth_service.lookup_active_key(key_hash)
            if record is not None and record.expires_at and now_utc_iso() > record.expires_at:
                record = None
            if record is not None:
                return {
                    "user_id": record.key_id,
                    "email": None,
                    "display_name": None,
                    "is_admin": "*" in record.scopes,
                    "auth_method": "api_key",
                    "key_hash": key_hash,
                    "scopes": record.scopes,
                }
        except Exception:
            pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Provide session cookie or X-API-Key header.",
    )
