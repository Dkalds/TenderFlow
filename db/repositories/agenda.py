"""Señales de la agenda de Mi Pipeline: matches de reglas sin triar.

Una señal es una licitación **abierta y con plazo por delante** que coincide
con una regla de watchlist del usuario y que nadie ha triado todavía: no tiene
pursuit en la organización (seguida) ni descarte en ``radar_dismissals``
(descartada). El triaje reutiliza los mismos gestos y persistencia que el
Radar — no se inventa un segundo mecanismo de descarte.

El matching replica la semántica de ``services/watchlist_rules._rule_clauses``
(keyword sobre título/descripción, CPV por prefijo, importe mínimo, CCAA) con
el mismo escapado de comodines LIKE. Vive aquí y no en ese módulo porque el
SQL nuevo pertenece a ``db/`` (ADR-022); el módulo legacy de services está
congelado en la whitelist TID251.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from db.database import connect_read
from db.repositories.base import rows_to_dicts
from shared.estados import abierta_sql

# Guard de fecha bien formada, mismo rango sargable que
# ``db/repositories/aggregates._iso_guard`` (el CHECK de v59 valida el formato
# en escrituras nuevas; esto solo excluye legado malformado sin regex).
_FECHA_LIMITE_VIVA_SQL = (
    "l.fecha_limite IS NOT NULL "
    "AND l.fecha_limite >= to_char(CURRENT_DATE, 'YYYY-MM-DD') "
    "AND l.fecha_limite < '3000'"
)

_SIGNAL_COLS = (
    "l.id_externo, l.titulo, l.organo_contratacion AS organo, "
    "l.importe AS importe_eur, l.ccaa, l.tecnologia, l.fecha_limite, l.url"
)


@dataclass(frozen=True)
class SignalCriteria:
    """Criterios de una regla de watchlist, sin acoplar ``db/`` a services."""

    rule_id: int
    nombre: str | None
    keyword: str | None
    cpv: str | None
    min_importe: float | None
    ccaa: str | None


def _escape_like(value: str) -> str:
    """Escapa comodines LIKE (``%``, ``_``) del input de usuario."""
    return value.replace("%", r"\%").replace("_", r"\_")


def signal_rows(
    criteria: SignalCriteria,
    *,
    user_key: str,
    organization_id: int,
    tecnologia: str | None = None,
    ccaa: str | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Matches vivos y sin triar de una regla, más urgentes primero."""
    clauses = [
        abierta_sql("l.estado"),
        _FECHA_LIMITE_VIVA_SQL,
        "NOT EXISTS (SELECT 1 FROM pursuits p "
        "WHERE p.organization_id = %s AND p.licitacion_id = l.id_externo)",
        "NOT EXISTS (SELECT 1 FROM radar_dismissals rd "
        "WHERE rd.user_key = %s AND rd.id_externo = l.id_externo)",
    ]
    params: list[Any] = [organization_id, user_key]
    if criteria.keyword:
        like = f"%{_escape_like(criteria.keyword)}%"
        clauses.append("(l.titulo LIKE %s OR l.descripcion LIKE %s)")
        params.extend([like, like])
    if criteria.cpv:
        clauses.append("l.cpv LIKE %s")
        params.append(f"{_escape_like(criteria.cpv)}%")
    if criteria.min_importe is not None:
        clauses.append("l.importe >= %s")
        params.append(criteria.min_importe)
    if criteria.ccaa:
        clauses.append("l.ccaa = %s")
        params.append(criteria.ccaa)
    if tecnologia:
        clauses.append("l.tecnologia = %s")
        params.append(tecnologia)
    if ccaa:
        clauses.append("l.ccaa = %s")
        params.append(ccaa)

    sql = (
        "SELECT "
        + _SIGNAL_COLS
        + " FROM licitaciones l WHERE "
        + " AND ".join(clauses)
        + " ORDER BY l.fecha_limite ASC, l.id_externo LIMIT %s"
    )
    with connect_read() as conn:
        return rows_to_dicts(conn.execute(sql, tuple([*params, limit])))
