"""Calidad del dato, forecast, retendering y universo de clustering."""

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
)


class CompletitudGlobal(TypedDict):
    """Lo que devuelve :meth:`AggregateRepository.quality_completitud`."""

    total: int
    #: Filas con valor no vacío, por columna de texto.
    cols: dict[str, int]
    importe: int
    fecha_iso: int


class CompletitudMesFila(TypedDict):
    mes: str
    total: int
    con_cpv: int
    con_importe: int
    con_organo: int
    con_fecha_limite: int


class SerieMensualFila(TypedDict):
    mes: str
    #: ``COUNT(*)`` (``int``) o ``SUM(importe)`` (``float``) según ``metric``.
    valor: float


class PublicacionesMesFila(TypedDict):
    mes: str
    publicaciones: int


class RetenderingFila(TypedDict):
    id_externo: str
    titulo: str
    organo_contratacion: str | None
    importe: float | None
    fecha_publicacion: str | None
    duracion_valor: float | None
    duracion_unidad: str | None
    fecha_inicio: str | None
    fecha_fin: str | None


class AdjudicacionForecastFila(TypedDict):
    licitacion_id: str
    fecha_adjudicacion: str | None
    importe_adjudicado: float | None
    n_ofertas_recibidas: int | None
    nombre: str


class ClusteringFila(TypedDict):
    id_externo: str
    titulo: str
    organo_contratacion: str | None
    importe: float | None
    ccaa: str | None
    estado: str | None
    cpv: str | None


class CalidadForecastMixin:
    """Calidad del dato, forecast, retendering y universo de clustering."""

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

    def quality_completitud(self) -> CompletitudGlobal:
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

    def quality_completitud_mensual(self, *, desde_iso: str) -> list[CompletitudMesFila]:
        """Completitud por mes de PUBLICACIÓN desde ``desde_iso`` (RFC calidad #3).

        Una serie de completitud sin tabla de histórico: cada mes es la cohorte
        de expedientes publicados en él, medida hoy. No es «cómo estaba el dato
        el mes pasado» (eso exigiría persistir snapshots), sino «qué tan
        completos llegan los expedientes de cada mes» — que es justo lo que se
        rompe cuando la fuente cambia de esquema: los meses posteriores al
        cambio caen y los anteriores no.

        Acotada por la ventana (un grupo por mes, ~12 filas) y por el índice de
        ``fecha_publicacion``.
        """
        guard = iso_guard("fecha_publicacion")
        sql = (
            "SELECT substr(fecha_publicacion, 1, 7) AS mes, COUNT(*) AS total, "
            "  COUNT(*) FILTER (WHERE cpv IS NOT NULL AND trim(cpv) != '') AS con_cpv, "
            "  COUNT(*) FILTER (WHERE importe IS NOT NULL) AS con_importe, "
            "  COUNT(*) FILTER (WHERE organo_contratacion IS NOT NULL "
            "                   AND trim(organo_contratacion) != '') AS con_organo, "
            "  COUNT(*) FILTER (WHERE fecha_limite IS NOT NULL "
            "                   AND trim(fecha_limite) != '') AS con_fecha_limite "
            "FROM licitaciones "
            f"WHERE {guard} AND fecha_publicacion >= %s "
            "GROUP BY mes ORDER BY mes"
        )
        with connect_read() as c:
            return typed_rows(CompletitudMesFila, rows_to_dicts(c.execute(sql, [desde_iso])))

    # ── Forecast ─────────────────────────────────────────────────────────

    def forecast_monthly(
        self, filters: LicitacionesFilters, *, metric: str
    ) -> list[SerieMensualFila]:
        """Serie mensual (mes YYYY-MM, valor) para el forecast de volumen."""
        where, params = _build_where(filters)
        guard = iso_guard("fecha_publicacion")
        agg = "COALESCE(SUM(importe), 0)" if metric == "sum" else "COUNT(*)"
        sql = (
            f"SELECT substr(fecha_publicacion, 1, 7) AS mes, {agg} AS valor "
            "FROM licitaciones "
            f"WHERE {where} AND {guard} "
            "GROUP BY mes ORDER BY mes"
        )
        with connect_read() as c:
            return typed_rows(SerieMensualFila, rows_to_dicts(c.execute(sql, params)))

    def publicaciones_mensuales(
        self, filters: LicitacionesFilters, *, mes_desde: str, mes_hasta: str
    ) -> list[PublicacionesMesFila]:
        """(mes ``YYYY-MM``, publicaciones) dentro de una ventana cerrada de meses.

        Hermana de :meth:`forecast_monthly`, con dos diferencias que justifican
        que no sea la misma consulta: la ventana va acotada en meses (no en
        fechas del filtro, que la estacionalidad necesita conservar libres) y
        el agregado es siempre un conteo — no hay variante ``sum``, porque una
        estacionalidad de importes la dominaría un único expediente grande.

        Los meses vacíos **no** se rellenan: sólo vuelven los que tienen filas.
        Decidir si un mes ausente es un cero real o un mes fuera de cobertura es
        del servicio, que es quien sabe qué tramo pidió.

        ``mes_desde``/``mes_hasta`` llegan como ``YYYY-MM`` y se traducen a un
        rango **sargable** sobre la columna (``>= 'YYYY-MM-01'`` y ``<`` el día
        uno del mes siguiente), no a un ``substr(...) >= ...``: ese predicado no
        puede usar el btree de la fecha y obliga a evaluar la función fila a
        fila, que es el mismo motivo por el que ``iso_guard`` es un rango y no
        una regex.
        """
        where, params = _build_where(filters)
        guard = iso_guard("fecha_publicacion")
        anio_fin, mes_fin = (int(p) for p in mes_hasta.split("-"))
        tras_el_fin = f"{anio_fin + mes_fin // 12:04d}-{mes_fin % 12 + 1:02d}-01"
        sql = (
            "SELECT substr(fecha_publicacion, 1, 7) AS mes, COUNT(*) AS publicaciones "
            "FROM licitaciones "
            f"WHERE {where} AND {guard} "
            "  AND fecha_publicacion >= %s AND fecha_publicacion < %s "
            "GROUP BY mes ORDER BY mes"
        )
        with connect_read() as c:
            return typed_rows(
                PublicacionesMesFila,
                rows_to_dicts(c.execute(sql, [*params, f"{mes_desde}-01", tras_el_fin])),
            )

    def retendering_universe(self, filters: LicitacionesFilters) -> list[RetenderingFila]:
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
            return typed_rows(RetenderingFila, rows_to_dicts(c.execute(sql, params)))

    def adjudicaciones_para_forecast(self, ids: list[str]) -> list[AdjudicacionForecastFila]:
        """Adjudicaciones (columnas del forecast) para una lista de licitaciones."""
        if not ids:
            return []
        sql = (
            "SELECT licitacion_id, fecha_adjudicacion, importe_adjudicado, "
            "       n_ofertas_recibidas, nombre "
            "FROM adjudicaciones WHERE licitacion_id = ANY(%s)"
        )
        with connect_read() as c:
            return typed_rows(AdjudicacionForecastFila, rows_to_dicts(c.execute(sql, [ids])))

    # ── Clustering online ────────────────────────────────────────────────

    def clustering_universe(
        self, filters: LicitacionesFilters, *, max_rows: int
    ) -> tuple[list[ClusteringFila], int]:
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
        return typed_rows(ClusteringFila, rows), total
