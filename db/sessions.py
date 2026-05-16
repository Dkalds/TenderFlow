"""Gestión de sesiones server-side con revocación.

Tabla ``sessions``:
  token_hash  TEXT PK     — SHA-256 del token raw (nunca almacenar el token)
  user_id     INTEGER     — FK a users
  created_at  TEXT
  expires_at  TEXT
  ip          TEXT
  user_agent  TEXT
  revoked     INTEGER     — 0/1
  revoked_at  TEXT
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from db.database import connect, now_utc_iso

_SESSION_TTL_HOURS = 24 * 7  # 7 días por defecto


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(
    user_id: int,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
    ttl_hours: int = _SESSION_TTL_HOURS,
) -> str:
    """Crea una nueva sesión y devuelve el token raw (guardar en cookie)."""
    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    now = datetime.now(UTC)
    expires = now + timedelta(hours=ttl_hours)

    with connect() as c:
        c.execute(
            "INSERT INTO sessions "
            "(token_hash, user_id, created_at, expires_at, ip, user_agent, revoked) "
            "VALUES (?, ?, ?, ?, ?, ?, 0)",
            (
                token_hash,
                user_id,
                now.isoformat(),
                expires.isoformat(),
                ip,
                (user_agent or "")[:512],
            ),
        )
    return token


def validate_session(token: str) -> dict[str, Any] | None:
    """Verifica token, devuelve datos de sesión o None si inválida/expirada."""
    token_hash = _hash_token(token)
    with connect() as c:
        row = c.execute(
            "SELECT user_id, expires_at, revoked, ip FROM sessions WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
    if row is None:
        return None
    user_id, expires_at, revoked, ip = row
    if revoked:
        return None
    try:
        exp = datetime.fromisoformat(expires_at)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
        if datetime.now(UTC) > exp:
            return None
    except Exception:
        return None
    return {"user_id": user_id, "expires_at": expires_at, "ip": ip}


def revoke_session(token: str) -> None:
    """Revoca una sesión específica (logout)."""
    token_hash = _hash_token(token)
    with connect() as c:
        c.execute(
            "UPDATE sessions SET revoked = 1, revoked_at = ? WHERE token_hash = ?",
            (now_utc_iso(), token_hash),
        )


def revoke_all_sessions(user_id: int) -> int:
    """Revoca todas las sesiones activas de un usuario (logout-all). Devuelve N."""
    with connect() as c:
        cur = c.execute(
            "UPDATE sessions SET revoked = 1, revoked_at = ? WHERE user_id = ? AND revoked = 0",
            (now_utc_iso(), user_id),
        )
        return cur.rowcount if hasattr(cur, "rowcount") else 0


def purge_expired_sessions() -> int:
    """Elimina sesiones expiradas/revocadas. Llamar en mantenimiento periódico."""
    cutoff = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    with connect() as c:
        cur = c.execute(
            "DELETE FROM sessions WHERE expires_at < ? OR revoked = 1",
            (cutoff,),
        )
        return cur.rowcount if hasattr(cur, "rowcount") else 0


def list_active_sessions(user_id: int) -> list[dict[str, Any]]:
    """Lista sesiones activas y no expiradas de un usuario."""
    now = datetime.now(UTC).isoformat()
    with connect() as c:
        cur = c.execute(
            "SELECT token_hash, created_at, expires_at, ip, user_agent "
            "FROM sessions "
            "WHERE user_id = ? AND revoked = 0 AND expires_at > ? "
            "ORDER BY created_at DESC",
            (user_id, now),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
