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
from observability.logging import get_logger

log = get_logger(__name__)

_SESSION_TTL_HOURS = 24
_SESSION_IDLE_MINUTES = 30
# Cada request autenticada refrescaba ``last_seen_at``. Con un umbral de
# inactividad de 30 minutos, escribir en cada petición no aporta precisión: solo
# convierte toda lectura autenticada en una escritura. Se refresca como mucho
# una vez por minuto.
_LAST_SEEN_THROTTLE_SECONDS = 60


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _as_utc(value: str) -> datetime:
    """Parsea un timestamp ISO de la BD como datetime aware en UTC."""
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


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
            "(token_hash, user_id, created_at, expires_at, ip, user_agent, last_seen_at, revoked) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 0)",
            (
                token_hash,
                user_id,
                now.isoformat(),
                expires.isoformat(),
                ip,
                (user_agent or "")[:512],
                now.isoformat(),
            ),
        )
    return token


def validate_session(token: str) -> dict[str, Any] | None:
    """Verifica token, devuelve datos de sesión o None si inválida/expirada."""
    token_hash = _hash_token(token)
    with connect() as c:
        row = c.execute(
            "SELECT user_id, created_at, expires_at, revoked, ip, last_seen_at, mfa_verified_at "
            "FROM sessions WHERE token_hash = %s",
            (token_hash,),
        ).fetchone()
    if row is None:
        return None
    user_id, created_at, expires_at, revoked, ip, last_seen_at, mfa_verified_at = row
    if revoked:
        return None
    try:
        exp = datetime.fromisoformat(expires_at)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
        now = datetime.now(UTC)
        if now > exp:
            return None
        last_seen = datetime.fromisoformat(last_seen_at) if last_seen_at else None
        if last_seen is not None:
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=UTC)
            if now - last_seen > timedelta(minutes=_SESSION_IDLE_MINUTES):
                revoke_session(token)
                return None
    except Exception:
        # Camino de autenticación: sin log, un fallo de BD se presenta al
        # usuario como "sesión inválida" y nadie puede distinguirlo de un
        # token realmente caducado.
        log.warning("session_validation_failed", exc_info=True)
        return None
    with connect() as c:
        c.execute(
            "UPDATE sessions SET last_seen_at = %s WHERE token_hash = %s AND revoked = 0",
            (now.isoformat(), token_hash),
        )
    return {
        "user_id": user_id,
        "authenticated_at": created_at,
        "expires_at": expires_at,
        "ip": ip,
        "mfa_verified_at": mfa_verified_at,
    }


def validate_session_principal(token: str) -> dict[str, Any] | None:
    """Valida la sesión y devuelve sesión + usuario + estado MFA en UNA consulta.

    Es el camino que recorre **toda** petición autenticada por cookie del SPA.
    Componerlo con ``validate_session`` + ``get_user_by_id`` +
    ``is_totp_required`` costaba de 3 a 5 aperturas de conexión en serie, cada
    una con su transacción de escritura: a los ~80 ms de RTT contra Supabase,
    varias décimas de segundo gastadas antes de empezar el trabajo real de la
    petición. Aquí es un SELECT con dos LEFT JOIN.

    Además lee ``totp_secrets.confirmed`` sin descifrar el secreto:
    ``is_totp_required`` pasaba por ``get_totp_secret``, que descifra el TOTP
    entero para acabar mirando un booleano.

    Devuelve ``None`` si la sesión no existe, está revocada, expiró, lleva
    inactiva más de ``_SESSION_IDLE_MINUTES`` (en cuyo caso la revoca) o su
    usuario está desactivado. El llamador no distingue entre esos casos a
    propósito: todos son "sesión inválida" y detallarlos filtra si la cuenta
    existe.
    """
    token_hash = _hash_token(token)
    now = datetime.now(UTC)

    with connect() as c:
        row = c.execute(
            "SELECT s.user_id, s.created_at, s.expires_at, s.revoked, s.ip, "
            "       s.last_seen_at, s.mfa_verified_at, "
            "       u.id, u.email, u.display_name, u.is_admin, u.deactivated_at, "
            "       COALESCE(t.confirmed, 0) "
            "FROM sessions s "
            "LEFT JOIN users u ON u.id = s.user_id "
            "LEFT JOIN totp_secrets t ON t.user_id = s.user_id "
            "WHERE s.token_hash = %s",
            (token_hash,),
        ).fetchone()
        if row is None:
            return None

        (
            user_id,
            created_at,
            expires_at,
            revoked,
            ip,
            last_seen_at,
            mfa_verified_at,
            u_id,
            email,
            display_name,
            is_admin,
            deactivated_at,
            totp_confirmed,
        ) = row

        if revoked:
            return None

        try:
            expired = now > _as_utc(expires_at)
            last_seen = _as_utc(last_seen_at) if last_seen_at else None
        except Exception:
            # Camino de autenticación: un fallo al interpretar las marcas de
            # tiempo se presenta como "sesión inválida", indistinguible para el
            # usuario de un token caducado. Queda constancia en el log.
            log.warning("session_validation_failed", exc_info=True)
            return None

        if expired:
            return None

        if last_seen is not None and now - last_seen > timedelta(minutes=_SESSION_IDLE_MINUTES):
            c.execute(
                "UPDATE sessions SET revoked = 1, revoked_at = %s WHERE token_hash = %s",
                (now.isoformat(), token_hash),
            )
            return None

        # Usuario inexistente o desactivado: la sesión ya no vale.
        if u_id is None or deactivated_at is not None:
            return None

        stale = (
            last_seen is None
            or (now - last_seen).total_seconds() >= _LAST_SEEN_THROTTLE_SECONDS
        )
        if stale:
            c.execute(
                "UPDATE sessions SET last_seen_at = %s WHERE token_hash = %s AND revoked = 0",
                (now.isoformat(), token_hash),
            )

    return {
        "user_id": user_id,
        "authenticated_at": created_at,
        "expires_at": expires_at,
        "ip": ip,
        "mfa_verified_at": mfa_verified_at,
        "id": u_id,
        "email": email,
        "display_name": display_name,
        "is_admin": bool(is_admin),
        "mfa_required": bool(totp_confirmed),
    }


def mark_session_mfa_verified(token: str) -> None:
    """Eleva la sesión actual tras verificar un segundo factor."""
    token_hash = _hash_token(token)
    with connect() as c:
        c.execute(
            "UPDATE sessions SET mfa_verified_at = %s WHERE token_hash = %s AND revoked = 0",
            (now_utc_iso(), token_hash),
        )


def revoke_session(token: str) -> None:
    """Revoca una sesión específica (logout)."""
    token_hash = _hash_token(token)
    with connect() as c:
        c.execute(
            "UPDATE sessions SET revoked = 1, revoked_at = %s WHERE token_hash = %s",
            (now_utc_iso(), token_hash),
        )


def revoke_all_sessions(user_id: int) -> int:
    """Revoca todas las sesiones activas de un usuario (logout-all). Devuelve N."""
    with connect() as c:
        cur = c.execute(
            "UPDATE sessions SET revoked = 1, revoked_at = %s WHERE user_id = %s AND revoked = 0",
            (now_utc_iso(), user_id),
        )
        return cur.rowcount if hasattr(cur, "rowcount") else 0


def purge_expired_sessions() -> int:
    """Elimina sesiones expiradas/revocadas. Llamar en mantenimiento periódico."""
    cutoff = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    with connect() as c:
        cur = c.execute(
            "DELETE FROM sessions WHERE expires_at < %s OR revoked = 1",
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
            "WHERE user_id = %s AND revoked = 0 AND expires_at > %s "
            "ORDER BY created_at DESC",
            (user_id, now),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
