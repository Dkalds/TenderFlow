"""Servicio de autenticación — acceso a la tabla ``api_keys``.

Encapsula las operaciones de lectura/escritura sobre las API keys para
mantener `api/auth.py` libre de acceso directo a la BD. Mantiene la
compatibilidad con esquemas legacy (columnas ``expires_at`` / ``scopes`` /
``user_id`` / ``prefix`` opcionales) inspeccionando ``PRAGMA table_info``
cuando el backend lo soporta.
"""

from __future__ import annotations

from dataclasses import dataclass

from db.repositories.api_keys import ApiKeyRepository
from observability.logging import get_logger

log = get_logger(__name__)

_repo = ApiKeyRepository()


@dataclass(frozen=True)
class ApiKeyRecord:
    """Datos públicos de una API key autenticada."""

    key_id: int
    user_id: int | None
    expires_at: str | None
    scopes: str


def lookup_active_key(key_hash: str) -> ApiKeyRecord | None:
    """Devuelve el registro activo cuya ``key_hash`` coincide, o ``None``."""
    row = _repo.get_by_hash(key_hash)
    if row is None:
        return None
    return ApiKeyRecord(
        key_id=int(row["id"]),
        user_id=int(row["user_id"]) if row.get("user_id") is not None else None,
        expires_at=row.get("expires_at"),
        scopes=str(row.get("scopes") or "*"),
    )


def get_stored_hash(key_id: int) -> str | None:
    """Devuelve el ``key_hash`` almacenado para validación en tiempo constante.

    Raises:
        Exception: Re-raises any DB error after logging so callers can
        distinguish "key not found" (``None``) from "DB unavailable".
    """
    try:
        return _repo.get_stored_hash(key_id)
    except Exception as exc:
        log.error("get_stored_hash_db_error", key_id=key_id, error=str(exc))
        raise


def update_last_used(key_id: int) -> None:
    """Actualiza ``last_used`` best-effort (silencia errores transitorios)."""
    try:
        _repo.update_last_used(key_id)
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
    _repo.insert(
        key_hash=key_hash,
        name=name,
        scopes=scopes,
        prefix=prefix,
        user_id=user_id,
        expires_at=expires_at,
    )


def get_active_scopes(key_hash: str) -> str | None:
    """Devuelve el string de scopes de una key activa, o ``None`` si no existe.

    Versión ligera para validaciones síncronas (p. ej. middleware /metrics)
    donde no se necesita el registro completo.
    """
    return _repo.get_active_scopes(key_hash)


def deactivate_key(key_hash: str) -> bool:
    """Desactiva una key por su hash. Devuelve ``True`` si afectó alguna fila."""
    return _repo.revoke(key_hash)
