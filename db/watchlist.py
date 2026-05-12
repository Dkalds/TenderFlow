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


def add_entry(entry: WatchlistEntry) -> None:
    # SQLite considera que dos NULL son distintos a efectos de UNIQUE, así que
    # la deduplicación por constraint no funciona cuando hay campos nulos.
    # Hacemos un SELECT explícito usando COALESCE para tratar NULL == NULL.
    with connect() as c:
        cur = c.execute(
            "SELECT id FROM watchlist_cpv WHERE "
            "user_key = ? AND cpv_prefix = ? "
            "AND COALESCE(keyword,'') = COALESCE(?, '') "
            "AND COALESCE(ccaa,'') = COALESCE(?, '') "
            "AND COALESCE(min_importe, -1) = COALESCE(?, -1) "
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
            "(user_key, cpv_prefix, keyword, min_importe, ccaa, email, user_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry.user_key,
                entry.cpv_prefix,
                entry.keyword,
                entry.min_importe,
                entry.ccaa,
                entry.email,
                entry.user_id,
                now_utc_iso(),
            ),
        )


def remove_entry(entry_id: int) -> None:
    with connect() as c:
        c.execute("DELETE FROM watchlist_cpv WHERE id = ?", (entry_id,))


def list_entries(user_key: str, *, user_id: int | None = None) -> list[dict[str, Any]]:
    with connect() as c:
        if user_id is not None:
            cur = c.execute(
                "SELECT id, cpv_prefix, keyword, min_importe, ccaa, email, "
                "created_at, last_notified_at, user_id "
                "FROM watchlist_cpv WHERE user_id = ? OR user_key = ? "
                "ORDER BY created_at DESC",
                (user_id, user_key),
            )
        else:
            cur = c.execute(
                "SELECT id, cpv_prefix, keyword, min_importe, ccaa, email, "
                "created_at, last_notified_at, user_id "
                "FROM watchlist_cpv WHERE user_key = ? ORDER BY created_at DESC",
                (user_key,),
            )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def update_last_notified(entry_id: int, ts: str) -> None:
    """Actualiza la marca de tiempo de última notificación para una entrada."""
    with connect() as c:
        c.execute(
            "UPDATE watchlist_cpv SET last_notified_at = ? WHERE id = ?",
            (ts, entry_id),
        )


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
