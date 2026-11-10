"""CRUD ligero sobre ``watchlist_cpv`` para alertas personalizadas por usuario.

Desde v181 (ADR-030 fase 3) el usuario se identifica por ``user_id``. La fila
es suya por ese id o, si el backfill no pudo resolverlo, por la clave legada
que ``clave_legada_de_usuario(user_id)`` calcula en la base con su correo
actual: ningún llamador conoce ya la clave. Es lo que hace que cambiar de
correo no pierda la watchlist. La columna ``user_key`` se sigue escribiendo
(opaca, hash del correo: no almacenamos PII directa); retirarla va por RFC.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from db.database import connect, now_utc_iso
from shared.types import JsonDict

#: Predicado de identidad. Parámetros: ``(user_id, user_id)``. Una fila con OTRO
#: id y la misma clave no es tuya; ver ``db/repositories/watchlist.py``.
_IDENT = "(user_id = %s OR (user_id IS NULL AND user_key = clave_legada_de_usuario(%s)))"


@dataclass
class WatchlistEntry:
    user_id: int
    cpv_prefix: str
    keyword: str | None = None
    min_importe: float | None = None
    ccaa: str | None = None
    email: str | None = None
    frequency: str = "daily"  # 'immediate' | 'daily' | 'weekly'
    organization_id: int | None = None
    visibility: str = "private"


def add_entry(entry: WatchlistEntry) -> None:
    # SQLite considera que dos NULL son distintos a efectos de UNIQUE, así que
    # la deduplicación por constraint no funciona cuando hay campos nulos.
    # Hacemos un SELECT explícito usando COALESCE para tratar NULL == NULL.
    # La identidad del SELECT incluye la clave legada: tras un cambio de correo,
    # la misma entrada bajo la clave antigua sigue contando como «ya existe».
    with connect() as c:
        cur = c.execute(
            "SELECT id FROM watchlist_cpv WHERE "
            f"{_IDENT} AND cpv_prefix = %s "
            "AND COALESCE(keyword,'') = COALESCE(%s, '') "
            "AND COALESCE(ccaa,'') = COALESCE(%s, '') "
            "AND COALESCE(min_importe, -1) = COALESCE(%s, -1) "
            "LIMIT 1",
            (
                entry.user_id,
                entry.user_id,
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
            "VALUES (clave_legada_de_usuario(%s), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                entry.user_id,
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


def remove_entry(entry_id: int, user_id: int) -> bool:
    """Elimina una entrada propia. ``True`` si borró algo.

    ``user_id`` no es opcional a propósito: sin él, un ``id`` adivinado
    borraría la entrada de cualquier otro usuario. La ruta que llame puede
    validar propiedad por su cuenta, pero el repositorio no delega esa
    comprobación — es la clase de IDOR latente que
    ``tests/test_user_key_sql_isolation.py`` audita.
    """
    with connect() as c:
        cur = c.execute(
            f"DELETE FROM watchlist_cpv WHERE id = %s AND {_IDENT}",
            (entry_id, user_id, user_id),
        )
        return bool(cur.rowcount > 0)


#: Columnas que ``list_entries`` y ``list_entries_por_clave`` devuelven.
_COLS_PROPIAS = (
    "id, cpv_prefix, keyword, min_importe, ccaa, email, "
    "created_at, last_notified_at, user_id, "
    "COALESCE(frequency, 'daily') AS frequency"
)


def list_entries_por_clave(user_key: str) -> list[JsonDict]:
    """Entradas guardadas bajo una ``user_key`` literal, sin resolver ningún usuario.

    Solo para el job de alertas de instancia (``scheduler/watchlist_alerts.py``),
    que corre sin sesión ni ``user_id``: su dueño es la clave de
    ``shared.user_key.user_key()`` (una sola persona, derivada de la
    configuración local) y no pertenece a ninguna fila de ``users``. Cualquier
    otro llamador tiene un ``user_id`` y usa :func:`list_entries`.
    """
    with connect() as c:
        cur = c.execute(
            f"SELECT {_COLS_PROPIAS} FROM watchlist_cpv WHERE user_key = %s "
            "ORDER BY created_at DESC",
            (user_key,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def list_entries(
    user_id: int,
    *,
    organization_id: int | None = None,
) -> list[dict[str, Any]]:
    with connect() as c:
        if organization_id is not None:
            cur = c.execute(
                f"SELECT {_COLS_PROPIAS}, organization_id, visibility "
                "FROM watchlist_cpv WHERE organization_id = %s "
                f"AND (visibility = 'organization' OR {_IDENT}) "
                "ORDER BY created_at DESC",
                (organization_id, user_id, user_id),
            )
        else:
            cur = c.execute(
                f"SELECT {_COLS_PROPIAS} "
                f"FROM watchlist_cpv WHERE {_IDENT} "
                "ORDER BY created_at DESC",
                (user_id, user_id),
            )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def entradas_por_id(ids: Sequence[int]) -> list[JsonDict]:
    """Entradas por id, con dueño, correo y frecuencia (las que sigan existiendo).

    La lee el despachador al repartir ``watchlist_match``: el correo no viaja
    en el evento, que se guarda para siempre.
    """
    if not ids:
        return []
    with connect() as c:
        cur = c.execute(
            "SELECT id, user_key, user_id, email, cpv_prefix, keyword, min_importe, ccaa, "
            "COALESCE(frequency, 'daily') AS frequency "
            "FROM watchlist_cpv WHERE id = ANY(%s) ORDER BY id",
            (list(ids),),
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


def update_frequency(entry_id: int, frequency: str, user_id: int) -> bool:
    """Actualiza la frecuencia de notificación de una entrada propia.

    Args:
        entry_id: ID de la entrada.
        frequency: 'immediate' | 'daily' | 'weekly'
        user_id: Dueño de la entrada. Obligatorio por el mismo motivo que en
            :func:`remove_entry`.

    Returns:
        ``True`` si actualizó alguna fila.
    """
    if frequency not in ("immediate", "daily", "weekly"):
        raise ValueError(f"frequency debe ser 'immediate', 'daily' o 'weekly', no {frequency!r}")
    with connect() as c:
        cur = c.execute(
            f"UPDATE watchlist_cpv SET frequency = %s WHERE id = %s AND {_IDENT}",
            (frequency, entry_id, user_id, user_id),
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
