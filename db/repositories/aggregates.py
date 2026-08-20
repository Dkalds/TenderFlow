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

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from db.database import connect_read
from db.repositories.base import loose_distinct_count, rows_to_dicts
from db.repositories.tecnologia_pliego import NO_SIGNAL_SENTINEL
from db.sql_fragments import TECHNOLOGY_OBSERVED_SQL
from observability.logging import get_logger
from shared.estados import ESTADOS_CERRADOS, abierta_sql

log = get_logger(__name__)


@contextmanager
def _lectura(conn: Any | None) -> Iterator[Any]:
    """Reutiliza la conexión dada, o abre una de lectura si no hay ninguna.

    Lo aprovecha el precálculo de KPIs, que ya corre dentro de una transacción
    con su propia conexión: sin esto abriría cinco más para preguntar lo mismo,
    reteniendo slots del pool mientras sostiene la de escritura. Y lo que
    permite es que el snapshot lo calculen **estas mismas funciones** en vez de
    una copia del SQL en el scheduler que hubiera que mantener sincronizada a
    mano — que es exactamente como el resumen y el Radar acabaron contando
    cosas distintas.

    ``conn`` va tipado como ``Any`` porque es el objeto de conexión de psycopg,
    igual que en el resto de helpers de ``db/repositories``.
    """
    if conn is not None:
        yield conn
    else:
        with connect_read() as abierta:
            yield abierta


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
    # "Sólo las que siguen abiertas": descarta los estados terminales en vez de
    # enumerar los abiertos (ver shared/estados.py). No es redundante con
    # ``estado``: ése fija uno concreto, éste excluye el cierre y deja pasar
    # cualquier código que la fuente publique mañana.
    solo_abiertas: bool = False

    def is_empty(self) -> bool:
        """True si ningún filtro está activo, es decir, si el ámbito es la tabla entera.

        Es la condición que habilita los caminos precalculados del overview: un
        agregado global solo se puede servir desde un snapshot si la pregunta
        es efectivamente global.

        Deliberadamente estricta. ``_build_where`` ignora un ``q`` en blanco o
        un ``ccaa`` vacío, así que hay filtros que no añaden cláusula y aun así
        se cuentan aquí como activos: equivocarse por este lado significa
        calcular en vivo algo que se podría haber leído del snapshot, y por el
        otro significaría servir un número que no corresponde al filtro pedido.
        """
        return self == LicitacionesFilters()


def build_licitaciones_where(
    filters: LicitacionesFilters, *, alias: str | None = None
) -> tuple[str, list[Any]]:
    """Construye el ``WHERE`` (dialecto qmark) desde :class:`LicitacionesFilters`.

    ``alias`` califica las columnas (``l.estado``) para las consultas que cruzan
    ``licitaciones`` con otra tabla — el drill-down de un órgano acota así sus
    adjudicaciones con el mismo ámbito que sus licitaciones, en vez de dejar
    que "top adjudicatario" y "lead time" midan el histórico completo mientras
    los KPIs de al lado miden el filtro. Sin ``alias`` las columnas van
    desnudas, como en las agregaciones que leen sólo de ``licitaciones``.
    """

    def col(name: str) -> str:
        return f"{alias}.{name}" if alias else name

    clauses: list[str] = ["1 = 1"]
    params: list[Any] = []

    if filters.fecha_desde:
        clauses.append(f"{col('fecha_publicacion')} >= %s")
        params.append(filters.fecha_desde)
    if filters.fecha_hasta:
        clauses.append(f"{col('fecha_publicacion')} <= %s")
        params.append(filters.fecha_hasta)
    if filters.ccaa:
        clauses.append(f"{col('ccaa')} = %s")
        params.append(filters.ccaa)
    if filters.tecnologia:
        clauses.append(f"{col('tecnologia')} = %s")
        params.append(filters.tecnologia)
    if filters.estado:
        clauses.append(f"{col('estado')} = %s")
        params.append(filters.estado)
    if filters.solo_abiertas:
        clauses.append(abierta_sql(col("estado")))
    if filters.importe_min is not None:
        clauses.append(f"{col('importe')} >= %s")
        params.append(filters.importe_min)
    if filters.q and filters.q.strip():
        needle = f"%{_escape_like(filters.q.strip())}%"
        clauses.append(
            f"({col('titulo')} ILIKE %s ESCAPE '\\' "
            f"OR {col('organo_contratacion')} ILIKE %s ESCAPE '\\' "
            f"OR {col('id_externo')} ILIKE %s ESCAPE '\\')"
        )
        params.extend([needle, needle, needle])
    if filters.cpv:
        clauses.append(f"{col('cpv')} = %s")
        params.append(filters.cpv)

    return " AND ".join(clauses), params


# Nombre interno histórico: los call sites de este módulo agregan sobre
# ``licitaciones`` a secas y nunca pasan ``alias``.
_build_where = build_licitaciones_where


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

    def overview_kpis(
        self, filters: LicitacionesFilters, *, conn: Any | None = None
    ) -> dict[str, Any]:
        """total, importe_total, importe_medio, organos_unicos — un SELECT."""
        where, params = _build_where(filters)
        sql = (
            "SELECT COUNT(*) AS total, "
            "       COALESCE(SUM(importe), 0) AS importe_total, "
            "       AVG(importe) AS importe_medio, "
            "       COUNT(DISTINCT organo_contratacion) AS organos "
            "FROM licitaciones WHERE " + where
        )
        with _lectura(conn) as c:
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
            "GROUP BY organo_contratacion ORDER BY n DESC LIMIT %s"
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

    def overview_adjudicaciones_indicadores(
        self, *, conn: Any | None = None
    ) -> dict[str, float | None]:
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
            "  ) t WHERE lead > 0) AS lead_time_medio, "
            # Denominador `COUNT(*)` (no solo las filas con es_pyme no nulo)
            # para dar el mismo resultado que services/analytics/competitors.py,
            # que trata el NULL como "no PYME". Dos KPIs con el mismo nombre y
            # distinta base serían peor que un solo número conservador.
            "  (SELECT 100.0 * COUNT(*) FILTER (WHERE es_pyme = 1) "
            "          / NULLIF(COUNT(*), 0) "
            "   FROM adjudicaciones) AS pct_pyme"
        )
        with _lectura(conn) as c:
            row = c.execute(sql).fetchone()
        if row is None:
            return {
                "hhi": 0.0,
                "pct_oferta_unica": 0.0,
                "lead_time_medio": None,
                "pct_pyme": 0.0,
            }
        hhi, pct_oferta_unica, lead_time, pct_pyme = row
        lead_val = float(lead_time) if lead_time is not None and float(lead_time) > 0 else None
        return {
            "hhi": float(hhi or 0.0),
            "pct_oferta_unica": float(pct_oferta_unica or 0.0),
            "lead_time_medio": lead_val,
            "pct_pyme": float(pct_pyme or 0.0),
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
            f"  COUNT(*) FILTER (WHERE {guard} AND {col} >= %s) AS lics_30d, "
            f"  COUNT(*) FILTER (WHERE {guard} AND {col} < %s AND {col} >= %s) AS lics_prev30d, "
            f"  COALESCE(SUM(importe) FILTER (WHERE {guard} AND {col} >= %s), 0)"
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
        """CCAA distintas presentes en el ámbito.

        Sin filtros va por *loose index scan*: ``COUNT(DISTINCT ccaa)`` sobre la
        tabla entera medía 30,9 s de media en producción (35 llamadas, 84,5 s de
        pico) para devolver un número de dos cifras. Con filtros se mantiene el
        ``COUNT(DISTINCT)``, que ahí sí opera sobre un subconjunto y no puede
        saltar por el índice.
        """
        if filters.is_empty():
            with connect_read() as c:
                return loose_distinct_count(c, "licitaciones", "ccaa")
        where, params = _build_where(filters)
        sql = "SELECT COUNT(DISTINCT ccaa) FROM licitaciones WHERE " + where
        with connect_read() as c:
            row = c.execute(sql, params).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def overview_tasa_anulacion(
        self, filters: LicitacionesFilters, *, hace_365d_iso: str, conn: Any | None = None
    ) -> tuple[int, int]:
        """(anul_count, total_count) sobre fecha_publicacion >= hoy-365d."""
        where, params = _build_where(filters)
        guard = _iso_guard("fecha_publicacion")
        sql = (
            "SELECT "
            "  COUNT(*) FILTER (WHERE estado = 'ANUL') AS anul, "
            "  COUNT(*) AS total "
            "FROM licitaciones "
            f"WHERE {where} AND {guard} AND fecha_publicacion >= %s"
        )
        with _lectura(conn) as c:
            row = c.execute(sql, [*params, hace_365d_iso]).fetchone()
        if row is None:
            return 0, 0
        return int(row[0] or 0), int(row[1] or 0)

    def importe_p75(self, *, conn: Any | None = None) -> float | None:
        """Percentil 75 de ``importe`` sobre toda la tabla.

        Alimenta el snapshot que habilita el camino rápido de
        :meth:`overview_para_hoy`, y es justo la parte cara de aquel cálculo:
        ``percentile_cont`` ordena todos los importes y con ``work_mem`` a
        3,5 MB eso se derrama a disco.

        ``None`` cuando no hay ningún importe. El llamante debe tratarlo como
        "sin umbral" y nunca como cero, que contaría todas las filas.
        """
        sql = (
            "SELECT percentile_cont(0.75) WITHIN GROUP (ORDER BY importe) "
            "FROM licitaciones WHERE importe IS NOT NULL"
        )
        with _lectura(conn) as c:
            row = c.execute(sql).fetchone()
        if row is None or row[0] is None:
            return None
        return float(row[0])

    def count_total_activas(self, *, conn: Any | None = None) -> int:
        """Expedientes no terminales en toda la tabla, para el snapshot."""
        sql = f"SELECT COUNT(*) FROM licitaciones WHERE {abierta_sql()}"
        with _lectura(conn) as c:
            row = c.execute(sql).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def overview_para_hoy(
        self,
        filters: LicitacionesFilters,
        *,
        hoy_iso: str,
        limite_48h_iso: str,
        hace_24h_iso: str,
        p75: float | None = None,
        total_activas: int | None = None,
    ) -> dict[str, int]:
        """Los cuatro contadores del bloque "para hoy".

        Compartido por ``services/analytics/overview.py`` (que ignora
        ``total_activas``) y por ``services/analytics/resumen.py``
        (``/analytics/resumen/hoy``, que los usa los cuatro): son los mismos
        contadores sobre el mismo conjunto filtrado, así que duplicar el SQL
        sería duplicar también las convenciones de fecha y el P75.

        ``p75`` y ``total_activas`` son los dos valores globales que el
        precálculo de KPIs deja en ``kpi_snapshots``. Si llegan **y** el ámbito
        es la tabla entera, se sirve por :meth:`_para_hoy_fast`; en cualquier
        otro caso se calcula todo en vivo, que con filtros es la única opción
        correcta.
        """
        if filters.is_empty() and p75 is not None and total_activas is not None:
            return self._para_hoy_fast(
                hoy_iso=hoy_iso,
                limite_48h_iso=limite_48h_iso,
                hace_24h_iso=hace_24h_iso,
                p75=p75,
                total_activas=total_activas,
            )
        where, params = _build_where(filters)
        pub_guard = _iso_guard("fecha_publicacion")
        lim_guard = _iso_guard("fecha_limite")
        # `abierta_sql()` y no `estado IN ('PUB','EV')`: con la lista blanca,
        # `total_activas` daba 0 sobre datos donde el Radar listaba 12 — todos
        # en `ADM`, que no es terminal. Ver `shared/estados.py`.
        abierta = abierta_sql()
        # Proyección explícita y no `SELECT *`: `filtered` se referencia dos
        # veces (en `p75` y en el FROM final), así que Postgres la materializa
        # en lugar de inlinearla. Con `SELECT *` eso son 1,64 M filas completas
        # —los ~46 bytes de estas cuatro columnas frente a la fila entera— que
        # con `work_mem` a 2 MB se derraman a disco y se releen dos veces.
        # Medido en producción el 2026-08-10: 26,5 s de media antes, 20,1 s con
        # la proyección acotada. Las cuatro columnas son exactamente las que
        # usan los FILTER de abajo; el WHERE del CTE se evalúa contra
        # `licitaciones`, así que `_build_where` puede seguir citando cualquier
        # otra columna.
        sql = (
            "WITH filtered AS (SELECT importe, fecha_limite, fecha_publicacion, estado "
            "                  FROM licitaciones WHERE " + where + "), "
            "p75 AS (SELECT percentile_cont(0.75) WITHIN GROUP (ORDER BY importe) AS v "
            "        FROM filtered WHERE importe IS NOT NULL) "
            "SELECT "
            "  COUNT(*) FILTER ("
            f"    WHERE {abierta} "
            f"     AND {lim_guard} AND fecha_limite > %s "
            "      AND importe >= (SELECT v FROM p75)"
            "  ) AS calientes_hoy, "
            f"  COUNT(*) FILTER (WHERE {lim_guard} AND fecha_limite >= %s AND fecha_limite <= %s)"
            "     AS vencen_48h, "
            f"  COUNT(*) FILTER (WHERE {pub_guard} AND fecha_publicacion >= %s) AS nuevas_24h, "
            f"  COUNT(*) FILTER (WHERE {abierta}) AS total_activas "
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

    def _para_hoy_fast(
        self,
        *,
        hoy_iso: str,
        limite_48h_iso: str,
        hace_24h_iso: str,
        p75: float,
        total_activas: int,
    ) -> dict[str, int]:
        """Los tres contadores con ventana, cada uno por su índice.

        Misma pregunta y mismos predicados que la rama con CTE, pero sin
        materializar ``filtered``: los tres acotan ventanas estrechas —plazo
        posterior a hoy, plazo dentro de 48 h, publicadas en 24 h— que
        ``idx_lic_fecha_limite`` e ``idx_fecha_pub`` resuelven por rango en vez
        de recorrer 1,64 M filas para contar unas pocas. ``total_activas`` no
        tiene ventana que acotar —es un recuento global por estado— así que
        viene del snapshot en lugar de calcularse aquí.

        Los ``_iso_guard`` se conservan literalmente aunque el corte por fecha
        implique ya el extremo inferior: el techo ``< '3000'`` no lo implica, y
        repetirlos tal cual es lo que hace evidente que las dos ramas cuentan
        lo mismo. Como son rangos sobre la misma columna, Postgres los funde en
        un único recorrido del índice.
        """
        abierta = abierta_sql()
        pub_guard = _iso_guard("fecha_publicacion")
        lim_guard = _iso_guard("fecha_limite")
        sql = (
            "SELECT "
            "  (SELECT COUNT(*) FROM licitaciones "
            f"    WHERE {abierta} AND {lim_guard} AND fecha_limite > %s "
            "      AND importe >= %s) AS calientes_hoy, "
            "  (SELECT COUNT(*) FROM licitaciones "
            f"    WHERE {lim_guard} AND fecha_limite >= %s AND fecha_limite <= %s) "
            "     AS vencen_48h, "
            "  (SELECT COUNT(*) FROM licitaciones "
            f"    WHERE {pub_guard} AND fecha_publicacion >= %s) AS nuevas_24h"
        )
        run_params: list[Any] = [hoy_iso, p75, hoy_iso, limite_48h_iso, hace_24h_iso]
        with connect_read() as c:
            row = c.execute(sql, run_params).fetchone()
        if row is None:
            return {"calientes_hoy": 0, "vencen_48h": 0, "nuevas_24h": 0, "total_activas": 0}
        return {
            "calientes_hoy": int(row[0] or 0),
            "vencen_48h": int(row[1] or 0),
            "nuevas_24h": int(row[2] or 0),
            "total_activas": total_activas,
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
            "ORDER BY fecha_publicacion DESC LIMIT %s"
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
        where = f"{guard} AND fecha_publicacion > %s"
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
                    "ORDER BY fecha_publicacion DESC LIMIT %s",
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
            "  SELECT organo FROM exploded GROUP BY organo ORDER BY COUNT(*) DESC LIMIT %s"
            "), top_techs AS ("
            "  SELECT code FROM exploded GROUP BY code ORDER BY COUNT(*) DESC LIMIT %s"
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
            "  SELECT ccaa FROM exploded GROUP BY ccaa ORDER BY COUNT(*) DESC LIMIT %s"
            "), top_techs AS ("
            "  SELECT code FROM exploded GROUP BY code ORDER BY COUNT(*) DESC LIMIT %s"
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
            "  SELECT code FROM exploded GROUP BY code ORDER BY COUNT(*) DESC LIMIT %s"
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
        placeholders = ",".join("%s" for _ in tech_codes)
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
            f"  COUNT(*) FILTER (WHERE {guard} AND {col} >= %s) AS cnt_cur, "
            f"  COUNT(*) FILTER (WHERE {guard} AND {col} < %s AND {col} >= %s) AS cnt_prev, "
            f"  COALESCE(SUM(importe) FILTER (WHERE {guard} AND {col} >= %s), 0) AS imp_cur, "
            f"  COALESCE(SUM(importe) FILTER (WHERE {guard} AND {col} < %s AND {col} >= %s), 0)"
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
            where += f" AND {_fold_expr('organo_contratacion')} LIKE %s ESCAPE '\\'"
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
            "GROUP BY organo_contratacion ORDER BY count DESC, organo_contratacion LIMIT %s"
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
            "  GROUP BY organo_contratacion ORDER BY COUNT(*) DESC LIMIT %s"
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
        por id de fila); ``sum_adj`` (total adjudicado del expediente) y ``n_adj``
        (nº de adjudicaciones/lotes) permiten al servicio calcular la baja
        agregada como ``1 - sum_adj / l.importe`` — todo lo adjudicado contra el
        presupuesto ÚNICO del expediente. NO multiplicar el presupuesto por
        ``n_adj``: eso replicaba el bug del pandas original, que sumaba
        ``importe_licitacion`` una vez por fila del join (n_adj * importe).
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
            "ORDER BY l.importe DESC LIMIT %s"
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
                    "GROUP BY cpv ORDER BY importe_total DESC, cpv LIMIT %s",
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
        placeholders = ",".join("%s" for _ in cpvs)
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
        compilaba el servicio con ``re.IGNORECASE``); ``~* %s`` los evalúa en el
        motor sobre ``titulo`` — la columna de texto disponible en la
        proyección de stats (la detección pandas usaba titulo+descripcion solo
        si descripcion existía, y en stats no existe).
        """
        where, params = _build_where(filters)
        selects: list[str] = []
        run_params: list[Any] = []
        for pattern in module_patterns.values():
            selects.append("COUNT(*) FILTER (WHERE titulo ~* %s)")
            selects.append("COALESCE(SUM(importe) FILTER (WHERE titulo ~* %s), 0)")
            run_params.extend([pattern, pattern])
        selects.append("COUNT(*) FILTER (WHERE titulo ~* %s)")
        selects.append("COALESCE(SUM(importe) FILTER (WHERE titulo ~* %s), 0)")
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
            selects.append(f"COUNT(*) FILTER (WHERE titulo ~* %s AND {guard} AND {col} >= %s)")
            selects.append(
                f"COUNT(*) FILTER (WHERE titulo ~* %s AND {guard} AND {col} < %s AND {col} >= %s)"
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
            "GROUP BY cpv ORDER BY count DESC, cpv LIMIT %s"
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
            "FROM adjudicaciones WHERE licitacion_id = ANY(%s)"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, [ids]))

    # ── Clustering online ────────────────────────────────────────────────

    def clustering_universe(
        self, filters: LicitacionesFilters, *, max_rows: int
    ) -> tuple[list[dict[str, Any]], int]:
        """(filas proyectadas, total sin recortar) para el clustering online.

        Justificación ADR-023: el clustering TF-IDF + KMeans no es expresable
        en SQL, pero la carga queda acotada — 7 columnas y como mucho
        ``max_rows`` filas (las más recientes por ``fecha_publicacion``, un
        recorte determinista que sustituye al ``sample`` aleatorio del camino
        full-table). ``total`` se calcula aparte para que el recorte no
        distorsione el conteo reportado.
        """
        where, params = _build_where(filters)
        base = f"FROM licitaciones WHERE {where} AND titulo IS NOT NULL"
        with connect_read() as c:
            row = c.execute(f"SELECT COUNT(*) {base}", params).fetchone()
            total = int(row[0] or 0) if row is not None else 0
            if total == 0:
                return [], 0
            rows = rows_to_dicts(
                c.execute(
                    "SELECT id_externo, titulo, organo_contratacion, importe, "
                    "       ccaa, estado, cpv "
                    f"{base} ORDER BY fecha_publicacion DESC NULLS LAST LIMIT %s",
                    [*params, max_rows],
                )
            )
        return rows, total

    # ── Drill-down por órgano ────────────────────────────────────────────

    def licitaciones_por_organo(
        self, organo: str, filters: LicitacionesFilters
    ) -> list[dict[str, Any]]:
        """Proyección ACOTADA de las licitaciones de UN órgano (ADR-023).

        El scoring y la estacionalidad del drill-down operan en pandas sobre
        este subconjunto — acotado por definición al órgano pedido.
        ``fecha_limite`` está porque el ranking usa el motor de scoring real,
        que puntúa el plazo: sin esa columna todas las filas del drill-down
        saldrían marcadas ``sin_plazo``.
        """
        where, params = _build_where(filters)
        sql = (
            "SELECT id_externo, titulo, organo_contratacion, importe, cpv, "
            "       tipo_contrato, estado, fecha_publicacion, fecha_limite, "
            "       ccaa, tecnologia, url "
            "FROM licitaciones "
            f"WHERE {where} AND organo_contratacion = %s"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, [*params, organo]))

    # ── Scoring / pipeline: proyecciones acotadas y contexto ─────────────

    # Columnas que _score_row (services/analytics/scoring.py) necesita leer.
    # `descripcion` no se expone en la respuesta: es insumo de la afinidad, que
    # antes solo miraba el título — y el título de un pliego español rara vez
    # nombra la tecnología. En PLACSP viene del `<summary>` ATOM, así que son
    # cadenas cortas sobre ~1,6 k filas.
    # `fuente` no puntúa: viaja con `url` porque es lo que decide cómo se
    # etiqueta ese enlace en el inspector del Radar (PLACSP, TED, PSCP…).
    _SCORING_COLS = (
        "id_externo, titulo, descripcion, organo_contratacion, importe, cpv, "
        "fecha_limite, estado, ccaa, tecnologia, fecha_publicacion, ml_tech_principal, url, "
        "fuente"
    )

    def importe_percentiles(self) -> tuple[float, float]:
        """(P10, P90) de importe sobre TODA la tabla.

        Fallback de ``importe_percentiles_universo`` para cuando el universo
        vivo tiene tan pocos importes que sus percentiles serían ruido: ahí una
        distribución estable —aunque contaminada— discrimina mejor que una
        calculada sobre un puñado de filas. No lo llames directamente desde el
        scoring; el llamante es ``services.analytics.scoring_signals``.

        Sin filtros a propósito. ``percentile_cont`` interpola linealmente,
        igual que ``Series.quantile`` por defecto.
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

    def importe_percentiles_universo(
        self,
        *,
        hoy_iso: str,
        cerrados: tuple[str, ...] = ESTADOS_CERRADOS,
    ) -> tuple[float, float, int]:
        """(P10, P90, nº de importes) sobre el universo puntuable.

        El predicado es **el mismo** que el de ``scoring_candidates``: si uno
        cambia, el otro también. La dimensión ``importe`` del score normaliza
        una oportunidad contra la distribución de este resultado, así que la
        población de referencia tiene que ser aquella en la que esa oportunidad
        compite —el mercado abierto de hoy—, no la tabla entera: de sus
        1.640.915 filas (medido 2026-08-11) el 91% son avisos agregados de PSCP
        sin plazo propio que nunca fueron oportunidades. Con esa referencia, un
        contrato de 300 k€ se comparaba contra un corpus cuyos percentiles
        describen otro mercado.

        Devuelve también el conteo para que el llamante decida si la muestra da
        para percentiles o conviene caer al fallback global.
        """
        placeholders = ",".join("%s" for _ in cerrados)
        guard = _iso_guard("fecha_limite")
        sql = (
            "SELECT percentile_cont(0.10) WITHIN GROUP (ORDER BY importe), "
            "       percentile_cont(0.90) WITHIN GROUP (ORDER BY importe), "
            "       COUNT(importe) "
            "FROM licitaciones "
            f"WHERE (estado IS NULL OR estado NOT IN ({placeholders})) "
            f"  AND {guard} AND fecha_limite >= %s "
            "  AND importe IS NOT NULL"
        )
        with connect_read() as c:
            row = c.execute(sql, [*cerrados, hoy_iso]).fetchone()
        if row is None or row[0] is None:
            return 0.0, 0.0, 0
        return float(row[0]), float(row[1] or 0.0), int(row[2] or 0)

    # Máximo de ofertas recibidas por expediente en la ventana pedida. Va como
    # sub-select y no como join directo contra ``adjudicaciones`` porque una
    # licitación multi-lote tiene una adjudicación por lote: sin colapsarlas
    # antes, sus ofertas pesarían una vez por lote en la media del segmento.
    _COMPETENCIA_SUB = (
        "SELECT a.licitacion_id, MAX(a.n_ofertas_recibidas) AS max_ofertas "
        "FROM adjudicaciones a "
        "WHERE a.n_ofertas_recibidas IS NOT NULL "
        "  AND a.fecha_adjudicacion >= %s "
        "GROUP BY a.licitacion_id"
    )

    def competencia_ofertas_por_cpv4(
        self, *, cutoff_iso: str
    ) -> tuple[list[dict[str, Any]], float | None]:
        """(filas ``cpv4``/``media_ofertas``, media global) del universo del radar.

        Señal de competencia del scoring: cuántas ofertas suele recibir un
        expediente del segmento. La media global es el fallback para los CPV-4
        sin muestra propia, y por eso **no** aplica el ``HAVING`` ni el filtro de
        ``cpv``: cuenta todo lo que el universo tenga en la ventana.

        El predicado del universo se interpola desde
        :data:`db.sql_fragments.TECHNOLOGY_OBSERVED_SQL` y no se escribe a mano,
        porque ``v84_lic_universo_cpv_index`` crea un índice **parcial** con ese
        mismo texto: el planificador solo lo usa si puede demostrar que este
        WHERE implica el predicado del índice, y no normaliza variantes del
        ``COALESCE``. Una copia divergente aquí no rompería el resultado —
        volvería en silencio al Parallel Seq Scan de 9,5 s que motivó el índice.
        Las dos columnas que la consulta pide de ``licitaciones``
        (``id_externo`` para el join, ``cpv`` para el segmento) son exactamente
        las del índice, para que el nodo pueda resolverse sin bajar al heap.

        Vivía en ``services/analytics/scoring_signals.py``; baja aquí por
        ADR-022 (todo el SQL en ``db/``) al tocarla para el índice.

        ``cutoff_iso`` llega calculado por el llamante (ventana de 24 meses de
        calendario), como el resto de ventanas relativas de este módulo: el
        resultado no depende del reloj de quien lo corre.
        """
        por_cpv4 = (
            "SELECT substr(l.cpv, 1, 4) AS cpv4, AVG(sub.max_ofertas) AS media_ofertas "
            f"FROM ({self._COMPETENCIA_SUB}) sub "
            "JOIN licitaciones l ON l.id_externo = sub.licitacion_id "
            f"WHERE {TECHNOLOGY_OBSERVED_SQL} "
            "  AND l.cpv IS NOT NULL "
            "  AND length(l.cpv) >= 4 "
            "GROUP BY cpv4 "
            "HAVING COUNT(*) >= 3"
        )
        # Misma forma que la de arriba —agregar ``adjudicaciones`` primero y
        # unir después— y no el join sobre las filas crudas: el join entra con
        # una fila por expediente en vez de una por lote. Da el mismo número
        # (``id_externo`` es la PK, así que la unión es 1:1) leyendo menos.
        global_sql = (
            "SELECT AVG(sub.max_ofertas) AS media_global "
            f"FROM ({self._COMPETENCIA_SUB}) sub "
            "JOIN licitaciones l ON l.id_externo = sub.licitacion_id "
            f"WHERE {TECHNOLOGY_OBSERVED_SQL}"
        )
        with connect_read() as c:
            rows = rows_to_dicts(c.execute(por_cpv4, [cutoff_iso]))
            row_global = c.execute(global_sql, [cutoff_iso]).fetchone()
        media_global = (
            float(row_global[0]) if row_global is not None and row_global[0] is not None else None
        )
        return rows, media_global

    def scoring_candidates(
        self,
        *,
        hoy_iso: str,
        filters: LicitacionesFilters | None = None,
        cerrados: tuple[str, ...] = ESTADOS_CERRADOS,
    ) -> list[dict[str, Any]]:
        """Proyección acotada de candidatas a oportunidad: abiertas y en plazo.

        ADR-023: el scoring puntuaba la tabla entera vía pandas; una
        licitación cerrada/adjudicada nunca es una "oportunidad", así que el
        universo puntuable excluye los estados terminales.

        Se enumeran los estados **cerrados**, no los abiertos, que es la regla
        de ``shared.estados``: con la allowlist anterior (``PUB``/``EV``) todo
        expediente en un estado abierto que no fuera esos dos —``ADM``, el más
        común— quedaba fuera del Radar sin dejar rastro. Se vio al mandar el
        Radar a puntuar de verdad: con los 15 expedientes del seed (12 ``ADM``,
        3 ``ADJ``) el ranking salía vacío.

        **El estado no acota nada por sí solo.** Medido en producción el
        2026-08-11: de 1.640.915 filas, 1.501.273 no están en estado terminal
        —el 91%—, porque 1.460.719 llegan de PSCP con ``PUBLICACIÓ AGREGADA``,
        que no es RES/ADJ/ANUL. Cargar eso en pandas son 1,5 M filas por 12
        columnas en cada request: la API se quedaba sin memoria y Render reiniciaba
        la instancia (diez reinicios el 2026-08-11, uno por cada carga del
        Radar), o el ``statement_timeout`` mataba la consulta y el usuario veía
        "Error al cargar la bandeja del radar".

        Por eso el universo exige además **plazo vivo**: sin fecha límite en el
        futuro no hay nada que presentar, y el Radar es una bandeja de
        decisión. Eso deja 1.643 filas, tres órdenes de magnitud menos. Lo que
        cae son las 1.466.309 abiertas sin ``fecha_limite`` (99,5% de ellas
        ``PUBLICACIÓ AGREGADA``, avisos agregados sin plazo propio que nunca
        fueron oportunidades individuales) y las 33.321 con el plazo ya
        vencido.

        Consecuencia deliberada: este universo ya **no** coincide con
        ``total_activas`` del resumen, que sigue contando por estado. Son dos
        preguntas distintas —"cuántas siguen vivas en el sistema" frente a "a
        cuántas puedo presentarme hoy"— y el ranking necesita la segunda.

        ``hoy_iso`` se inyecta (no ``now()`` en SQL) como en
        ``overview_para_hoy``: el corte queda fijado por el llamante y los
        tests no dependen del reloj.

        El predicado de estado + plazo está replicado en
        ``importe_percentiles_universo``, que calcula la distribución de
        referencia de la dimensión ``importe``: si cambia aquí, cambia allí.
        """
        where, params = _build_where(filters or LicitacionesFilters())
        placeholders = ",".join("%s" for _ in cerrados)
        guard = _iso_guard("fecha_limite")
        sql = (
            f"SELECT {self._SCORING_COLS} FROM licitaciones "
            f"WHERE {where} "
            f"  AND (estado IS NULL OR estado NOT IN ({placeholders})) "
            f"  AND {guard} AND fecha_limite >= %s"
        )
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, [*params, *cerrados, hoy_iso]))

    def licitaciones_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        """Proyección de scoring para una lista exacta de ids (modo page-aligned)."""
        if not ids:
            return []
        placeholders = ",".join("%s" for _ in ids)
        sql = f"SELECT {self._SCORING_COLS} FROM licitaciones WHERE id_externo IN ({placeholders})"
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, ids))

    def tech_signal_by_ids(
        self, ids: list[str], *, tecnologia: str | None = None
    ) -> dict[str, float]:
        """Fuerza de la señal técnica [0,1] por licitación, para las ids dadas.

        Combina las dos evidencias que el sistema ya produce y hasta ahora solo
        servían para filtrar o etiquetar:

        - ``licitacion_tecnologia_pliego``: derivada del **texto real de los
          pliegos**, con términos citables. Es la más fuerte de las dos y
          sobrevive al clobber de ``db/upsert.py``.
        - ``licitacion_tecnologia_score``: probabilidad del clasificador ML.

        Se toma el máximo: una tecnología confirmada por cualquiera de las dos
        vías está confirmada. Con ``tecnologia``, la fuerza es la de ESA
        tecnología (es el ranking de "las mejores oportunidades SAP", no "las
        mejores oportunidades que además son SAP"); sin filtro, la máxima sobre
        cualquiera.

        Se consulta **por ids** y no se cachea entera a propósito:
        ``licitacion_tecnologia_score`` tiene una fila por (licitación, label)
        sobre toda la tabla, así que puede llegar a millones — el patrón de
        carga completa que usan las otras señales aquí reventaría la memoria
        del proceso. El universo puntuable son ~1,6 k ids y ambas consultas
        atacan sus claves primarias.

        No usa ``licitaciones.ml_proba_max``: `db/upsert.py` la sobreescribe en
        cada re-scrape (esa es justamente la razón de existir de la tabla de
        pliego).
        """
        if not ids:
            return {}
        filtro_tech = " AND tecnologia = %s" if tecnologia else ""
        params: list[Any] = [ids, NO_SIGNAL_SENTINEL]
        if tecnologia:
            params.append(tecnologia)
        params.append(ids)
        if tecnologia:
            params.append(tecnologia)
        sql = (
            "SELECT licitacion_id, MAX(fuerza) AS fuerza FROM ("
            "  SELECT licitacion_id, MAX(score) AS fuerza"
            "    FROM licitacion_tecnologia_pliego"
            "   WHERE licitacion_id = ANY(%s) AND tecnologia <> %s"
            f"{filtro_tech}"
            "   GROUP BY licitacion_id"
            "  UNION ALL"
            "  SELECT licitacion_id, MAX(probabilidad) AS fuerza"
            "    FROM licitacion_tecnologia_score"
            "   WHERE licitacion_id = ANY(%s)"
            f"{filtro_tech}"
            "   GROUP BY licitacion_id"
            ") sub GROUP BY licitacion_id"
        )
        with connect_read() as c:
            rows = rows_to_dicts(c.execute(sql, params))
        return {
            str(r["licitacion_id"]): float(r["fuerza"])
            for r in rows
            if r["licitacion_id"] is not None and r["fuerza"] is not None
        }

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
            f"WHERE {where} AND {guard} AND fecha_limite > %s AND fecha_limite < %s "
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
        placeholders = ",".join("%s" for _ in tech_codes)
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
