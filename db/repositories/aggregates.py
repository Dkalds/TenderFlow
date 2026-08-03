"""Repository para agregaciones OLAP (``GROUP BY``/``COUNT``/``SUM`` en Postgres).

Contrapartida SQL de los servicios ``services/analytics/{overview,tecnologias,
competitors}.py``, que hasta ahora cargaban la tabla completa a pandas y
agregaban en el proceso web (ver AGENTS.md / postmortem OOM en
``services/_data_cache.py``). Postgres resuelve estos ``GROUP BY`` sobre las
~47k filas de ``licitaciones`` en milisegundos; este módulo es el único lugar
donde vive el SQL de esas agregaciones (ADR-022, invariante §3.10) — incluida
la construcción del ``WHERE`` a partir de los filtros: los servicios de
``services/analytics/*`` pasan valores (fechas, strings, floats), nunca
fragmentos de SQL.

Convenciones de fecha (importante, ver ``db/alembic/versions/
v59_pg_date_format_checks.py``): las columnas de fecha (``fecha_publicacion``,
``fecha_limite``, ``fecha_adjudicacion``) son ``TEXT`` ISO-8601, no
``TIMESTAMP`` — hay filas históricas con formato inválido (el CHECK que las
valida es ``NOT VALID``, no cubre datos previos a la migración). Por eso:

- Los filtros simples (``>=``/``<=`` con la fecha que llega del usuario) se
  comparan como string, igual que el resto de repositories del proyecto — sin
  CAST, sin riesgo de reventar la query por una fila legado malformada.
- El bucketing mensual usa ``substr(fecha, 1, 7)`` (prefijo ``YYYY-MM``) en
  vez de ``date_trunc``: evita casts a ``timestamp`` (y con ellos, cualquier
  ambigüedad de timezone de sesión) y es exacto para cualquier fecha ISO bien
  formada.
- Las ventanas relativas a "ahora" (últimos N días/horas) reciben el cutoff ya
  calculado en Python (``datetime.now(UTC).isoformat()`` — mismo formato que
  ``db.connection.now_utc_iso()``) como parámetro, comparado con ``>=``/``<``
  de forma lexicográfica, igual que los filtros. Se guardan con un rango
  lexicográfico sargable (``>= '1900' AND < '3000'``, ver ``_iso_guard``) para
  excluir filas claramente malformadas del cálculo, replicando el
  ``errors="coerce"`` + ``dropna`` que hacía pandas fila a fila sin renunciar
  al índice btree de la columna.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from db.database import connect_read
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)


def _iso_guard(column: str) -> str:
    """Cláusula que excluye fechas claramente malformadas (mirror de coerce+dropna).

    Rango lexicográfico y no regex: ``~`` no puede usar el btree y obliga a
    evaluar el patrón fila a fila sobre todo lo que devuelva el índice de fecha
    (32 s medidos en prod para 217 filas de resultado). El rango es sargable y
    equivalente sobre datos ISO: el CHECK de v59 valida el formato en toda
    escritura nueva y las filas legado se verificaron limpias en prod
    (0 malformadas en licitaciones/adjudicaciones, 2026-08-02).
    """
    return f"({column} >= '1900' AND {column} < '3000')"


def _escape_like(s: str) -> str:
    """Escapa comodines de LIKE/ILIKE (``%``, ``_``) en input de usuario."""
    return s.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


# Aproximación SQL de shared/services fold_text (NFKD sin tildes + casefold)
# sin la extensión ``unaccent`` (no habilitada; habilitarla exige migración con
# gate humano). Cubre el repertorio acentuado real de los nombres de órganos
# españoles; cualquier carácter fuera del mapa queda igual (mismo resultado
# que fold_text para ASCII).
_FOLD_SRC = "áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ"
_FOLD_DST = "aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC"


def _fold_expr(column: str) -> str:
    """Expresión SQL que pliega tildes y mayúsculas de ``column``."""
    return f"lower(translate({column}, '{_FOLD_SRC}', '{_FOLD_DST}'))"


@dataclass(frozen=True)
class LicitacionesFilters:
    """Filtros comunes sobre ``licitaciones`` para las agregaciones de analytics.

    Valores planos (no el DTO Pydantic del servicio) — mantiene ``db/`` sin
    depender de ``services/analytics/*``.
    """

    ccaa: str | None = None
    tecnologia: str | None = None
    estado: str | None = None
    fecha_desde: str | None = None
    fecha_hasta: str | None = None
    importe_min: float | None = None
    q: str | None = None
    cpv: str | None = None


def _build_where(filters: LicitacionesFilters) -> tuple[str, list[Any]]:
    """Construye el ``WHERE`` (dialecto qmark) desde :class:`LicitacionesFilters`."""
    clauses: list[str] = ["1 = 1"]
    params: list[Any] = []

    if filters.fecha_desde:
        clauses.append("fecha_publicacion >= ?")
        params.append(filters.fecha_desde)
    if filters.fecha_hasta:
        clauses.append("fecha_publicacion <= ?")
        params.append(filters.fecha_hasta)
    if filters.ccaa:
        clauses.append("ccaa = ?")
        params.append(filters.ccaa)
    if filters.tecnologia:
        clauses.append("tecnologia = ?")
        params.append(filters.tecnologia)
    if filters.estado:
        clauses.append("estado = ?")
        params.append(filters.estado)
    if filters.importe_min is not None:
        clauses.append("importe >= ?")
        params.append(filters.importe_min)
    if filters.q and filters.q.strip():
        needle = f"%{_escape_like(filters.q.strip())}%"
        clauses.append(
            "(titulo ILIKE ? ESCAPE '\\' OR organo_contratacion ILIKE ? ESCAPE '\\' "
            "OR id_externo ILIKE ? ESCAPE '\\')"
        )
        params.extend([needle, needle, needle])
    if filters.cpv:
        clauses.append("cpv = ?")
        params.append(filters.cpv)

    return " AND ".join(clauses), params


class AggregateRepository:
    """Acceso a las vistas materializadas de aggregates y a agregaciones en vivo."""

    def load_mat_clusters(self) -> list[dict[str, Any]]:
        """Carga datos de ``mat_clusters`` para ``services/clustering_engine.py``."""
        with connect_read() as c:
            try:
                cur = c.execute(
                    "SELECT id_externo, cluster_id, cluster_label, updated_at FROM mat_clusters"
                )
                return rows_to_dicts(cur)
            except Exception as exc:
                log.warning("repo_mat_clusters_unavailable", error=str(exc))
                return []

    # ── Overview ──────────────────────────────────────────────────────────

    def overview_kpis(self, filters: LicitacionesFilters) -> dict[str, Any]:
        """total, importe_total, importe_medio, organos_unicos — un SELECT."""
        where, params = _build_where(filters)
        sql = (
            "SELECT COUNT(*) AS total, "
            "       COALESCE(SUM(importe), 0) AS importe_total, "
            "       AVG(importe) AS importe_medio, "
            "       COUNT(DISTINCT organo_contratacion) AS organos "
            "FROM licitaciones WHERE " + where
        )
        with connect_read() as c:
            row = c.execute(sql, params).fetchone()
        if row is None or int(row[0]) == 0:
            return {"total": 0, "importe_total": 0.0, "importe_medio": 0.0, "organos": 0}
        return {
            "total": int(row[0]),
            "importe_total": float(row[1] or 0.0),
            "importe_medio": float(row[2]) if row[2] is not None else 0.0,
            "organos": int(row[3] or 0),
        }

    def overview_por_estado(self, filters: LicitacionesFilters) -> list[dict[str, Any]]:
        where, params = _build_where(filters)
        sql = (
            "SELECT estado, COUNT(*) AS n FROM licitaciones "
            "WHERE " + where + " AND estado IS NOT NULL "
            "GROUP BY estado ORDER BY n DESC"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, params))

    def overview_por_mes(self, filters: LicitacionesFilters) -> list[dict[str, Any]]:
        where, params = _build_where(filters)
        sql = (
            "SELECT substr(fecha_publicacion, 1, 7) AS mes, "
            "       COUNT(*) AS n_licitaciones, "
            "       COALESCE(SUM(importe), 0) AS importe "
            "FROM licitaciones "
            "WHERE " + where + " AND " + _iso_guard("fecha_publicacion") + " "
            "GROUP BY mes ORDER BY mes"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, params))

    def overview_top_organos(
        self, filters: LicitacionesFilters, n: int = 15
    ) -> list[dict[str, Any]]:
        where, params = _build_where(filters)
        sql = (
            "SELECT organo_contratacion, COUNT(*) AS n, COALESCE(SUM(importe), 0) AS importe "
            "FROM licitaciones "
            "WHERE " + where + " AND organo_contratacion IS NOT NULL "
            "GROUP BY organo_contratacion ORDER BY n DESC LIMIT ?"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, [*params, n]))

    def overview_funnel(self, filters: LicitacionesFilters) -> dict[str, int]:
        where, params = _build_where(filters)
        sql = (
            "SELECT "
            "  COUNT(*) FILTER (WHERE estado = 'PUB') AS pub, "
            "  COUNT(*) FILTER (WHERE estado = 'EV') AS ev, "
            "  COUNT(*) FILTER (WHERE estado = 'RES') AS res, "
            "  COUNT(*) FILTER (WHERE estado = 'ADJ') AS adj, "
            "  COUNT(*) FILTER (WHERE estado = 'ANUL') AS anul, "
            "  COUNT(*) AS total "
            "FROM licitaciones WHERE " + where
        )
        with connect_read() as c:
            row = c.execute(sql, params).fetchone()
        if row is None:
            return {"PUB": 0, "EV": 0, "RES": 0, "ADJ": 0, "ANUL": 0, "total": 0}
        pub, ev, res, adj, anul, total = row
        return {
            "PUB": int(pub or 0),
            "EV": int(ev or 0),
            "RES": int(res or 0),
            "ADJ": int(adj or 0),
            "ANUL": int(anul or 0),
            "total": int(total or 0),
        }

    def overview_adjudicaciones_indicadores(self) -> dict[str, float | None]:
        """HHI, % oferta única y lead time medio, agregados en Postgres.

        Sustituye la carga full-table ``adjudicaciones⋈licitaciones`` que
        alimentaba estos tres KPIs vía pandas (27 s y ~170k filas por llamada
        medidos en prod, y bloqueada en Render por
        ``render_api_full_table_loads_blocked`` — que los dejaba a cero/None).
        Sin filtros a propósito: estos indicadores siempre ignoraron los
        filtros del endpoint (ver docstring de ``services/analytics/overview``).

        La clave de empresa replica ``services/adjudicaciones.py`` (NIF
        normalizado con fallback a nombre normalizado) usando además
        ``empresa_id`` — la resolución de entidad ya hecha en ingesta — como
        primera opción cuando existe.
        """
        empresa_key = (
            "COALESCE(a.empresa_id::text, "
            "NULLIF(upper(regexp_replace(a.nif, '[^A-Za-z0-9]', '', 'g')), ''), "
            "NULLIF(upper(trim(a.nombre)), ''))"
        )
        adj_guard = _iso_guard("a.fecha_adjudicacion")
        pub_guard = _iso_guard("l.fecha_publicacion")
        sql = (
            "SELECT "
            "  (SELECT COALESCE(SUM(POWER(cuota * 100, 2)), 0) FROM ( "
            "     SELECT SUM(a.importe_adjudicado) "
            "            / NULLIF(SUM(SUM(a.importe_adjudicado)) OVER (), 0) AS cuota "
            "     FROM adjudicaciones a "
            "     WHERE a.importe_adjudicado IS NOT NULL "
            f"      AND {empresa_key} IS NOT NULL "
            f"    GROUP BY {empresa_key} "
            "  ) shares) AS hhi, "
            "  (SELECT 100.0 * COUNT(*) FILTER (WHERE n_ofertas_recibidas = 1) "
            "          / NULLIF(COUNT(*) FILTER (WHERE n_ofertas_recibidas IS NOT NULL), 0) "
            "   FROM adjudicaciones) AS pct_oferta_unica, "
            "  (SELECT ROUND(AVG(lead)::numeric, 1) FROM ( "
            "     SELECT substr(a.fecha_adjudicacion, 1, 10)::date "
            "            - substr(l.fecha_publicacion, 1, 10)::date AS lead "
            "     FROM adjudicaciones a "
            "     JOIN licitaciones l ON l.id_externo = a.licitacion_id "
            f"    WHERE {adj_guard} AND {pub_guard} "
            "  ) t WHERE lead > 0) AS lead_time_medio"
        )
        with connect_read() as c:
            row = c.execute(sql).fetchone()
        if row is None:
            return {"hhi": 0.0, "pct_oferta_unica": 0.0, "lead_time_medio": None}
        hhi, pct_oferta_unica, lead_time = row
        lead_val = float(lead_time) if lead_time is not None and float(lead_time) > 0 else None
        return {
            "hhi": float(hhi or 0.0),
            "pct_oferta_unica": float(pct_oferta_unica or 0.0),
            "lead_time_medio": lead_val,
        }

    def overview_yoy_and_recent(
        self,
        filters: LicitacionesFilters,
        *,
        hace_30d_iso: str,
        hace_60d_iso: str,
    ) -> dict[str, float]:
        """Ventanas ``>= hoy-30d`` (SIN cota superior, igual que el pandas original:

        ``_yoy_delta_count``/``_importe_30d`` solo filtran por el límite
        inferior — una fecha de publicación futura, si existiera, se incluiría
        igual). ``lics_prev30d`` sí es un rango cerrado ``[hoy-60d, hoy-30d)``.
        """
        where, params = _build_where(filters)
        col = "fecha_publicacion"
        guard = _iso_guard(col)
        sql = (
            "SELECT "
            f"  COUNT(*) FILTER (WHERE {guard} AND {col} >= ?) AS lics_30d, "
            f"  COUNT(*) FILTER (WHERE {guard} AND {col} < ? AND {col} >= ?) AS lics_prev30d, "
            f"  COALESCE(SUM(importe) FILTER (WHERE {guard} AND {col} >= ?), 0)"
            "     AS importe_30d "
            "FROM licitaciones WHERE " + where
        )
        # OJO orden de binds: los ``?`` de la lista SELECT aparecen ANTES que
        # los del WHERE en el texto SQL final — el orden de los params debe
        # seguir la posición física del placeholder, no el orden en que se
        # construyen en Python.
        run_params = [hace_30d_iso, hace_30d_iso, hace_60d_iso, hace_30d_iso, *params]
        with connect_read() as c:
            row = c.execute(sql, run_params).fetchone()
        if row is None:
            return {"lics_30d": 0.0, "lics_prev30d": 0.0, "importe_30d": 0.0}
        lics_30d, lics_prev30d, importe_30d = row
        return {
            "lics_30d": float(lics_30d or 0),
            "lics_prev30d": float(lics_prev30d or 0),
            "importe_30d": float(importe_30d or 0.0),
        }

    def overview_concentracion_organos(
        self, filters: LicitacionesFilters, *, top_n: int = 10
    ) -> tuple[float, float]:
        """(top_n_importe, total_importe) agrupado por organo (dropna, min_count=1)."""
        where, params = _build_where(filters)
        sql = (
            "SELECT SUM(importe) AS s FROM licitaciones "
            "WHERE " + where + " AND organo_contratacion IS NOT NULL "
            "GROUP BY organo_contratacion "
            "HAVING SUM(importe) IS NOT NULL "
            "ORDER BY s DESC"
        )
        with connect_read() as c:
            rows = c.execute(sql, params).fetchall()
        sums = [float(r[0]) for r in rows]
        return sum(sums[:top_n]), sum(sums)

    def overview_concentracion_ccaa(
        self, filters: LicitacionesFilters, *, top_n: int = 3
    ) -> tuple[float, float]:
        """(top_n_importe, total_importe) agrupado por ccaa (dropna, min_count=1)."""
        where, params = _build_where(filters)
        sql = (
            "SELECT SUM(importe) AS s FROM licitaciones "
            "WHERE " + where + " AND ccaa IS NOT NULL "
            "GROUP BY ccaa "
            "HAVING SUM(importe) IS NOT NULL "
            "ORDER BY s DESC"
        )
        with connect_read() as c:
            rows = c.execute(sql, params).fetchall()
        sums = [float(r[0]) for r in rows]
        return sum(sums[:top_n]), sum(sums)

    def overview_ccaa_cubiertas(self, filters: LicitacionesFilters) -> int:
        where, params = _build_where(filters)
        sql = "SELECT COUNT(DISTINCT ccaa) FROM licitaciones WHERE " + where
        with connect_read() as c:
            row = c.execute(sql, params).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def overview_tasa_anulacion(
        self, filters: LicitacionesFilters, *, hace_365d_iso: str
    ) -> tuple[int, int]:
        """(anul_count, total_count) sobre fecha_publicacion >= hoy-365d."""
        where, params = _build_where(filters)
        guard = _iso_guard("fecha_publicacion")
        sql = (
            "SELECT "
            "  COUNT(*) FILTER (WHERE estado = 'ANUL') AS anul, "
            "  COUNT(*) AS total "
            "FROM licitaciones "
            f"WHERE {where} AND {guard} AND fecha_publicacion >= ?"
        )
        with connect_read() as c:
            row = c.execute(sql, [*params, hace_365d_iso]).fetchone()
        if row is None:
            return 0, 0
        return int(row[0] or 0), int(row[1] or 0)

    def overview_para_hoy(
        self,
        filters: LicitacionesFilters,
        *,
        hoy_iso: str,
        limite_48h_iso: str,
        hace_24h_iso: str,
    ) -> dict[str, int]:
        """Los cuatro contadores del bloque "para hoy", en un solo SELECT.

        Compartido por ``services/analytics/overview.py`` (que ignora
        ``total_activas``) y por ``services/analytics/resumen.py``
        (``/analytics/resumen/hoy``, que los usa los cuatro): son los mismos
        contadores sobre el mismo conjunto filtrado, así que duplicar el SQL
        sería duplicar también las convenciones de fecha y el P75.
        """
        where, params = _build_where(filters)
        pub_guard = _iso_guard("fecha_publicacion")
        lim_guard = _iso_guard("fecha_limite")
        sql = (
            "WITH filtered AS (SELECT * FROM licitaciones WHERE " + where + "), "
            "p75 AS (SELECT percentile_cont(0.75) WITHIN GROUP (ORDER BY importe) AS v "
            "        FROM filtered WHERE importe IS NOT NULL) "
            "SELECT "
            "  COUNT(*) FILTER ("
            "    WHERE estado IN ('PUB', 'EV') "
            f"     AND {lim_guard} AND fecha_limite > ? "
            "      AND importe >= (SELECT v FROM p75)"
            "  ) AS calientes_hoy, "
            f"  COUNT(*) FILTER (WHERE {lim_guard} AND fecha_limite >= ? AND fecha_limite <= ?)"
            "     AS vencen_48h, "
            f"  COUNT(*) FILTER (WHERE {pub_guard} AND fecha_publicacion >= ?) AS nuevas_24h, "
            "  COUNT(*) FILTER (WHERE estado IN ('PUB', 'EV')) AS total_activas "
            "FROM filtered"
        )
        run_params = [*params, hoy_iso, hoy_iso, limite_48h_iso, hace_24h_iso]
        with connect_read() as c:
            row = c.execute(sql, run_params).fetchone()
        if row is None:
            return {"calientes_hoy": 0, "vencen_48h": 0, "nuevas_24h": 0, "total_activas": 0}
        calientes, vencen, nuevas, activas = row
        return {
            "calientes_hoy": int(calientes or 0),
            "vencen_48h": int(vencen or 0),
            "nuevas_24h": int(nuevas or 0),
            "total_activas": int(activas or 0),
        }

    # ── Resumen ──────────────────────────────────────────────────────────

    _RESUMEN_ITEM_COLS = (
        "id_externo, titulo, importe, fecha_publicacion, estado, "
        "organo_contratacion, tipo_contrato, ccaa"
    )

    def resumen_timeline_items(
        self, filters: LicitacionesFilters, *, limit: int
    ) -> list[dict[str, Any]]:
        """Las ``limit`` licitaciones más recientes (scatter de ``/resumen/timeline``).

        El ``ORDER BY ... DESC LIMIT`` lo resuelve el btree de
        ``fecha_publicacion`` hacia atrás: se materializan ``limit`` filas, no
        la tabla entera como hacía el ``sort_values().head()`` de pandas.
        """
        where, params = _build_where(filters)
        guard = _iso_guard("fecha_publicacion")
        sql = (
            f"SELECT {self._RESUMEN_ITEM_COLS} FROM licitaciones "
            f"WHERE {where} AND {guard} "
            "ORDER BY fecha_publicacion DESC LIMIT ?"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, [*params, limit]))

    def resumen_novedades(
        self, *, desde_iso: str, sample_limit: int
    ) -> tuple[int, list[dict[str, Any]]]:
        """(total, muestra) de licitaciones publicadas después de ``desde_iso``.

        La muestra va ordenada por ``fecha_publicacion`` descendente — el
        ``head(10)`` de pandas devolvía las primeras filas en el orden en que
        las servía la BD (arbitrario y no estable entre llamadas); las más
        recientes son además las que el banner quiere enseñar.
        """
        guard = _iso_guard("fecha_publicacion")
        where = f"{guard} AND fecha_publicacion > ?"
        with connect_read() as c:
            row = c.execute(
                f"SELECT COUNT(*) FROM licitaciones WHERE {where}", [desde_iso]
            ).fetchone()
            count = int(row[0]) if row and row[0] is not None else 0
            if count == 0:
                return 0, []
            sample = rows_to_dicts(
                c.execute(
                    "SELECT id_externo, titulo, importe, organo_contratacion "
                    f"FROM licitaciones WHERE {where} "
                    "ORDER BY fecha_publicacion DESC LIMIT ?",
                    [desde_iso, sample_limit],
                )
            )
        return count, sample

    # ── Tecnologias ──────────────────────────────────────────────────────

    def tecnologias_total_y_sin_clasificar(self, filters: LicitacionesFilters) -> tuple[int, int]:
        where, params = _build_where(filters)
        sql = (
            "SELECT COUNT(*) AS total, "
            "       COUNT(*) FILTER (WHERE tecnologia IS NULL OR trim(tecnologia) = '')"
            "         AS sin_clasificar "
            "FROM licitaciones WHERE " + where
        )
        with connect_read() as c:
            row = c.execute(sql, params).fetchone()
        if row is None:
            return 0, 0
        return int(row[0] or 0), int(row[1] or 0)

    def tecnologias_entries(self, filters: LicitacionesFilters) -> list[dict[str, Any]]:
        """Explode de ``tecnologia`` (CSV) vía ``unnest(string_to_array(...))``.

        Agrupa por CÓDIGO crudo (no por label legible) — el mapeo código→label
        de ``services/classification.py`` es un dict Python; varios códigos
        pueden mapear al mismo label, así que ese re-merge se hace en Python
        sobre el resultado ya agregado (post-procesamiento ligero permitido).
        """
        where, params = _build_where(filters)
        sql = (
            "SELECT trim(code) AS code, "
            "       COUNT(*) AS count, "
            "       COALESCE(SUM(importe), 0) AS importe, "
            "       COUNT(*) FILTER (WHERE estado = 'ADJ') AS adjudicadas "
            "FROM licitaciones, "
            "     unnest(string_to_array(COALESCE(tecnologia, ''), ',')) AS code "
            "WHERE " + where + " AND trim(code) != '' "
            "GROUP BY trim(code)"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, params))

    def tecnologias_cross_organo(
        self, filters: LicitacionesFilters, *, top_organos: int, top_techs: int
    ) -> list[dict[str, Any]]:
        where, params = _build_where(filters)
        sql = (
            "WITH exploded AS ("
            "  SELECT organo_contratacion AS organo, trim(code) AS code "
            "  FROM licitaciones, unnest(string_to_array(COALESCE(tecnologia, ''), ',')) AS code "
            "  WHERE " + where + " AND trim(code) != '' AND organo_contratacion IS NOT NULL"
            "), top_organos AS ("
            "  SELECT organo FROM exploded GROUP BY organo ORDER BY COUNT(*) DESC LIMIT ?"
            "), top_techs AS ("
            "  SELECT code FROM exploded GROUP BY code ORDER BY COUNT(*) DESC LIMIT ?"
            ") "
            "SELECT e.organo, e.code, COUNT(*) AS count "
            "FROM exploded e "
            "WHERE e.organo IN (SELECT organo FROM top_organos) "
            "  AND e.code IN (SELECT code FROM top_techs) "
            "GROUP BY e.organo, e.code"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, [*params, top_organos, top_techs]))

    def tecnologias_cross_geo(
        self, filters: LicitacionesFilters, *, top_ccaa: int, top_techs: int
    ) -> list[dict[str, Any]]:
        where, params = _build_where(filters)
        sql = (
            "WITH exploded AS ("
            "  SELECT ccaa, trim(code) AS code "
            "  FROM licitaciones, unnest(string_to_array(COALESCE(tecnologia, ''), ',')) AS code "
            "  WHERE " + where + " AND trim(code) != '' AND ccaa IS NOT NULL"
            "), top_ccaa AS ("
            "  SELECT ccaa FROM exploded GROUP BY ccaa ORDER BY COUNT(*) DESC LIMIT ?"
            "), top_techs AS ("
            "  SELECT code FROM exploded GROUP BY code ORDER BY COUNT(*) DESC LIMIT ?"
            ") "
            "SELECT e.ccaa, e.code, COUNT(*) AS count "
            "FROM exploded e "
            "WHERE e.ccaa IN (SELECT ccaa FROM top_ccaa) "
            "  AND e.code IN (SELECT code FROM top_techs) "
            "GROUP BY e.ccaa, e.code"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, [*params, top_ccaa, top_techs]))

    def tecnologias_evolucion(
        self, filters: LicitacionesFilters, *, top_techs: int
    ) -> list[dict[str, Any]]:
        where, params = _build_where(filters)
        guard = _iso_guard("fecha_publicacion")
        sql = (
            "WITH exploded AS ("
            "  SELECT substr(fecha_publicacion, 1, 7) AS mes, trim(code) AS code, importe "
            "  FROM licitaciones, unnest(string_to_array(COALESCE(tecnologia, ''), ',')) AS code "
            "  WHERE " + where + f" AND trim(code) != '' AND {guard}"
            "), top_techs AS ("
            "  SELECT code FROM exploded GROUP BY code ORDER BY COUNT(*) DESC LIMIT ?"
            ") "
            "SELECT mes, "
            "       CASE WHEN code IN (SELECT code FROM top_techs) THEN code ELSE '__OTRAS__' END"
            "         AS tech_grp, "
            "       COUNT(*) AS count, COALESCE(SUM(importe), 0) AS importe "
            "FROM exploded "
            "GROUP BY mes, tech_grp "
            "ORDER BY mes"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, [*params, top_techs]))

    def tecnologia_detalle_items(
        self, filters: LicitacionesFilters, *, tech_codes: list[str], limit: int
    ) -> list[dict[str, Any]]:
        """Top-N licitaciones (por importe) para los códigos crudos de UN label.

        ``tech_codes`` es la lista de códigos de ``tecnologia`` que mapean al
        label solicitado (resuelta en ``services/analytics/tecnologias.py`` vía
        ``TECHNOLOGY_LABELS`` — lógica de dominio, no SQL).
        """
        if not tech_codes:
            return []
        where, params = _build_where(filters)
        placeholders = ",".join("?" for _ in tech_codes)
        sql = (
            "SELECT DISTINCT ON (l.id_externo) "
            "       l.id_externo, l.titulo, l.organo_contratacion, l.importe, "
            "       l.estado, l.ccaa, l.fecha_publicacion "
            "FROM licitaciones l, "
            "     unnest(string_to_array(COALESCE(l.tecnologia, ''), ',')) AS code "
            "WHERE " + where + f" AND trim(code) IN ({placeholders}) "
            "ORDER BY l.id_externo, l.importe DESC NULLS LAST"
        )
        with connect_read() as c:
            rows = rows_to_dicts(c.execute(sql, [*params, *tech_codes]))
        rows.sort(key=lambda r: (r["importe"] is None, -(r["importe"] or 0)))
        return rows[:limit]

    # ── Geography ────────────────────────────────────────────────────────

    def geography_by_ccaa(self, filters: LicitacionesFilters) -> list[dict[str, Any]]:
        """(ccaa, count, importe) ordenado por count DESC; ccaa NULL excluida."""
        where, params = _build_where(filters)
        sql = (
            "SELECT ccaa, COUNT(*) AS count, COALESCE(SUM(importe), 0) AS importe "
            "FROM licitaciones "
            "WHERE " + where + " AND ccaa IS NOT NULL "
            "GROUP BY ccaa ORDER BY count DESC, ccaa"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, params))

    def geography_by_provincia(self, filters: LicitacionesFilters) -> list[dict[str, Any]]:
        """(provincia, count, importe) sobre TODO el dataset filtrado."""
        where, params = _build_where(filters)
        sql = (
            "SELECT provincia, COUNT(*) AS count, COALESCE(SUM(importe), 0) AS importe "
            "FROM licitaciones "
            "WHERE " + where + " AND provincia IS NOT NULL AND trim(provincia) != '' "
            "GROUP BY provincia ORDER BY count DESC, provincia"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, params))

    # ── Trends ───────────────────────────────────────────────────────────

    def trends_daily(self, filters: LicitacionesFilters) -> list[dict[str, Any]]:
        """(dia YYYY-MM-DD, count, importe) — base para series month/week/day.

        El roll-up a semana/mes se hace en Python sobre este resultado ya
        agregado (cientos de filas, post-agregación permitida por ADR-023):
        evita duplicar en SQL el formato de etiqueta semanal de pandas
        (``%Y-W%V`` sobre el lunes de la semana).
        """
        where, params = _build_where(filters)
        guard = _iso_guard("fecha_publicacion")
        sql = (
            "SELECT substr(fecha_publicacion, 1, 10) AS dia, "
            "       COUNT(*) AS count, COALESCE(SUM(importe), 0) AS importe "
            "FROM licitaciones "
            f"WHERE {where} AND {guard} "
            "GROUP BY dia ORDER BY dia"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, params))

    def trends_heatmap(self, filters: LicitacionesFilters) -> list[dict[str, Any]]:
        """(mes YYYY-MM, estado, value) para el heatmap mes x estado."""
        where, params = _build_where(filters)
        guard = _iso_guard("fecha_publicacion")
        sql = (
            "SELECT substr(fecha_publicacion, 1, 7) AS mes, estado, COUNT(*) AS value "
            "FROM licitaciones "
            f"WHERE {where} AND {guard} AND estado IS NOT NULL "
            "GROUP BY mes, estado ORDER BY mes, estado"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, params))

    def trends_yoy(
        self,
        filters: LicitacionesFilters,
        *,
        hace_365d_iso: str,
        hace_730d_iso: str,
    ) -> dict[str, float]:
        """Conteos e importes de las ventanas [hoy-365d, ∞) y [hoy-730d, hoy-365d)."""
        where, params = _build_where(filters)
        col = "fecha_publicacion"
        guard = _iso_guard(col)
        sql = (
            "SELECT "
            f"  COUNT(*) FILTER (WHERE {guard} AND {col} >= ?) AS cnt_cur, "
            f"  COUNT(*) FILTER (WHERE {guard} AND {col} < ? AND {col} >= ?) AS cnt_prev, "
            f"  COALESCE(SUM(importe) FILTER (WHERE {guard} AND {col} >= ?), 0) AS imp_cur, "
            f"  COALESCE(SUM(importe) FILTER (WHERE {guard} AND {col} < ? AND {col} >= ?), 0)"
            "     AS imp_prev "
            "FROM licitaciones WHERE " + where
        )
        run_params = [
            hace_365d_iso,
            hace_365d_iso,
            hace_730d_iso,
            hace_365d_iso,
            hace_365d_iso,
            hace_730d_iso,
            *params,
        ]
        with connect_read() as c:
            row = c.execute(sql, run_params).fetchone()
        if row is None:
            return {"cnt_cur": 0.0, "cnt_prev": 0.0, "imp_cur": 0.0, "imp_prev": 0.0}
        return {
            "cnt_cur": float(row[0] or 0),
            "cnt_prev": float(row[1] or 0),
            "imp_cur": float(row[2] or 0.0),
            "imp_prev": float(row[3] or 0.0),
        }

    # Bins del histograma de importe (mismos cortes que pd.cut right=False del
    # servicio original: [izq, der)). El primer bin excluye importes negativos,
    # igual que pandas dejaba fuera de todos los bins los valores < 0.
    _HISTOGRAM_BINS: tuple[tuple[str, float, float | None], ...] = (
        ("0-1K", 0, 1_000),
        ("1K-10K", 1_000, 10_000),
        ("10K-50K", 10_000, 50_000),
        ("50K-100K", 50_000, 100_000),
        ("100K-500K", 100_000, 500_000),
        ("500K-1M", 500_000, 1_000_000),
        ("1M-5M", 1_000_000, 5_000_000),
        ("5M+", 5_000_000, None),
    )

    def trends_histogram(self, filters: LicitacionesFilters) -> list[tuple[str, int]]:
        """Conteo por bin logarítmico de importe (orden fijo de bins).

        Devuelve lista vacía si no hay ningún importe no nulo en el dataset
        filtrado (paridad con el ``[]`` que devolvía el pandas original).
        """
        where, params = _build_where(filters)
        filters_sql: list[str] = []
        for _label, lo, hi in self._HISTOGRAM_BINS:
            if hi is None:
                filters_sql.append(f"COUNT(*) FILTER (WHERE importe >= {lo:.0f})")
            else:
                filters_sql.append(
                    f"COUNT(*) FILTER (WHERE importe >= {lo:.0f} AND importe < {hi:.0f})"
                )
        sql = (
            "SELECT COUNT(*), " + ", ".join(filters_sql) + " FROM licitaciones "
            "WHERE " + where + " AND importe IS NOT NULL"
        )
        with connect_read() as c:
            row = c.execute(sql, params).fetchone()
        if row is None or int(row[0] or 0) == 0:
            return []
        return [
            (label, int(row[i + 1] or 0))
            for i, (label, _lo, _hi) in enumerate(self._HISTOGRAM_BINS)
        ]

    # ── Organos ──────────────────────────────────────────────────────────

    def _organos_where(self, filters: LicitacionesFilters, q: str | None) -> tuple[str, list[Any]]:
        """WHERE común de /organos: filtros estándar + búsqueda plegada en el nombre.

        ``q`` llega YA plegado por el servicio (``fold_text``); aquí solo se
        pliega la columna. Búsqueda separada del ``q`` genérico de
        ``_build_where`` porque este busca solo en el nombre del órgano y sin
        tildes/mayúsculas.
        """
        where, params = _build_where(filters)
        if q:
            where += f" AND {_fold_expr('organo_contratacion')} LIKE ? ESCAPE '\\'"
            params.append(f"%{_escape_like(q)}%")
        return where, params

    def organos_totales(
        self, filters: LicitacionesFilters, *, q_folded: str | None
    ) -> tuple[int, int, float]:
        """(filas totales, órganos únicos, importe total) del dataset filtrado."""
        where, params = self._organos_where(filters, q_folded)
        sql = (
            "SELECT COUNT(*), COUNT(DISTINCT organo_contratacion), "
            "COALESCE(SUM(importe), 0) FROM licitaciones WHERE " + where
        )
        with connect_read() as c:
            row = c.execute(sql, params).fetchone()
        if row is None:
            return 0, 0, 0.0
        return int(row[0] or 0), int(row[1] or 0), float(row[2] or 0.0)

    def organos_ranking(
        self, filters: LicitacionesFilters, *, q_folded: str | None, limit: int
    ) -> list[dict[str, Any]]:
        """Ranking (count DESC) con la CCAA modal por órgano.

        ``mode() WITHIN GROUP (ORDER BY ccaa)`` replica el ``mode().iloc[0]``
        de pandas (empates → primera por orden alfabético) e ignora NULLs.
        """
        where, params = self._organos_where(filters, q_folded)
        sql = (
            "SELECT organo_contratacion, COUNT(*) AS count, "
            "       COALESCE(SUM(importe), 0) AS importe, "
            "       mode() WITHIN GROUP (ORDER BY ccaa) AS ccaa_mode "
            "FROM licitaciones "
            "WHERE " + where + " AND organo_contratacion IS NOT NULL "
            "GROUP BY organo_contratacion ORDER BY count DESC, organo_contratacion LIMIT ?"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, [*params, limit]))

    def organos_treemap(
        self, filters: LicitacionesFilters, *, q_folded: str | None, top_organos: int
    ) -> list[dict[str, Any]]:
        """(organo, tipo_contrato, importe) para los top-N órganos por count."""
        where, params = self._organos_where(filters, q_folded)
        sql = (
            "WITH top_org AS ("
            "  SELECT organo_contratacion FROM licitaciones "
            "  WHERE " + where + " AND organo_contratacion IS NOT NULL "
            "  GROUP BY organo_contratacion ORDER BY COUNT(*) DESC LIMIT ?"
            ") "
            "SELECT l.organo_contratacion AS organo, l.tipo_contrato, "
            "       SUM(l.importe) AS importe "
            "FROM licitaciones l "
            "WHERE " + where + " AND l.organo_contratacion IN "
            "      (SELECT organo_contratacion FROM top_org) "
            "  AND l.tipo_contrato IS NOT NULL AND l.importe IS NOT NULL "
            "GROUP BY l.organo_contratacion, l.tipo_contrato "
            "HAVING SUM(l.importe) > 0"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, [*params, top_organos, *params]))

    # ── Resumen: sankey y top licitaciones ───────────────────────────────

    def resumen_sankey(self, filters: LicitacionesFilters) -> list[dict[str, Any]]:
        """(tipo_contrato, estado, value) — flujo tipo→estado, NULLs excluidos."""
        where, params = _build_where(filters)
        sql = (
            "SELECT tipo_contrato, estado, COUNT(*) AS value FROM licitaciones "
            "WHERE " + where + " AND tipo_contrato IS NOT NULL AND estado IS NOT NULL "
            "GROUP BY tipo_contrato, estado ORDER BY tipo_contrato, estado"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, params))

    def resumen_top_licitaciones(
        self, filters: LicitacionesFilters, *, n: int
    ) -> list[dict[str, Any]]:
        """Top-N por importe con adjudicatario y agregados de adjudicación.

        ``adjudicatario`` es el primer nombre no nulo del grupo (determinista
        por id de fila); ``sum_adj``/``n_adj`` permiten al servicio replicar el
        cálculo de baja del pandas original (que sumaba la columna
        ``importe_licitacion`` del join — es decir, ``n_adj * importe``).
        """
        where, params = _build_where(filters)
        sql = (
            "SELECT l.id_externo, l.titulo, l.organo_contratacion, l.importe, l.estado, "
            "       adj.nombre AS adjudicatario, adj.sum_adj, adj.n_adj "
            "FROM licitaciones l "
            "LEFT JOIN LATERAL ("
            "  SELECT (SELECT a2.nombre FROM adjudicaciones a2 "
            "          WHERE a2.licitacion_id = l.id_externo AND a2.nombre IS NOT NULL "
            "          ORDER BY a2.id LIMIT 1) AS nombre, "
            "         SUM(a.importe_adjudicado) AS sum_adj, COUNT(*) AS n_adj "
            "  FROM adjudicaciones a WHERE a.licitacion_id = l.id_externo "
            ") adj ON TRUE "
            "WHERE " + where + " AND l.importe IS NOT NULL "
            "ORDER BY l.importe DESC LIMIT ?"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, [*params, n]))

    # ── Trends CPV ───────────────────────────────────────────────────────

    def trends_cpv_ranking(
        self, filters: LicitacionesFilters, *, top_n: int
    ) -> tuple[int, list[dict[str, Any]], str | None, str | None]:
        """(total_cpvs, top-N por importe, periodo_inicio, periodo_fin)."""
        where, params = _build_where(filters)
        guard = _iso_guard("fecha_publicacion")
        base_where = f"{where} AND cpv IS NOT NULL AND {guard}"
        with connect_read() as c:
            row = c.execute(
                "SELECT COUNT(DISTINCT cpv), min(substr(fecha_publicacion, 1, 7)), "
                "       max(substr(fecha_publicacion, 1, 7)) "
                f"FROM licitaciones WHERE {base_where}",
                params,
            ).fetchone()
            total = int(row[0] or 0) if row else 0
            inicio = row[1] if row else None
            fin = row[2] if row else None
            top = rows_to_dicts(
                c.execute(
                    "SELECT cpv, COALESCE(SUM(importe), 0) AS importe_total, "
                    "       COUNT(*) AS count "
                    f"FROM licitaciones WHERE {base_where} "
                    "GROUP BY cpv ORDER BY importe_total DESC, cpv LIMIT ?",
                    [*params, top_n],
                )
            )
        return total, top, inicio, fin

    def trends_cpv_series(
        self, filters: LicitacionesFilters, *, cpvs: list[str]
    ) -> list[dict[str, Any]]:
        """(cpv, mes, count, importe) para los CPVs del top."""
        if not cpvs:
            return []
        where, params = _build_where(filters)
        guard = _iso_guard("fecha_publicacion")
        placeholders = ",".join("?" for _ in cpvs)
        sql = (
            "SELECT cpv, substr(fecha_publicacion, 1, 7) AS mes, "
            "       COUNT(*) AS count, COALESCE(SUM(importe), 0) AS importe "
            "FROM licitaciones "
            f"WHERE {where} AND {guard} AND cpv IN ({placeholders}) "
            "GROUP BY cpv, mes ORDER BY cpv, mes"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, [*params, *cpvs]))

    # ── Proyectos & módulos (detección regex en el motor) ────────────────

    def proyectos_modulos_stats(
        self,
        filters: LicitacionesFilters,
        *,
        module_patterns: dict[str, str],
        all_pattern: str,
    ) -> tuple[dict[str, tuple[int, float]], int, float]:
        """Conteo/importe por módulo + (clasificadas, importe distinct).

        Los patrones llegan como regex POSIX (mismas alternancias escapadas que
        compilaba el servicio con ``re.IGNORECASE``); ``~* ?`` los evalúa en el
        motor sobre ``titulo`` — la columna de texto disponible en la
        proyección de stats (la detección pandas usaba titulo+descripcion solo
        si descripcion existía, y en stats no existe).
        """
        where, params = _build_where(filters)
        selects: list[str] = []
        run_params: list[Any] = []
        for pattern in module_patterns.values():
            selects.append("COUNT(*) FILTER (WHERE titulo ~* ?)")
            selects.append("COALESCE(SUM(importe) FILTER (WHERE titulo ~* ?), 0)")
            run_params.extend([pattern, pattern])
        selects.append("COUNT(*) FILTER (WHERE titulo ~* ?)")
        selects.append("COALESCE(SUM(importe) FILTER (WHERE titulo ~* ?), 0)")
        run_params.extend([all_pattern, all_pattern])
        sql = "SELECT " + ", ".join(selects) + " FROM licitaciones WHERE " + where
        with connect_read() as c:
            row = c.execute(sql, [*run_params, *params]).fetchone()
        if row is None:
            return {}, 0, 0.0
        por_modulo: dict[str, tuple[int, float]] = {}
        for i, mod in enumerate(module_patterns):
            count = int(row[i * 2] or 0)
            if count:
                por_modulo[mod] = (count, float(row[i * 2 + 1] or 0.0))
        total_clasificados = int(row[-2] or 0)
        importe_distinct = float(row[-1] or 0.0)
        return por_modulo, total_clasificados, importe_distinct

    def proyectos_modulos_yoy(
        self,
        filters: LicitacionesFilters,
        *,
        module_patterns: dict[str, str],
        hace_365d_iso: str,
        hace_730d_iso: str,
    ) -> dict[str, tuple[int, int]]:
        """{módulo: (n_act, n_prev)} en ventanas de 12 meses consecutivas."""
        where, params = _build_where(filters)
        col = "fecha_publicacion"
        guard = _iso_guard(col)
        selects: list[str] = []
        run_params: list[Any] = []
        for pattern in module_patterns.values():
            selects.append(f"COUNT(*) FILTER (WHERE titulo ~* ? AND {guard} AND {col} >= ?)")
            selects.append(
                f"COUNT(*) FILTER (WHERE titulo ~* ? AND {guard} AND {col} < ? AND {col} >= ?)"
            )
            run_params.extend([pattern, hace_365d_iso, pattern, hace_365d_iso, hace_730d_iso])
        sql = "SELECT " + ", ".join(selects) + " FROM licitaciones WHERE " + where
        with connect_read() as c:
            row = c.execute(sql, [*run_params, *params]).fetchone()
        if row is None:
            return {}
        return {
            mod: (int(row[i * 2] or 0), int(row[i * 2 + 1] or 0))
            for i, mod in enumerate(module_patterns)
        }

    def tipos_contrato_breakdown(self, filters: LicitacionesFilters) -> list[dict[str, Any]]:
        """(tipo_contrato, count, importe) — NULL/'' excluidos, count DESC."""
        where, params = _build_where(filters)
        sql = (
            "SELECT tipo_contrato, COUNT(*) AS count, COALESCE(SUM(importe), 0) AS importe "
            "FROM licitaciones "
            "WHERE " + where + " AND tipo_contrato IS NOT NULL AND trim(tipo_contrato) != '' "
            "GROUP BY tipo_contrato ORDER BY count DESC, tipo_contrato"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, params))

    def tipo_estado_crosstab(self, filters: LicitacionesFilters) -> list[dict[str, Any]]:
        """(tipo_contrato, estado, n) — tipo NULL/'' y estado NULL excluidos.

        Paridad con el ``groupby(["tipo","estado"])`` de pandas, que descartaba
        los NaN de ambas columnas.
        """
        where, params = _build_where(filters)
        sql = (
            "SELECT tipo_contrato, estado, COUNT(*) AS n FROM licitaciones "
            "WHERE " + where + " AND tipo_contrato IS NOT NULL AND trim(tipo_contrato) != '' "
            "AND estado IS NOT NULL "
            "GROUP BY tipo_contrato, estado ORDER BY tipo_contrato, estado"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, params))

    def cpv_top_por_count(self, filters: LicitacionesFilters, *, n: int) -> list[dict[str, Any]]:
        """(cpv, count, importe) top-N por count — cpv NULL/'' excluido."""
        where, params = _build_where(filters)
        sql = (
            "SELECT cpv, COUNT(*) AS count, COALESCE(SUM(importe), 0) AS importe "
            "FROM licitaciones "
            "WHERE " + where + " AND cpv IS NOT NULL AND trim(cpv) != '' "
            "GROUP BY cpv ORDER BY count DESC, cpv LIMIT ?"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, [*params, n]))

    # ── Quality ──────────────────────────────────────────────────────────

    _QUALITY_TEXT_COLS = (
        "id_externo",
        "titulo",
        "organo_contratacion",
        "estado",
        "fecha_publicacion",
        "ccaa",
        "cpv",
        "url",
        "tecnologia",
        "tipo_contrato",
        "provincia",
    )

    def quality_completitud(self) -> dict[str, Any]:
        """Total, conteos de completitud por columna y formato ISO de fechas.

        El check ISO opera sobre el STRING crudo de ``fecha_publicacion`` —
        que es exactamente lo que el camino pandas perdió cuando
        ``load_stats_base_df`` empezó a convertir la columna a ``Timestamp``
        (ítem del backlog «quality.py ya no detecta fechas legacy
        malformadas»): en SQL la columna TEXT sigue cruda.
        """
        selects = ["COUNT(*) AS total"]
        for col in self._QUALITY_TEXT_COLS:
            selects.append(f"COUNT(*) FILTER (WHERE {col} IS NOT NULL AND trim({col}) != '')")
        selects.append("COUNT(*) FILTER (WHERE importe IS NOT NULL)")
        selects.append(
            r"COUNT(*) FILTER (WHERE fecha_publicacion ~ '^\d{4}-\d{2}-\d{2}') AS fecha_iso"
        )
        sql = "SELECT " + ", ".join(selects) + " FROM licitaciones"
        with connect_read() as c:
            row = c.execute(sql).fetchone()
        if row is None:
            return {"total": 0, "cols": {}, "importe": 0, "fecha_iso": 0}
        cols = {col: int(row[i + 1] or 0) for i, col in enumerate(self._QUALITY_TEXT_COLS)}
        return {
            "total": int(row[0] or 0),
            "cols": cols,
            "importe": int(row[len(self._QUALITY_TEXT_COLS) + 1] or 0),
            "fecha_iso": int(row[len(self._QUALITY_TEXT_COLS) + 2] or 0),
        }

    # ── Forecast ─────────────────────────────────────────────────────────

    def forecast_monthly(
        self, filters: LicitacionesFilters, *, metric: str
    ) -> list[dict[str, Any]]:
        """Serie mensual (mes YYYY-MM, valor) para el forecast de volumen."""
        where, params = _build_where(filters)
        guard = _iso_guard("fecha_publicacion")
        agg = "COALESCE(SUM(importe), 0)" if metric == "sum" else "COUNT(*)"
        sql = (
            f"SELECT substr(fecha_publicacion, 1, 7) AS mes, {agg} AS valor "
            "FROM licitaciones "
            f"WHERE {where} AND {guard} "
            "GROUP BY mes ORDER BY mes"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, params))

    def retendering_universe(self, filters: LicitacionesFilters) -> list[dict[str, Any]]:
        """Proyección acotada para el forecast de re-licitación (ADR-023).

        Solo filas que PUEDEN producir una fecha de fin estimada (duración
        positiva o ``fecha_fin`` explícita) — el resto quedaba descartado por
        ``dias_hasta_fin`` NaN en el pandas original.
        """
        where, params = _build_where(filters)
        sql = (
            "SELECT id_externo, titulo, organo_contratacion, importe, "
            "       fecha_publicacion, duracion_valor, duracion_unidad, "
            "       fecha_inicio, fecha_fin "
            "FROM licitaciones "
            f"WHERE {where} AND ((duracion_valor IS NOT NULL AND duracion_valor > 0) "
            "       OR fecha_fin IS NOT NULL)"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, params))

    def adjudicaciones_para_forecast(self, ids: list[str]) -> list[dict[str, Any]]:
        """Adjudicaciones (columnas del forecast) para una lista de licitaciones."""
        if not ids:
            return []
        sql = (
            "SELECT licitacion_id, fecha_adjudicacion, importe_adjudicado, "
            "       n_ofertas_recibidas, nombre "
            "FROM adjudicaciones WHERE licitacion_id = ANY(?)"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, [ids]))

    # ── Scoring / pipeline: proyecciones acotadas y contexto ─────────────

    # Columnas que _score_row (services/analytics/scoring.py) necesita leer.
    _SCORING_COLS = (
        "id_externo, titulo, organo_contratacion, importe, cpv, "
        "fecha_limite, estado, ccaa, tecnologia, fecha_publicacion"
    )

    def importe_percentiles(self) -> tuple[float, float]:
        """(P10, P90) de importe sobre TODA la tabla (contexto de scoring).

        Sin filtros a propósito: el contexto de percentiles del scoring se
        calcula sobre el dataset completo para no sesgarse por el subconjunto
        filtrado (misma semántica que el ``base_df`` original).
        ``percentile_cont`` interpola linealmente, igual que
        ``Series.quantile`` por defecto.
        """
        sql = (
            "SELECT percentile_cont(0.10) WITHIN GROUP (ORDER BY importe), "
            "       percentile_cont(0.90) WITHIN GROUP (ORDER BY importe) "
            "FROM licitaciones WHERE importe IS NOT NULL"
        )
        with connect_read() as c:
            row = c.execute(sql).fetchone()
        if row is None or row[0] is None:
            return 0.0, 0.0
        return float(row[0]), float(row[1] or 0.0)

    def scoring_candidates(
        self, *, estados: tuple[str, ...] = ("PUB", "EV")
    ) -> list[dict[str, Any]]:
        """Proyección acotada de candidatas a oportunidad (estados activos).

        ADR-023: el scoring puntuaba la tabla entera vía pandas; una
        licitación cerrada/adjudicada nunca es una "oportunidad", así que el
        universo puntuable son los estados activos — una fracción del total.
        """
        placeholders = ",".join("?" for _ in estados)
        sql = f"SELECT {self._SCORING_COLS} FROM licitaciones WHERE estado IN ({placeholders})"
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, list(estados)))

    def licitaciones_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        """Proyección de scoring para una lista exacta de ids (modo page-aligned)."""
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        sql = f"SELECT {self._SCORING_COLS} FROM licitaciones WHERE id_externo IN ({placeholders})"
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, ids))

    def pipeline_window(
        self,
        filters: LicitacionesFilters,
        *,
        hoy_iso: str,
        hasta_iso: str,
    ) -> list[dict[str, Any]]:
        """Licitaciones con fecha_limite en (hoy, hoy+dias] — la ventana del pipeline.

        Proyección acotada por construcción: la ventana de vencimientos (≤365
        días) es una fracción pequeña de la tabla, y los buckets/scoring
        posteriores operan en Python sobre ese resultado ya reducido.
        """
        where, params = _build_where(filters)
        guard = _iso_guard("fecha_limite")
        sql = (
            f"SELECT {self._SCORING_COLS} FROM licitaciones "
            f"WHERE {where} AND {guard} AND fecha_limite > ? AND fecha_limite < ? "
            "ORDER BY fecha_limite"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, [*params, hoy_iso, hasta_iso]))

    def tecnologia_detalle_kpis(
        self, filters: LicitacionesFilters, *, tech_codes: list[str]
    ) -> tuple[int, float, float]:
        """(n, importe_total, importe_medio) — dedup por id_externo (evita doble

        conteo del explode). ``importe_medio`` usa ``AVG`` (ignora NULLs, igual
        que ``Series.mean(skipna=True)``) — puede diferir de
        ``importe_total / n`` si hay filas con ``importe`` nulo entre las ``n``.
        """
        if not tech_codes:
            return 0, 0.0, 0.0
        where, params = _build_where(filters)
        placeholders = ",".join("?" for _ in tech_codes)
        sql = (
            "SELECT COUNT(*) AS n, COALESCE(SUM(importe), 0) AS importe_total, "
            "       AVG(importe) AS importe_medio FROM ("
            "  SELECT DISTINCT ON (l.id_externo) l.id_externo, l.importe "
            "  FROM licitaciones l, "
            "       unnest(string_to_array(COALESCE(l.tecnologia, ''), ',')) AS code "
            "  WHERE " + where + f" AND trim(code) IN ({placeholders}) "
            ") sub"
        )
        with connect_read() as c:
            row = c.execute(sql, [*params, *tech_codes]).fetchone()
        if row is None:
            return 0, 0.0, 0.0
        return (
            int(row[0] or 0),
            float(row[1] or 0.0),
            float(row[2]) if row[2] is not None else 0.0,
        )
