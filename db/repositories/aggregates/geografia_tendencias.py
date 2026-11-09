"""Geografía, tendencias (incluidas las de CPV) y calendario de vencimientos."""

from __future__ import annotations

from typing import TypedDict

from db.database import connect_read
from db.repositories.aggregates.filtros import (
    LicitacionesFilters,
    _build_where,
)
from db.repositories.base import rows_to_dicts, typed_rows
from db.sql_fragments import (
    iso_guard,
    universo_producto_sql,
)


class CcaaImporteFila(TypedDict):
    ccaa: str
    count: int
    importe: float
    importe_medio: float | None


class ProvinciaImporteFila(TypedDict):
    provincia: str
    count: int
    importe: float


class DiaImporteFila(TypedDict):
    #: ``YYYY-MM-DD``.
    dia: str
    count: int
    importe: float


class MesEstadoFila(TypedDict):
    mes: str
    estado: str
    value: int


class CpvImporteTotalFila(TypedDict):
    cpv: str
    importe_total: float
    count: int


class CpvMesFila(TypedDict):
    cpv: str
    mes: str
    count: int
    importe: float


class GeografiaTendenciasMixin:
    """Geografía, tendencias (incluidas las de CPV) y calendario de vencimientos."""

    # ── Geography ────────────────────────────────────────────────────────

    def geography_by_ccaa(self, filters: LicitacionesFilters) -> list[CcaaImporteFila]:
        """(ccaa, count, importe, importe_medio) ordenado por count DESC; ccaa NULL excluida.

        ``importe_medio`` es ``AVG(importe)``: solo cuenta las filas con importe.
        Dividir ``importe`` entre ``count`` bajaba la media de la comunidad que
        más expedientes publica sin importe.
        """
        where, params = _build_where(filters)
        sql = (
            "SELECT ccaa, COUNT(*) AS count, COALESCE(SUM(importe), 0) AS importe, "
            "AVG(importe) AS importe_medio "
            "FROM licitaciones "
            "WHERE " + where + " AND ccaa IS NOT NULL "
            "GROUP BY ccaa ORDER BY count DESC, ccaa"
        )
        with connect_read() as c:
            return typed_rows(CcaaImporteFila, rows_to_dicts(c.execute(sql, params)))

    def geography_by_provincia(self, filters: LicitacionesFilters) -> list[ProvinciaImporteFila]:
        """(provincia, count, importe) sobre TODO el dataset filtrado."""
        where, params = _build_where(filters)
        sql = (
            "SELECT provincia, COUNT(*) AS count, COALESCE(SUM(importe), 0) AS importe "
            "FROM licitaciones "
            "WHERE " + where + " AND provincia IS NOT NULL AND trim(provincia) != '' "
            "GROUP BY provincia ORDER BY count DESC, provincia"
        )
        with connect_read() as c:
            return typed_rows(ProvinciaImporteFila, rows_to_dicts(c.execute(sql, params)))

    # ── Trends ───────────────────────────────────────────────────────────

    def trends_daily(self, filters: LicitacionesFilters) -> list[DiaImporteFila]:
        """(dia YYYY-MM-DD, count, importe) — base para series month/week/day.

        El roll-up a semana/mes se hace en Python sobre este resultado ya
        agregado (cientos de filas, post-agregación permitida por ADR-023):
        evita duplicar en SQL el formato de etiqueta semanal de pandas
        (``%Y-W%V`` sobre el lunes de la semana).
        """
        where, params = _build_where(filters)
        guard = iso_guard("fecha_publicacion")
        sql = (
            "SELECT substr(fecha_publicacion, 1, 10) AS dia, "
            "       COUNT(*) AS count, COALESCE(SUM(importe), 0) AS importe "
            "FROM licitaciones "
            f"WHERE {where} AND {guard} "
            "GROUP BY dia ORDER BY dia"
        )
        with connect_read() as c:
            return typed_rows(DiaImporteFila, rows_to_dicts(c.execute(sql, params)))

    def trends_heatmap(self, filters: LicitacionesFilters) -> list[MesEstadoFila]:
        """(mes YYYY-MM, estado, value) para el heatmap mes x estado."""
        where, params = _build_where(filters)
        guard = iso_guard("fecha_publicacion")
        sql = (
            "SELECT substr(fecha_publicacion, 1, 7) AS mes, estado, COUNT(*) AS value "
            "FROM licitaciones "
            f"WHERE {where} AND {guard} AND estado IS NOT NULL "
            "GROUP BY mes, estado ORDER BY mes, estado"
        )
        with connect_read() as c:
            return typed_rows(MesEstadoFila, rows_to_dicts(c.execute(sql, params)))

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
        guard = iso_guard(col)
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

    # ── Calendario de vencimientos ───────────────────────────────────────
    #
    # Eje ``fecha_limite`` (fin del plazo de presentación), no publicación. El
    # universo es el MISMO que el del listado al que enlaza cada día
    # (``GET /licitaciones?cierre_desde=D&cierre_hasta=D``): el filtro global
    # de ``_build_where`` más el universo del listado
    # (:func:`db.sql_fragments.universo_producto_sql`), el ``solo_universo``
    # que ``LicitacionRepository._base_filters`` aplica siempre. Sin esa
    # cláusula el calendario contaría filas que el listado no enseña y el día
    # prometería más de lo que abre (ADR-014).
    #
    # La cota superior es EXCLUSIVA (el día siguiente al ``hasta``) porque
    # ``fecha_limite`` puede llevar hora: ``'2026-09-20T14:00' <= '2026-09-20'``
    # es falso en orden lexicográfico. Es la misma convención que usa
    # ``_base_filters`` para ``cierre_hasta``.

    _VENCIMIENTOS_UNIVERSO = universo_producto_sql("licitaciones")

    def vencimientos_diarios(
        self, filters: LicitacionesFilters, *, desde_iso: str, hasta_exclusivo_iso: str
    ) -> list[DiaImporteFila]:
        """(dia YYYY-MM-DD, count, importe) de cierres en ``[desde, hasta)``.

        El tamaño está acotado por la ventana (un día por fila), que el servicio
        limita; no escala con el número de licitaciones.
        """
        where, params = _build_where(filters, presentacion=True)
        guard = iso_guard("fecha_limite")
        sql = (
            "SELECT substr(fecha_limite, 1, 10) AS dia, "
            "       COUNT(*) AS count, COALESCE(SUM(importe), 0) AS importe "
            "FROM licitaciones "
            f"WHERE {where} AND {guard} AND {self._VENCIMIENTOS_UNIVERSO} "
            "  AND fecha_limite >= %s AND fecha_limite < %s "
            "GROUP BY dia ORDER BY dia"
        )
        with connect_read() as c:
            return typed_rows(
                DiaImporteFila,
                rows_to_dicts(c.execute(sql, [*params, desde_iso, hasta_exclusivo_iso])),
            )

    def vencimientos_kpis(
        self,
        filters: LicitacionesFilters,
        *,
        hoy_iso: str,
        manana_iso: str,
        fin_7d_exclusivo_iso: str,
        fin_mes_exclusivo_iso: str,
    ) -> dict[str, int]:
        """Cierres de hoy, de los próximos 7 días y de lo que queda de mes.

        Relativos a ``hoy`` y no a la ventana que pinta el calendario: el KPI
        responde «¿qué me vence ya?» aunque el usuario esté mirando otro año.
        Todas las cotas superiores son exclusivas (ver la nota de la sección).
        """
        where, params = _build_where(filters, presentacion=True)
        guard = iso_guard("fecha_limite")
        sql = (
            "SELECT "
            "  COUNT(*) FILTER (WHERE fecha_limite < %s) AS hoy, "
            "  COUNT(*) FILTER (WHERE fecha_limite < %s) AS proximos_7d, "
            "  COUNT(*) FILTER (WHERE fecha_limite < %s) AS resto_mes "
            "FROM licitaciones "
            f"WHERE {where} AND {guard} AND {self._VENCIMIENTOS_UNIVERSO} "
            "  AND fecha_limite >= %s AND fecha_limite < %s"
        )
        # El techo del WHERE es el mayor de las dos ventanas: el fin de mes
        # puede caer antes que hoy+7 (último día del mes) o después.
        techo = max(fin_7d_exclusivo_iso, fin_mes_exclusivo_iso)
        run_params = [
            manana_iso,
            fin_7d_exclusivo_iso,
            fin_mes_exclusivo_iso,
            *params,
            hoy_iso,
            techo,
        ]
        with connect_read() as c:
            row = c.execute(sql, run_params).fetchone()
        if row is None:
            return {"hoy": 0, "proximos_7d": 0, "resto_mes": 0}
        return {
            "hoy": int(row[0] or 0),
            "proximos_7d": int(row[1] or 0),
            "resto_mes": int(row[2] or 0),
        }

    # ── Trends CPV ───────────────────────────────────────────────────────

    def trends_cpv_ranking(
        self, filters: LicitacionesFilters, *, top_n: int
    ) -> tuple[int, list[CpvImporteTotalFila], str | None, str | None]:
        """(total_cpvs, top-N por importe, periodo_inicio, periodo_fin)."""
        where, params = _build_where(filters)
        guard = iso_guard("fecha_publicacion")
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
        return total, typed_rows(CpvImporteTotalFila, top), inicio, fin

    def trends_cpv_series(
        self, filters: LicitacionesFilters, *, cpvs: list[str]
    ) -> list[CpvMesFila]:
        """(cpv, mes, count, importe) para los CPVs del top."""
        if not cpvs:
            return []
        where, params = _build_where(filters)
        guard = iso_guard("fecha_publicacion")
        placeholders = ",".join("%s" for _ in cpvs)
        sql = (
            "SELECT cpv, substr(fecha_publicacion, 1, 7) AS mes, "
            "       COUNT(*) AS count, COALESCE(SUM(importe), 0) AS importe "
            "FROM licitaciones "
            f"WHERE {where} AND {guard} AND cpv IN ({placeholders}) "
            "GROUP BY cpv, mes ORDER BY cpv, mes"
        )
        with connect_read() as c:
            return typed_rows(CpvMesFila, rows_to_dicts(c.execute(sql, [*params, *cpvs])))
