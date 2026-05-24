"""Servicio de autenticación — acceso a la tabla ``api_keys``.

Encapsula las operaciones de lectura/escritura sobre las API keys para
mantener `api/auth.py` libre de acceso directo a la BD. Mantiene la
compatibilidad con esquemas legacy (columnas ``expires_at`` / ``scopes`` /
``user_id`` / ``prefix`` opcionales) inspeccionando ``PRAGMA table_info``
cuando el backend lo soporta.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from db.database import connect, connect_read, get_table_columns, now_utc_iso
from observability.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class ApiKeyRecord:
    """Datos públicos de una API key autenticada."""

    key_id: int
    expires_at: str | None
    scopes: str


def _api_keys_columns(conn: Any) -> set[str]:
    """Devuelve el conjunto de columnas presentes en ``api_keys``.

    Usa ``get_table_columns`` que funciona tanto en SQLite local (PRAGMA) como
    en Turso/Hrana (fallback a cursor.description).
    """
    return get_table_columns(conn, "api_keys")


def lookup_active_key(key_hash: str) -> ApiKeyRecord | None:
    """Devuelve el registro activo cuya ``key_hash`` coincide, o ``None``."""
    with connect_read() as c:
        cols = _api_keys_columns(c)
        select_parts = ["id"]
        select_parts.append("expires_at" if "expires_at" in cols else "NULL")
        select_parts.append("scopes" if "scopes" in cols else "'*'")
        row = c.execute(
            "SELECT " + ", ".join(select_parts) + " FROM api_keys "
            "WHERE key_hash = ? AND is_active = 1",
            (key_hash,),
        ).fetchone()
    if row is None:
        return None
    return ApiKeyRecord(
        key_id=int(row[0]),
        expires_at=row[1],
        scopes=str(row[2]) if row[2] else "*",
    )


def get_stored_hash(key_id: int) -> str | None:
    """Devuelve el ``key_hash`` almacenado para validación en tiempo constante.

    Raises:
        Exception: Re-raises any DB error after logging so callers can
        distinguish "key not found" (``None``) from "DB unavailable".
    """
    try:
        with connect_read() as c:
            row = c.execute("SELECT key_hash FROM api_keys WHERE id = ?", (key_id,)).fetchone()
    except Exception as exc:
        log.error("get_stored_hash_db_error", key_id=key_id, error=str(exc))
        raise
    return str(row[0]) if row else None


def update_last_used(key_id: int) -> None:
    """Actualiza ``last_used`` best-effort (silencia errores transitorios)."""
    try:
        with connect() as c:
            c.execute(
                "UPDATE api_keys SET last_used = ? WHERE id = ?",
                (now_utc_iso(), key_id),
            )
    except Exception as exc:
        log.debug("api_key_last_used_update_failed", key_id=key_id, error=str(exc))


def insert_api_key(
    *,
    key_hash: str,
    name: str,
    scopes: str,
    prefix: str,
    user_id: int | None,
    expires_at: str | None,
) -> None:
    """Inserta una nueva API key respetando las columnas presentes."""
    now = now_utc_iso()
    with connect() as c:
        cols = _api_keys_columns(c)
        fields = ["key_hash", "name", "created_at", "is_active"]
        values: list[Any] = [key_hash, name, now, 1]

        if "scopes" in cols:
            fields.append("scopes")
            values.append(scopes)
        if "user_id" in cols:
            fields.append("user_id")
            values.append(user_id)
        if "prefix" in cols:
            fields.append("prefix")
            values.append(prefix)
        if "expires_at" in cols and expires_at is not None:
            fields.append("expires_at")
            values.append(expires_at)

        placeholders = ",".join("?" * len(fields))
        c.execute(
            "INSERT INTO api_keys (" + ", ".join(fields) + ") VALUES (" + placeholders + ")",
            values,
        )


def get_active_scopes(key_hash: str) -> str | None:
    """Devuelve el string de scopes de una key activa, o ``None`` si no existe.

    Versión ligera para validaciones síncronas (p. ej. middleware /metrics)
    donde no se necesita el registro completo.
    """
    try:
        with connect_read() as c:
            row = c.execute(
                "SELECT scopes FROM api_keys WHERE key_hash = ? AND is_active = 1",
                (key_hash,),
            ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    return str(row[0]) if row[0] is not None else "*"


def deactivate_key(key_hash: str) -> bool:
    """Desactiva una key por su hash. Devuelve ``True`` si afectó alguna fila."""
    with connect() as c:
        cur = c.execute(
            "UPDATE api_keys SET is_active = 0 WHERE key_hash = ?",
            (key_hash,),
        )
        return bool(cur.rowcount)
