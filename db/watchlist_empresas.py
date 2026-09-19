"""CRUD sobre ``watchlist_empresas`` — vigilancia de competidores.

``user_key`` es opaco (hash de email o nombre), igual que en watchlist_cpv.
El scheduler (scheduler/competitor_alerts.py) consume ``list_all`` y
actualiza ``last_notified_at`` tras cada notificación.

``organization_id`` es obligatoria y no tiene rama ``None``. La tuvo, y esa
rama era el bug de clase que documenta ``api/tenancy.py``: quien omitía el
argumento no obtenía «sin filtrar por organización» como decisión, lo
obtenía por descuido, y el repositorio caía a una query sin ámbito sin
decir nada. Ahora un llamador que la omita falla al tipar.

Desde v129 (ADR-030 fase 2) la fila lleva también ``user_id`` y la lectura es
dual: ver ``db/repositories/watchlist.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts
from db.sql_fragments import iso_guard

#: Predicado de identidad dual. Parámetros: ``(user_id, user_key, user_id)``.
_IDENT = "(user_id = %s OR (user_key = %s AND (user_id IS NULL OR %s::int IS NULL)))"
_IDENT_W = "(w.user_id = %s OR (w.user_key = %s AND (w.user_id IS NULL OR %s::int IS NULL)))"


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
    user_id: int | None = None


def add_entry(entry: WatchlistEmpresaEntry) -> int | None:
    """Añade una empresa a la watchlist del usuario. Devuelve el id o None si ya existía."""
    with connect() as c:
        existing = c.execute(
            f"SELECT id FROM watchlist_empresas WHERE {_IDENT} AND empresa_id = %s",
            (entry.user_id, entry.user_key, entry.user_id, entry.empresa_id),
        ).fetchone()
        if existing is not None:
            return None
        row = c.execute(
            "INSERT INTO watchlist_empresas "
            "(user_key, user_id, empresa_id, email, frequency, created_at, "
            " organization_id, visibility) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                entry.user_key,
                entry.user_id,
                entry.empresa_id,
                entry.email,
                entry.frequency,
                now_utc_iso(),
                entry.organization_id,
                entry.visibility,
            ),
        ).fetchone()
        nuevo_id = int(row[0])

    # Escritura doble hacia `follows` (ADR-031 §B, fase aditiva). `target_id` es
    # texto porque el objetivo es polimórfico; no lanza nunca, por lo mismo que
    # en `db/radar_dismissals.py`.
    from db.repositories import follows as _follows

    _follows.registrar(
        user_key=entry.user_key,
        user_id=entry.user_id,
        organization_id=entry.organization_id,
        target_type="empresa",
        target_id=str(entry.empresa_id),
        visibility=entry.visibility,
    )
    return nuevo_id


def remove_entry(
    user_key: str, empresa_id: int, organization_id: int, *, user_id: int | None = None
) -> bool:
    with connect() as c:
        cur = c.execute(
            "DELETE FROM watchlist_empresas WHERE organization_id = %s "
            f"AND empresa_id = %s AND (visibility = 'organization' OR {_IDENT})",
            (organization_id, empresa_id, user_id, user_key, user_id),
        )
        borrado = bool(cur.rowcount)

    from db.repositories import follows as _follows

    _follows.olvidar(
        user_key=user_key,
        user_id=user_id,
        target_type="empresa",
        target_id=str(empresa_id),
    )
    return borrado


def list_entries(
    user_key: str, organization_id: int, *, user_id: int | None = None
) -> list[dict[str, Any]]:
    """Empresas vigiladas por un usuario, con nombre canónico.

    Con ``FOLLOWS_LECTURA`` encendido la pertenencia sale de ``follows``
    (ADR-031 §B, fase 2) y esta tabla sólo aporta correo, frecuencia y último
    aviso: ver :func:`db.repositories.follows.empresas_desde_follows`.
    """
    from db.repositories import follows as _follows

    if _follows.lectura_desde_follows():
        return _follows.empresas_desde_follows(user_key, organization_id, user_id=user_id)
    with connect() as c:
        return rows_to_dicts(
            c.execute(
                "SELECT w.id, w.empresa_id, e.nombre_canonico, e.nif_canonico, "
                "       w.email, w.frequency, w.created_at, w.last_notified_at, "
                "       w.organization_id, w.visibility "
                "FROM watchlist_empresas w "
                "JOIN empresas e ON e.empresa_id = w.empresa_id "
                "WHERE w.organization_id = %s "
                f"AND (w.visibility = 'organization' OR {_IDENT_W}) "
                "ORDER BY e.nombre_canonico",
                (organization_id, user_id, user_key, user_id),
            )
        )


#: Techo de adjudicaciones que devuelve :func:`movimientos_vigiladas`. Las
#: señales se construyen sobre estas filas; el resumen por empresa no depende
#: del techo (lo calcula su propio ``GROUP BY``).
MOVIMIENTOS_LIMITE = 200


def movimientos_vigiladas(
    user_key: str,
    organization_id: int,
    *,
    desde_iso: str,
    user_id: int | None = None,
    limit: int = MOVIMIENTOS_LIMITE,
) -> dict[str, list[dict[str, Any]]]:
    """Adjudicaciones recientes de las empresas que vigila el usuario.

    Mismo ámbito de visibilidad que :func:`list_entries` (las propias más las
    compartidas con la organización). Devuelve dos listas:

    - ``resumen``: por empresa vigilada, adjudicaciones e importe desde
      ``desde_iso`` (incluidas las que no tienen ninguna, con 0: «no se mueve»
      también es una respuesta).
    - ``adjudicaciones``: las más recientes, con ``ccaa_nueva``/``cpv_nuevo``
      marcando si abren una CCAA o una familia CPV (2 dígitos) donde la empresa
      no tenía adjudicaciones ANTES de ``desde_iso``. Es la misma pregunta que
      hace ``scheduler/competitor_alerts.py`` para el email, pero sobre la
      fecha de adjudicación (lo que pasó en el mercado) y no sobre la de
      extracción (cuándo lo vimos nosotros).
    """
    ident = (user_id, user_key, user_id)
    vigiladas = (
        "SELECT DISTINCT w.empresa_id FROM watchlist_empresas w "
        "WHERE w.organization_id = %s "
        f"AND (w.visibility = 'organization' OR {_IDENT_W})"
    )
    guard = iso_guard("a.fecha_adjudicacion")
    resumen_sql = (
        f"WITH v AS ({vigiladas}) "
        "SELECT v.empresa_id, e.nombre_canonico AS nombre, "
        "       COUNT(a.licitacion_id) AS adjudicaciones, "
        "       COALESCE(SUM(a.importe_adjudicado), 0) AS importe "
        "FROM v "
        "JOIN empresas e ON e.empresa_id = v.empresa_id "
        "LEFT JOIN adjudicaciones a ON a.empresa_id = v.empresa_id "
        f"  AND {guard} AND a.fecha_adjudicacion >= %s "
        "GROUP BY v.empresa_id, e.nombre_canonico "
        "ORDER BY adjudicaciones DESC, e.nombre_canonico"
    )
    previo = "a2.fecha_adjudicacion < %s AND " + iso_guard("a2.fecha_adjudicacion")
    detalle_sql = (
        f"WITH v AS ({vigiladas}) "
        "SELECT a.empresa_id, e.nombre_canonico AS nombre, a.licitacion_id, "
        "       l.titulo, l.organo_contratacion, l.cpv, l.ccaa, "
        "       a.importe_adjudicado, a.fecha_adjudicacion, "
        "       (l.ccaa IS NOT NULL AND NOT EXISTS ("
        "           SELECT 1 FROM adjudicaciones a2 "
        "           JOIN licitaciones l2 ON l2.id_externo = a2.licitacion_id "
        f"          WHERE a2.empresa_id = a.empresa_id AND l2.ccaa = l.ccaa AND {previo}"
        "       )) AS ccaa_nueva, "
        "       (l.cpv IS NOT NULL AND NOT EXISTS ("
        "           SELECT 1 FROM adjudicaciones a2 "
        "           JOIN licitaciones l2 ON l2.id_externo = a2.licitacion_id "
        "          WHERE a2.empresa_id = a.empresa_id "
        f"            AND substr(l2.cpv, 1, 2) = substr(l.cpv, 1, 2) AND {previo}"
        "       )) AS cpv_nuevo "
        "FROM adjudicaciones a "
        "JOIN v ON v.empresa_id = a.empresa_id "
        "JOIN empresas e ON e.empresa_id = a.empresa_id "
        "JOIN licitaciones l ON l.id_externo = a.licitacion_id "
        f"WHERE {guard} AND a.fecha_adjudicacion >= %s "
        "ORDER BY a.fecha_adjudicacion DESC, a.licitacion_id "
        "LIMIT %s"
    )
    with connect_read() as c:
        resumen = rows_to_dicts(c.execute(resumen_sql, (organization_id, *ident, desde_iso)))
        detalle = rows_to_dicts(
            c.execute(
                detalle_sql,
                (
                    organization_id,
                    *ident,
                    desde_iso,
                    desde_iso,
                    desde_iso,
                    max(1, min(int(limit), MOVIMIENTOS_LIMITE)),
                ),
            )
        )
    return {"resumen": resumen, "adjudicaciones": detalle}


def list_all() -> list[dict[str, Any]]:
    """Todas las entradas con destinatario — para el job de alertas."""
    with connect() as c:
        return rows_to_dicts(
            c.execute(
                "SELECT w.id, w.user_key, w.user_id, w.empresa_id, e.nombre_canonico, "
                "       w.email, w.frequency, w.last_notified_at, w.organization_id "
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
