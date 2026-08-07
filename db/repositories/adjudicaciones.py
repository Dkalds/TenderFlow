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

# Identidad de empresa para los grafos órgano↔empresa (ADR-023): nombre
# canónico del maestro si existe y no está en blanco, si no el nombre raw del
# adjudicatario — la misma regla que aplicaba `_prepare_df` en
# services/analytics/red_organo_empresa.py sobre `empresa_nombre_master`.
_EMPRESA_KEY_SQL = (
    "COALESCE(CASE WHEN trim(e.nombre_canonico) != '' THEN e.nombre_canonico END, a.nombre)"
)

_GRAPH_FROM = (
    "FROM adjudicaciones a "
    "LEFT JOIN licitaciones l ON l.id_externo = a.licitacion_id "
    "LEFT JOIN empresas e ON e.empresa_id = a.empresa_id "
)


def _adj_filter_conditions(
    *,
    ccaa_filter: tuple[str, ...] | None,
    fecha_desde: str | None,
    fecha_hasta: str | None,
) -> tuple[list[str], list[Any]]:
    """Condiciones de filtro comunes de las consultas UTE (sobre el alias ``a``)."""
    conditions: list[str] = []
    params: list[Any] = []
    if ccaa_filter:
        placeholders = ",".join("?" for _ in ccaa_filter)
        conditions.append(f"a.ccaa IN ({placeholders})")
        params.extend(ccaa_filter)
    if fecha_desde and _DATE_RE.match(fecha_desde):
        conditions.append("a.fecha_adjudicacion >= ?")
        params.append(fecha_desde)
    if fecha_hasta and _DATE_RE.match(fecha_hasta):
        conditions.append("a.fecha_adjudicacion <= ?")
        params.append(fecha_hasta)
    return conditions, params


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

    # ── Columnas usadas por services/analytics/competitors.py ────────────
    _COMPETITOR_COLS = (
        "a.licitacion_id, a.nombre, a.nif, a.empresa_id, a.es_pyme, "
        "a.importe_adjudicado, a.fecha_adjudicacion, a.ccaa, a.n_ofertas_recibidas, "
        "l.organo_contratacion, l.tecnologia, l.estado, l.importe AS importe_licitacion, "
        "COALESCE(lo.importe, l.importe) AS presupuesto_efectivo, "
        "e.nombre_canonico AS empresa_nombre_master, "
        "e.nif_canonico AS empresa_nif_master, "
        "e.grupo_id AS empresa_grupo_id, "
        "g.nombre AS empresa_grupo_master"
    )

    def load_for_competitors(
        self,
        *,
        ccaa: str | None = None,
        tecnologia: str | None = None,
        estado: str | None = None,
        fecha_desde: str | None = None,
        fecha_hasta: str | None = None,
        importe_min: float | None = None,
    ) -> list[dict[str, Any]]:
        """Carga la proyección/filtro necesarios para ``services.analytics.competitors``.

        Unión adjudicaciones + licitaciones + maestro de empresas, con solo
        las columnas que consume la resolución de identidad + las 16
        agregaciones posteriores (no ``a.*``) y los 4 filtros (``tecnologia``,
        ``estado``, rango de fechas, ``importe_min`` sobre
        ``importe_licitacion``) en el ``WHERE``. La resolución de identidad
        (union-find sobre NIF/nombre normalizados) y las agregaciones siguen
        en pandas — no son reducibles a un ``GROUP BY`` plano.
        """
        sql = (
            "SELECT " + self._COMPETITOR_COLS + " "
            "FROM adjudicaciones a "
            "LEFT JOIN licitaciones l ON l.id_externo = a.licitacion_id "
            "LEFT JOIN lotes lo ON lo.id = a.lote_id "
            "LEFT JOIN empresas e ON e.empresa_id = a.empresa_id "
            "LEFT JOIN grupos_empresariales g ON g.grupo_id = e.grupo_id "
        )
        conditions: list[str] = []
        params: list[Any] = []
        if ccaa:
            conditions.append("a.ccaa = ?")
            params.append(ccaa)
        if tecnologia:
            conditions.append("l.tecnologia = ?")
            params.append(tecnologia)
        if estado:
            conditions.append("l.estado = ?")
            params.append(estado)
        if fecha_desde and _DATE_RE.match(fecha_desde):
            conditions.append("a.fecha_adjudicacion >= ?")
            params.append(fecha_desde)
        if fecha_hasta and _DATE_RE.match(fecha_hasta):
            conditions.append("a.fecha_adjudicacion <= ?")
            params.append(fecha_hasta)
        if importe_min is not None:
            conditions.append("l.importe >= ?")
            params.append(importe_min)
        if conditions:
            sql += "WHERE " + " AND ".join(conditions) + " "
        sql += "ORDER BY a.fecha_adjudicacion DESC"
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

    # ── Analítica UTE (ADR-023) ──────────────────────────────────────────
    #
    # El patrón regex que define «es UTE» lo pone el servicio llamador (es su
    # regla de negocio); aquí solo se aplica con `~*` (case-insensitive) sobre
    # el nombre raw del adjudicatario. `COALESCE(…, FALSE)` porque un nombre
    # NULL debe contar como no-UTE (paridad con `str.contains(na=False)`).

    def ute_kpis(
        self,
        *,
        pattern: str,
        ccaa_filter: tuple[str, ...] | None = None,
        fecha_desde: str | None = None,
        fecha_hasta: str | None = None,
    ) -> dict[str, Any]:
        """Conteos/importes UTE vs individual + nº de nombres UTE distintos."""
        conditions, params = _adj_filter_conditions(
            ccaa_filter=ccaa_filter, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta
        )
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        sql = (
            "SELECT COUNT(*) FILTER (WHERE es_ute) AS total_ute, "
            "       COALESCE(SUM(importe_adjudicado) FILTER (WHERE es_ute), 0) AS importe_ute, "
            "       COUNT(*) FILTER (WHERE NOT es_ute) AS total_individual, "
            "       COALESCE(SUM(importe_adjudicado) FILTER (WHERE NOT es_ute), 0) "
            "           AS importe_individual, "
            "       COUNT(DISTINCT nombre) FILTER (WHERE es_ute) AS empresas_distintas "
            "FROM (SELECT a.nombre, a.importe_adjudicado, "
            "             COALESCE(a.nombre ~* ?, FALSE) AS es_ute "
            f"      FROM adjudicaciones a{where}) t"
        )
        with connect_read() as c:
            row = c.execute(sql, [pattern, *params]).fetchone()
        if row is None:  # pragma: no cover - un SELECT agregado siempre trae fila
            return {
                "total_ute": 0,
                "importe_ute": 0.0,
                "total_individual": 0,
                "importe_individual": 0.0,
                "empresas_distintas": 0,
            }
        return {
            "total_ute": int(row[0] or 0),
            "importe_ute": float(row[1] or 0),
            "total_individual": int(row[2] or 0),
            "importe_individual": float(row[3] or 0),
            "empresas_distintas": int(row[4] or 0),
        }

    def ute_top_miembros(
        self,
        *,
        pattern: str,
        ccaa_filter: tuple[str, ...] | None = None,
        fecha_desde: str | None = None,
        fecha_hasta: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Ranking de nombres UTE por nº de adjudicaciones (nombre completo)."""
        conditions, params = _adj_filter_conditions(
            ccaa_filter=ccaa_filter, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta
        )
        where = " AND ".join(["COALESCE(a.nombre ~* ?, FALSE)", *conditions])
        sql = (
            "SELECT a.nombre AS nombre, COUNT(*) AS count, "
            "       COALESCE(SUM(a.importe_adjudicado), 0) AS importe "
            f"FROM adjudicaciones a WHERE {where} "
            "GROUP BY a.nombre ORDER BY count DESC, importe DESC, nombre LIMIT ?"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, [pattern, *params, limit]))

    def ute_evolucion(
        self,
        *,
        pattern: str,
        ccaa_filter: tuple[str, ...] | None = None,
        fecha_desde: str | None = None,
        fecha_hasta: str | None = None,
    ) -> list[dict[str, Any]]:
        """Serie mensual (period YYYY-MM) de adjudicaciones UTE.

        El guard sargable ``>= '1900' AND < '3000'`` descarta fechas no-ISO
        (paridad con el ``dropna`` tras ``to_datetime(errors="coerce")``).
        """
        conditions, params = _adj_filter_conditions(
            ccaa_filter=ccaa_filter, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta
        )
        where = " AND ".join(
            [
                "COALESCE(a.nombre ~* ?, FALSE)",
                "a.fecha_adjudicacion >= '1900'",
                "a.fecha_adjudicacion < '3000'",
                *conditions,
            ]
        )
        sql = (
            "SELECT substr(a.fecha_adjudicacion, 1, 7) AS period, "
            "       COUNT(*) AS contratos, "
            "       COALESCE(SUM(a.importe_adjudicado), 0) AS importe "
            f"FROM adjudicaciones a WHERE {where} "
            "GROUP BY period ORDER BY period"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, [pattern, *params]))

    def load_ute_rows(
        self,
        *,
        pattern: str,
        ccaa_filter: tuple[str, ...] | None = None,
        fecha_desde: str | None = None,
        fecha_hasta: str | None = None,
    ) -> list[dict[str, Any]]:
        """Proyección ACOTADA de filas UTE para el grafo de co-licitación.

        Justificación ADR-023: el parseo de miembros de una UTE
        (``parse_ute_members``) no es expresable en SQL, pero las filas cuyo
        nombre matchea el patrón UTE son una fracción pequeña del total y solo
        se proyectan 2 columnas — carga acotada, no full-table.
        """
        conditions, params = _adj_filter_conditions(
            ccaa_filter=ccaa_filter, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta
        )
        where = " AND ".join(["COALESCE(a.nombre ~* ?, FALSE)", *conditions])
        sql = f"SELECT a.nombre, a.importe_adjudicado FROM adjudicaciones a WHERE {where}"
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, [pattern, *params]))

    # ── Drill-down por órgano (ADR-023) ──────────────────────────────────

    def load_por_organo(self, organo: str) -> list[dict[str, Any]]:
        """Proyección ACOTADA de las adjudicaciones de UN órgano.

        Justificación ADR-023: acotada por definición al órgano pedido; el
        lead-time mediano y el lookup por licitación del drill-down siguen en
        pandas sobre este subconjunto. ``nombre`` aplica la identidad
        maestro-canónico-o-raw (la misma expresión que los grafos
        órgano↔empresa); ``fecha_publicacion``/``importe_licitacion`` vienen
        del join para el lead-time y la baja porcentual.
        """
        sql = (
            f"SELECT a.licitacion_id, {_EMPRESA_KEY_SQL} AS nombre, "
            "       a.importe_adjudicado, a.fecha_adjudicacion, "
            "       l.fecha_publicacion, l.importe AS importe_licitacion "
            f"{_GRAPH_FROM}"
            "WHERE l.organo_contratacion = ?"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, [organo]))
