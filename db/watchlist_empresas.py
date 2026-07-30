"""CRUD sobre ``watchlist_empresas`` — vigilancia de competidores.

``user_key`` es opaco (hash de email o nombre), igual que en watchlist_cpv.
El scheduler (scheduler/competitor_alerts.py) consume ``list_all`` y
actualiza ``last_notified_at`` tras cada notificación.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from db.database import connect, now_utc_iso
from db.repositories.base import rows_to_dicts


@dataclass
class WatchlistEmpresaEntry:
    user_key: str
    empresa_id: int
    email: str | None = None
    frequency: str = "daily"  # 'immediate' | 'daily' | 'weekly'
    organization_id: int | None = None
    visibility: str = "private"


def add_entry(entry: WatchlistEmpresaEntry) -> int | None:
    """Añade una empresa a la watchlist del usuario. Devuelve el id o None si ya existía."""
    with connect() as c:
        existing = c.execute(
            "SELECT id FROM watchlist_empresas WHERE user_key = ? AND empresa_id = ?",
            (entry.user_key, entry.empresa_id),
        ).fetchone()
        if existing is not None:
            return None
        cur = c.execute(
            "INSERT INTO watchlist_empresas "
            "(user_key, empresa_id, email, frequency, created_at, organization_id, visibility) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                entry.user_key,
                entry.empresa_id,
                entry.email,
                entry.frequency,
                now_utc_iso(),
                entry.organization_id,
                entry.visibility,
            ),
        )
        return int(cur.lastrowid)


def remove_entry(
    user_key: str, empresa_id: int, organization_id: int | None = None
) -> bool:
    with connect() as c:
        if organization_id is None:
            cur = c.execute(
                "DELETE FROM watchlist_empresas WHERE user_key = ? AND empresa_id = ?",
                (user_key, empresa_id),
            )
        else:
            cur = c.execute(
                "DELETE FROM watchlist_empresas WHERE organization_id = ? "
                "AND empresa_id = ? AND (visibility = 'organization' OR user_key = ?)",
                (organization_id, empresa_id, user_key),
            )
        return bool(cur.rowcount)


def list_entries(
    user_key: str, organization_id: int | None = None
) -> list[dict[str, Any]]:
    """Empresas vigiladas por un usuario, con nombre canónico."""
    with connect() as c:
        if organization_id is None:
            where = "w.user_key = ?"
            params: tuple[Any, ...] = (user_key,)
        else:
            where = (
                "w.organization_id = ? AND "
                "(w.visibility = 'organization' OR w.user_key = ?)"
            )
            params = (organization_id, user_key)
        return rows_to_dicts(
            c.execute(
                "SELECT w.id, w.empresa_id, e.nombre_canonico, e.nif_canonico, "
                "       w.email, w.frequency, w.created_at, w.last_notified_at, "
                "       w.organization_id, w.visibility "
                "FROM watchlist_empresas w "
                "JOIN empresas e ON e.empresa_id = w.empresa_id "
                "WHERE " + where + " ORDER BY e.nombre_canonico",
                params,
            )
        )


def list_all() -> list[dict[str, Any]]:
    """Todas las entradas con destinatario — para el job de alertas."""
    with connect() as c:
        return rows_to_dicts(
            c.execute(
                "SELECT w.id, w.user_key, w.empresa_id, e.nombre_canonico, "
                "       w.email, w.frequency, w.last_notified_at "
                "FROM watchlist_empresas w "
                "JOIN empresas e ON e.empresa_id = w.empresa_id "
                "WHERE w.email IS NOT NULL AND w.email != ''"
            )
        )


def update_last_notified(entry_id: int, ts: str | None = None) -> None:
    with connect() as c:
        c.execute(
            "UPDATE watchlist_empresas SET last_notified_at = ? WHERE id = ?",
            (ts or now_utc_iso(), entry_id),
        )
