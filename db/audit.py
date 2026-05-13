"""Registro de auditoría para acciones de usuario en el dashboard.

Las acciones se persisten en ``audit_log`` y permiten trazabilidad de
quién hizo qué sin almacenar PII directa (se usa ``user_key`` opaco y
``session_hash`` truncado).

Acciones estándar:
    ``login``              — autenticación exitosa
    ``login_failed``       — intento fallido de autenticación
    ``logout``             — cierre de sesión explícito
    ``watchlist_add``      — entrada añadida a la watchlist
    ``watchlist_delete``   — entrada eliminada de la watchlist
    ``export_excel``       — exportación a Excel
    ``export_pdf``         — exportación a PDF
"""

from __future__ import annotations

from typing import Any

from db.database import connect, now_utc_iso
from observability.logging import get_logger

log = get_logger(__name__)


def log_action(
    user_key: str,
    session_hash: str,
    action: str,
    detail: str = "",
) -> None:
    """Persiste una acción de usuario en ``audit_log``. No lanza excepciones.

    Args:
        user_key: Clave opaca del usuario (hash).
        session_hash: Hash truncado de la sesión Streamlit.
        action: Nombre de la acción (ver módulo docstring).
        detail: Información adicional en texto libre (sin PII).
    """
    try:
        with connect() as c:
            c.execute(
                "INSERT INTO audit_log (user_key, session_hash, action, detail, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_key, session_hash, action, detail, now_utc_iso()),
            )
    except Exception as exc:
        log.warning("audit_log_persist_failed", action=action, error=str(exc))


def list_recent(
    limit: int = 200,
    *,
    user_key: str | None = None,
    action: str | None = None,
) -> list[dict[str, Any]]:
    """Devuelve entradas recientes del audit log (para el panel de Observabilidad).

    Args:
        limit: Máximo de entradas a devolver.
        user_key: Filtra por usuario si se proporciona.
        action: Filtra por tipo de acción si se proporciona.
    """
    clauses: list[str] = []
    params: list[Any] = []
    if user_key:
        clauses.append("user_key = ?")
        params.append(user_key)
    if action:
        clauses.append("action = ?")
        params.append(action)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with connect() as c:
        cur = c.execute(
            f"SELECT id, user_key, session_hash, action, detail, created_at "  # noqa: S608
            f"FROM audit_log {where} ORDER BY created_at DESC LIMIT ?",
            params,
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
