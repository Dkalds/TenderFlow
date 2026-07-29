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
  de forma lexicográfica, igual que los filtros. Se guardan con un regex de
  prefijo ISO (``~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'``) para excluir filas
  claramente malformadas del cálculo, replicando el ``errors="coerce"`` +
  ``dropna`` que hacía pandas fila a fila.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from db.database import connect_read
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)

_ISO_DATE_RE = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}"


def _iso_guard(column: str) -> str:
    """Cláusula que excluye fechas claramente malformadas (mirror de coerce+dropna)."""
    return f"{column} ~ '{_ISO_DATE_RE}'"


def _escape_like(s: str) -> str:
    """Escapa comodines de LIKE/ILIKE (``%``, ``_``) en input de usuario."""
    return s.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


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
            f"  COUNT(*) FILTER (WHERE {pub_guard} AND fecha_publicacion >= ?) AS nuevas_24h "
            "FROM filtered"
        )
        run_params = [*params, hoy_iso, hoy_iso, limite_48h_iso, hace_24h_iso]
        with connect_read() as c:
            row = c.execute(sql, run_params).fetchone()
        if row is None:
            return {"calientes_hoy": 0, "vencen_48h": 0, "nuevas_24h": 0}
        calientes, vencen, nuevas = row
        return {
            "calientes_hoy": int(calientes or 0),
            "vencen_48h": int(vencen or 0),
            "nuevas_24h": int(nuevas or 0),
        }

    # ── Tecnologias ──────────────────────────────────────────────────────

    def tecnologias_total_y_sin_clasificar(
        self, filters: LicitacionesFilters
    ) -> tuple[int, int]:
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
