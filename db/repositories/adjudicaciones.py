"""Repository para adjudicaciones."""

from __future__ import annotations

import re
from typing import Any

from db.database import connect_read
from db.repositories.base import count_where, rows_to_dicts

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_SUMMARY_COLS = (
    "id, licitacion_id, nombre, nif, importe_adjudicado, "
    "fecha_adjudicacion, ccaa, es_pyme, n_ofertas_recibidas"
)


class AdjudicacionRepository:
    def list_paginated(
        self,
        *,
        licitacion_id: str | None = None,
        ccaa: str | None = None,
        fecha_desde: str | None = None,
        fecha_hasta: str | None = None,
        limit: int = 50,
        offset: int = 0,
        with_total: bool = True,
    ) -> tuple[list[dict[str, Any]], int]:
        conditions: list[str] = []
        params: list[Any] = []

        if licitacion_id:
            conditions.append("licitacion_id = ?")
            params.append(licitacion_id)
        if ccaa:
            conditions.append("ccaa = ?")
            params.append(ccaa)
        if fecha_desde and _DATE_RE.match(fecha_desde):
            conditions.append("fecha_adjudicacion >= ?")
            params.append(fecha_desde)
        if fecha_hasta and _DATE_RE.match(fecha_hasta):
            conditions.append("fecha_adjudicacion <= ?")
            params.append(fecha_hasta)

        where = " AND ".join(conditions)
        with connect_read() as c:
            total = count_where(c, "adjudicaciones", where, tuple(params)) if with_total else -1
            sql = "SELECT " + _SUMMARY_COLS + " FROM adjudicaciones"
            if where:
                sql += " WHERE " + where
            sql += " ORDER BY fecha_adjudicacion DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            items = rows_to_dicts(c.execute(sql, tuple(params)))

        return items, total
