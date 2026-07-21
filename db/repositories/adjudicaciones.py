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

    # ── Métodos para services/adjudicaciones.py ──────────────────────────

    def load_raw_with_licitaciones(
        self,
        *,
        limit: int | None = None,
        ccaa_filter: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        """Carga adjudicaciones raw con datos de la licitación asociada."""
        sql = (
            "SELECT a.*, l.titulo, l.organo_contratacion, l.url AS url_lic, "
            "       l.fecha_publicacion, l.tecnologia, l.estado, "
            "       l.importe AS importe_licitacion, "
            "       e.nombre_canonico AS empresa_nombre_master, "
            "       e.nif_canonico AS empresa_nif_master, "
            "       e.es_ute AS empresa_es_ute, "
            "       e.grupo_id AS empresa_grupo_id, "
            "       g.nombre AS empresa_grupo_master "
            "FROM adjudicaciones a "
            "LEFT JOIN licitaciones l ON l.id_externo = a.licitacion_id "
            "LEFT JOIN empresas e ON e.empresa_id = a.empresa_id "
            "LEFT JOIN grupos_empresariales g ON g.grupo_id = e.grupo_id "
        )
        params: list[Any] = []
        if ccaa_filter:
            placeholders = ",".join("?" for _ in ccaa_filter)
            sql += f"WHERE a.ccaa IN ({placeholders}) "
            params.extend(ccaa_filter)
        sql += "ORDER BY a.fecha_adjudicacion DESC"
        if limit is not None and limit > 0:
            sql += " LIMIT ?"
            params.append(int(limit))
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, params))

    def load_licitadores(
        self,
        *,
        ccaa_filter: tuple[str, ...] | None = None,
        limit: int = 10000,
    ) -> list[dict[str, Any]]:
        """Carga adjudicaciones con datos para el ranking de licitadores."""
        sql = (
            "SELECT a.id, a.licitacion_id, a.nif, a.nombre, a.ccaa, a.provincia, "
            "       a.importe_adjudicado, a.importe_pagable, a.fecha_adjudicacion, "
            "       a.es_pyme, a.n_ofertas_recibidas, "
            "       l.titulo, l.organo_contratacion, l.cpv, l.tecnologia "
            "FROM adjudicaciones a "
            "JOIN licitaciones l ON l.id_externo = a.licitacion_id "
        )
        params: list[Any] = []
        if ccaa_filter:
            placeholders = ",".join("?" for _ in ccaa_filter)
            sql += f"WHERE a.ccaa IN ({placeholders}) "
            params.extend(ccaa_filter)
        sql += f"ORDER BY a.fecha_adjudicacion DESC LIMIT {int(limit)}"
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, params))

    def find_publicacion_posterior_a_adjudicacion(
        self, *, fuentes: tuple[str, ...] | None = None
    ) -> list[dict[str, Any]]:
        """Licitaciones con ``fecha_publicacion`` posterior a su primera adjudicación.

        Devuelve una fila por licitación con ``id_externo``, ``fuente``, ``pub``
        (fecha_publicacion ISO, 10 chars) y ``min_adj`` (adjudicación más
        temprana, ISO). Es imposible que una licitación se adjudique antes de
        publicarse: estas filas tienen la fecha de publicación corrupta (una
        fase posterior la sobrescribió). Source-agnóstico.
        """
        sql = (
            "SELECT l.id_externo, l.fuente, "
            "       substr(l.fecha_publicacion, 1, 10) AS pub, "
            "       substr(MIN(a.fecha_adjudicacion), 1, 10) AS min_adj "
            "FROM licitaciones l "
            "JOIN adjudicaciones a ON a.licitacion_id = l.id_externo "
            "WHERE l.fecha_publicacion IS NOT NULL "
            "  AND a.fecha_adjudicacion IS NOT NULL "
            "GROUP BY l.id_externo, l.fuente, substr(l.fecha_publicacion, 1, 10) "
            "HAVING substr(l.fecha_publicacion, 1, 10) "
            "       > substr(MIN(a.fecha_adjudicacion), 1, 10) "
            "ORDER BY l.fuente, min_adj"
        )
        with connect_read() as c:
            rows = rows_to_dicts(c.execute(sql))
        if fuentes is not None:
            rows = [r for r in rows if (r.get("fuente") or "").lower() in fuentes]
        return rows
