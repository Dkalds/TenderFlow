"""CRUD sobre ``watchlist_empresas`` — vigilancia de competidores.

``user_key`` es opaco (hash de email o nombre), igual que en watchlist_cpv.
El scheduler (scheduler/competitor_alerts.py) consume ``list_all`` y
actualiza ``last_notified_at`` tras cada notificación.

``organization_id`` es obligatoria y no tiene rama ``None``. La tuvo, y esa
rama era el bug de clase que documenta ``api/tenancy.py``: quien omitía el
argumento no obtenía «sin filtrar por organización» como decisión, lo
obtenía por descuido, y el repositorio caía a una query sin ámbito sin
decir nada. Ahora un llamador que la omita falla al tipar.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from db.database import connect, now_utc_iso
from db.repositories.base import rows_to_dicts


@dataclass
class WatchlistEmpresaEntry:
    """Entrada de vigilancia. ``organization_id`` va sin default a propósito.

    Con default ``None`` se podía construir una entrada sin ámbito y escribir
    una fila con organización nula, invisible después para la consulta con
    ámbito: el favorito existía y el usuario no lo veía en ninguna parte.
    """

    user_key: str
    empresa_id: int
    organization_id: int
    email: str | None = None
    frequency: str = "daily"  # 'immediate' | 'daily' | 'weekly'
    visibility: str = "private"


def add_entry(entry: WatchlistEmpresaEntry) -> int | None:
    """Añade una empresa a la watchlist del usuario. Devuelve el id o None si ya existía."""
    with connect() as c:
        existing = c.execute(
            "SELECT id FROM watchlist_empresas WHERE user_key = %s AND empresa_id = %s",
            (entry.user_key, entry.empresa_id),
        ).fetchone()
        if existing is not None:
            return None
        row = c.execute(
            "INSERT INTO watchlist_empresas "
            "(user_key, empresa_id, email, frequency, created_at, organization_id, visibility) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                entry.user_key,
                entry.empresa_id,
                entry.email,
                entry.frequency,
                now_utc_iso(),
                entry.organization_id,
                entry.visibility,
            ),
        ).fetchone()
        return int(row[0])


def remove_entry(user_key: str, empresa_id: int, organization_id: int) -> bool:
    with connect() as c:
        cur = c.execute(
            "DELETE FROM watchlist_empresas WHERE organization_id = %s "
            "AND empresa_id = %s AND (visibility = 'organization' OR user_key = %s)",
            (organization_id, empresa_id, user_key),
        )
        return bool(cur.rowcount)


def list_entries(user_key: str, organization_id: int) -> list[dict[str, Any]]:
    """Empresas vigiladas por un usuario, con nombre canónico."""
    with connect() as c:
        return rows_to_dicts(
            c.execute(
                "SELECT w.id, w.empresa_id, e.nombre_canonico, e.nif_canonico, "
                "       w.email, w.frequency, w.created_at, w.last_notified_at, "
                "       w.organization_id, w.visibility "
                "FROM watchlist_empresas w "
                "JOIN empresas e ON e.empresa_id = w.empresa_id "
                "WHERE w.organization_id = %s "
                "AND (w.visibility = 'organization' OR w.user_key = %s) "
                "ORDER BY e.nombre_canonico",
                (organization_id, user_key),
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
            "UPDATE watchlist_empresas SET last_notified_at = %s WHERE id = %s",
            (ts or now_utc_iso(), entry_id),
        )
