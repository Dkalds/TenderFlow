"""Servicio GDPR — exportación, anonimización y gestión de datos de usuario.

Centraliza las queries que usa ``api/routes/me.py`` para cumplir con el
derecho de portabilidad y el derecho al olvido (RGPD Art. 17/20).
"""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read, get_table_columns, now_utc_iso
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)


def get_user_id_from_key_id(key_id: int) -> int | None:
    """Obtiene el ``user_id`` vinculado a la API key, si la columna existe."""
    with connect_read() as c:
        try:
            cols = get_table_columns(c, "api_keys")
            if "user_id" not in cols:
                row = c.execute("SELECT id FROM users LIMIT 1").fetchone()
                return int(row[0]) if row else None
            row = c.execute(
                "SELECT user_id FROM api_keys WHERE id = ? LIMIT 1", (key_id,)
            ).fetchone()
            if row and row[0]:
                return int(row[0])
            row = c.execute("SELECT id FROM users LIMIT 1").fetchone()
            return int(row[0]) if row else None
        except Exception:
            return None


def export_api_keys(key_hash: str) -> list[dict[str, Any]]:
    """Exporta las API keys vinculadas al ``key_hash``."""
    with connect_read() as c:
        cur = c.execute(
            "SELECT name, created_at, expires_at FROM api_keys WHERE key_hash = ?",
            (key_hash,),
        )
        return rows_to_dicts(cur)


def export_watchlist(key_hash: str) -> list[dict[str, Any]]:
    """Exporta las entradas de watchlist del usuario."""
    with connect_read() as c:
        try:
            cur = c.execute(
                "SELECT * FROM watchlist WHERE user_key = ? LIMIT 5000",
                (key_hash,),
            )
            return rows_to_dicts(cur)
        except Exception:
            return []


def export_feedback() -> list[dict[str, Any]]:
    """Exporta todo el ML feedback (anónimo, sin FK a usuario)."""
    with connect_read() as c:
        cur = c.execute("SELECT * FROM ml_feedback LIMIT 10000")
        return rows_to_dicts(cur)


def export_audit_log(key_hash: str) -> list[dict[str, Any]]:
    """Exporta el audit log filtrado por ``user_key``."""
    with connect_read() as c:
        try:
            cur = c.execute(
                "SELECT * FROM audit_log WHERE user_key = ? ORDER BY created_at DESC LIMIT 1000",
                (key_hash,),
            )
            return rows_to_dicts(cur)
        except Exception:
            return []


def anonymize_user_data(key_hash: str, key_id: int) -> None:
    """Anonimiza watchlist y revoca la API key del usuario."""
    with connect() as c:
        try:
            c.execute(
                "UPDATE watchlist SET user_key = 'DELETED', name = 'DELETED' WHERE user_key = ?",
                (key_hash,),
            )
        except Exception:
            pass
        c.execute(
            "UPDATE api_keys SET is_active = 0, last_used = ? WHERE id = ?",
            (now_utc_iso(), key_id),
        )


def list_user_keys(key_id: int) -> list[dict[str, Any]]:
    """Lista las API keys del usuario (solo la key autenticada por ID)."""
    with connect_read() as c:
        try:
            cols_info = get_table_columns(c, "api_keys")
            select_cols = "id, name, created_at, is_active, scopes"
            if "prefix" in cols_info:
                select_cols += ", prefix"
            if "expires_at" in cols_info:
                select_cols += ", expires_at"
            cur = c.execute(
                f"SELECT {select_cols} FROM api_keys WHERE id = ?",  # noqa: S608
                (key_id,),
            )
            return rows_to_dicts(cur)
        except Exception as exc:
            log.warning("list_user_keys_error", error=str(exc))
            return []


def get_key_name_and_scopes(key_id: int) -> tuple[str, str] | None:
    """Obtiene nombre y scopes de una API key por ID."""
    with connect_read() as c:
        row = c.execute("SELECT name, scopes FROM api_keys WHERE id = ?", (key_id,)).fetchone()
    if not row:
        return None
    return row[0], str(row[1] or "*")


def set_key_expiry(key_id: int, expires_at: str) -> None:
    """Establece ``expires_at`` en una API key (para rotación con grace period)."""
    with connect() as c:
        cols_info = get_table_columns(c, "api_keys")
        if "expires_at" in cols_info:
            c.execute(
                "UPDATE api_keys SET expires_at = ? WHERE id = ?",
                (expires_at, key_id),
            )
