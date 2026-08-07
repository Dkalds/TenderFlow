"""CRUD ligero sobre ``watchlist_cpv`` para alertas personalizadas por usuario.

``user_key`` es opaco (hash de email o nombre). No almacenamos PII directa.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from db.database import connect, now_utc_iso


@dataclass
class WatchlistEntry:
    user_key: str
    cpv_prefix: str
    keyword: str | None = None
    min_importe: float | None = None
    ccaa: str | None = None
    email: str | None = None
    user_id: int | None = None
    frequency: str = "daily"  # 'immediate' | 'daily' | 'weekly'
    organization_id: int | None = None
    visibility: str = "private"


def add_entry(entry: WatchlistEntry) -> None:
    # SQLite considera que dos NULL son distintos a efectos de UNIQUE, así que
    # la deduplicación por constraint no funciona cuando hay campos nulos.
    # Hacemos un SELECT explícito usando COALESCE para tratar NULL == NULL.
    with connect() as c:
        cur = c.execute(
            "SELECT id FROM watchlist_cpv WHERE "
            "user_key = %s AND cpv_prefix = %s "
            "AND COALESCE(keyword,'') = COALESCE(%s, '') "
            "AND COALESCE(ccaa,'') = COALESCE(%s, '') "
            "AND COALESCE(min_importe, -1) = COALESCE(%s, -1) "
            "LIMIT 1",
            (
                entry.user_key,
                entry.cpv_prefix,
                entry.keyword,
                entry.ccaa,
                entry.min_importe,
            ),
        )
        if cur.fetchone() is not None:
            return
        c.execute(
            "INSERT INTO watchlist_cpv "
            "(user_key, cpv_prefix, keyword, min_importe, ccaa, email, user_id, "
            " frequency, created_at, organization_id, visibility) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                entry.user_key,
                entry.cpv_prefix,
                entry.keyword,
                entry.min_importe,
                entry.ccaa,
                entry.email,
                entry.user_id,
                entry.frequency,
                now_utc_iso(),
                entry.organization_id,
                entry.visibility,
            ),
        )


def remove_entry(entry_id: int, user_key: str) -> bool:
    """Elimina una entrada propia. ``True`` si borró algo.

    ``user_key`` no es opcional a propósito: sin él, un ``id`` adivinado
    borraría la entrada de cualquier otro usuario. La ruta que llame puede
    validar propiedad por su cuenta, pero el repositorio no delega esa
    comprobación — es la clase de IDOR latente que
    ``tests/test_user_key_sql_isolation.py`` audita.
    """
    with connect() as c:
        cur = c.execute(
            "DELETE FROM watchlist_cpv WHERE id = %s AND user_key = %s",
            (entry_id, user_key),
        )
        return bool(cur.rowcount > 0)


def list_entries(
    user_key: str,
    *,
    user_id: int | None = None,
    organization_id: int | None = None,
) -> list[dict[str, Any]]:
    with connect() as c:
        if organization_id is not None:
            cur = c.execute(
                "SELECT id, cpv_prefix, keyword, min_importe, ccaa, email, "
                "created_at, last_notified_at, user_id, "
                "COALESCE(frequency, 'daily') AS frequency, organization_id, visibility "
                "FROM watchlist_cpv WHERE organization_id = %s "
                "AND (visibility = 'organization' OR user_id = %s OR user_key = %s) "
                "ORDER BY created_at DESC",
                (organization_id, user_id, user_key),
            )
        elif user_id is not None:
            cur = c.execute(
                "SELECT id, cpv_prefix, keyword, min_importe, ccaa, email, "
                "created_at, last_notified_at, user_id, "
                "COALESCE(frequency, 'daily') AS frequency "
                "FROM watchlist_cpv WHERE user_id = %s OR user_key = %s "
                "ORDER BY created_at DESC",
                (user_id, user_key),
            )
        else:
            cur = c.execute(
                "SELECT id, cpv_prefix, keyword, min_importe, ccaa, email, "
                "created_at, last_notified_at, user_id, "
                "COALESCE(frequency, 'daily') AS frequency "
                "FROM watchlist_cpv WHERE user_key = %s ORDER BY created_at DESC",
                (user_key,),
            )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def update_last_notified(entry_id: int, ts: str) -> None:
    """Actualiza la marca de tiempo de última notificación para una entrada."""
    with connect() as c:
        c.execute(
            "UPDATE watchlist_cpv SET last_notified_at = %s WHERE id = %s",
            (ts, entry_id),
        )


def update_frequency(entry_id: int, frequency: str, user_key: str) -> bool:
    """Actualiza la frecuencia de notificación de una entrada propia.

    Args:
        entry_id: ID de la entrada.
        frequency: 'immediate' | 'daily' | 'weekly'
        user_key: Dueño de la entrada. Obligatorio por el mismo motivo que en
            :func:`remove_entry`.

    Returns:
        ``True`` si actualizó alguna fila.
    """
    if frequency not in ("immediate", "daily", "weekly"):
        raise ValueError(f"frequency debe ser 'immediate', 'daily' o 'weekly', no {frequency!r}")
    with connect() as c:
        cur = c.execute(
            "UPDATE watchlist_cpv SET frequency = %s WHERE id = %s AND user_key = %s",
            (frequency, entry_id, user_key),
        )
        return bool(cur.rowcount > 0)


def matches_licitacion(entry: dict[str, Any], licitacion: dict[str, Any]) -> bool:
    """True si la licitación encaja con la entrada de watchlist."""
    cpv = str(licitacion.get("cpv") or "")
    if entry.get("cpv_prefix") and not cpv.startswith(entry["cpv_prefix"]):
        return False
    kw = (entry.get("keyword") or "").strip().lower()
    if kw:
        blob = " ".join(str(licitacion.get(k) or "") for k in ("titulo", "descripcion")).lower()
        if kw not in blob:
            return False
    if entry.get("min_importe") is not None:
        imp = licitacion.get("importe") or 0
        try:
            if float(imp) < float(entry["min_importe"]):
                return False
        except (TypeError, ValueError):
            return False
    return not (
        entry.get("ccaa") and str(licitacion.get("ccaa") or "").lower() != entry["ccaa"].lower()
    )
