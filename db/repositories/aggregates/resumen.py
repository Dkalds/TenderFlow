"""Resumen: timeline, novedades, sankey y top licitaciones."""

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


class TimelineItemFila(TypedDict):
    id_externo: str
    titulo: str
    importe: float | None
    fecha_publicacion: str | None
    estado: str | None
    organo_contratacion: str | None
    tipo_contrato: str | None
    ccaa: str | None
    fuente: str


class NovedadFila(TypedDict):
    id_externo: str
    titulo: str
    importe: float | None
    organo_contratacion: str | None


class TipoEstadoValorFila(TypedDict):
    tipo_contrato: str
    estado: str
    value: int


class TopLicitacionFila(TypedDict):
    id_externo: str
    titulo: str
    organo_contratacion: str | None
    importe: float
    estado: str | None
    adjudicatario: str | None
    sum_adj: float | None
    n_adj: int


class ResumenMixin:
    """Resumen: timeline, novedades, sankey y top licitaciones."""

    # ── Resumen ──────────────────────────────────────────────────────────

    _RESUMEN_ITEM_COLS = (
        "id_externo, titulo, importe, fecha_publicacion, estado, "
        "organo_contratacion, tipo_contrato, ccaa, fuente"
    )

    def resumen_timeline_items(
        self, filters: LicitacionesFilters, *, limit: int, muestrear: bool = False
    ) -> tuple[list[TimelineItemFila], int]:
        """Filas del scatter de ``/resumen/timeline`` y total de la ventana.

        Dos modos, porque el mismo endpoint alimenta dos preguntas distintas:

        - ``muestrear=False`` (por defecto): las ``limit`` **más recientes**. Es
          lo que necesita la tabla «Últimas publicaciones», y el ``ORDER BY ...
          DESC LIMIT`` lo resuelve el btree de ``fecha_publicacion`` hacia atrás
          sin materializar la ventana entera.
        - ``muestrear=True``: una **muestra sistemática repartida por toda la
          ventana**. Lo pide la nube de puntos, para la que «las 1.000 más
          recientes» era una respuesta equivocada: en producción, las 1.000 más
          recientes de una ventana de 30 días son 48 horas, así que un gráfico
          rotulado «en el periodo» dibujaba dos días. Se ordena por fecha, se
          numera y se toma una de cada ``ceil(total/limit)``: el resultado
          conserva la forma de la nube y cubre el rango pedido.

        El segundo elemento del par es el total de la ventana **antes** de
        recortar, en los dos modos. Sin él, la UI no puede decir si lo que
        enseña es todo o una parte (regla del rediseño: nada de topes
        silenciosos).
        """
        where, params = _build_where(filters, presentacion=True)
        guard = iso_guard("fecha_publicacion")

        if not muestrear:
            total = self._resumen_timeline_total(where, params)
            sql = (
                f"SELECT {self._RESUMEN_ITEM_COLS} FROM licitaciones "
                f"WHERE {where} AND {guard} "
                "ORDER BY fecha_publicacion DESC LIMIT %s"
            )
            with connect_read() as c:
                filas = rows_to_dicts(c.execute(sql, [*params, limit]))
            return typed_rows(TimelineItemFila, filas), total

        # `(rn - 1) % stride = 0` y no `rn % stride = 1`: con stride 1 —la
        # ventana cabe entera— el segundo no selecciona nada, porque `rn % 1`
        # es siempre 0. Así el caso «no hace falta muestrear» sale gratis por
        # la misma consulta en vez de por una rama aparte.
        sql = (
            "WITH ventana AS ("
            f"  SELECT {self._RESUMEN_ITEM_COLS}, "
            "         row_number() OVER (ORDER BY fecha_publicacion DESC) AS rn, "
            "         count(*) OVER () AS total "
            "  FROM licitaciones "
            f"  WHERE {where} AND {guard}"
            ") "
            f"SELECT {self._RESUMEN_ITEM_COLS}, total FROM ventana "
            "WHERE (rn - 1) %% greatest(1, ceil(total::numeric / %s)::bigint) = 0 "
            "ORDER BY fecha_publicacion DESC"
        )
        with connect_read() as c:
            rows = rows_to_dicts(c.execute(sql, [*params, limit]))
        total = int(rows[0]["total"]) if rows else 0
        for row in rows:
            row.pop("total", None)
        return typed_rows(TimelineItemFila, rows), total

    def _resumen_timeline_total(self, where: str, params: list[object]) -> int:
        """Expedientes de la ventana, para poder declarar el recorte."""
        guard = iso_guard("fecha_publicacion")
        sql = f"SELECT count(*) FROM licitaciones WHERE {where} AND {guard}"
        with connect_read() as c:
            row = c.execute(sql, params).fetchone()
        return int(row[0] or 0) if row else 0

    def resumen_novedades(
        self,
        filters: LicitacionesFilters | None = None,
        *,
        desde_iso: str,
        sample_limit: int,
    ) -> tuple[int, list[NovedadFila]]:
        """(total, muestra) de licitaciones publicadas después de ``desde_iso``.

        La muestra va ordenada por ``fecha_publicacion`` descendente — el
        ``head(10)`` de pandas devolvía las primeras filas en el orden en que
        las servía la BD (arbitrario y no estable entre llamadas); las más
        recientes son además las que el banner quiere enseñar.

        ``filters`` acota al ámbito con el mismo ``WHERE`` que el resto de
        agregados del Resumen; sin él cuenta el mercado entero (la campana).
        """
        filtro, params = _build_where(filters or LicitacionesFilters(), presentacion=True)
        guard = iso_guard("fecha_publicacion")
        where = f"{filtro} AND {guard} AND fecha_publicacion > %s"
        with connect_read() as c:
            row = c.execute(
                f"SELECT COUNT(*) FROM licitaciones WHERE {where}", [*params, desde_iso]
            ).fetchone()
            count = int(row[0]) if row and row[0] is not None else 0
            if count == 0:
                return 0, []
            sample = rows_to_dicts(
                c.execute(
                    "SELECT id_externo, titulo, importe, organo_contratacion "
                    f"FROM licitaciones WHERE {where} "
                    "ORDER BY fecha_publicacion DESC LIMIT %s",
                    [*params, desde_iso, sample_limit],
                )
            )
        return count, typed_rows(NovedadFila, sample)

    # ── Resumen: sankey y top licitaciones ───────────────────────────────

    def resumen_sankey(self, filters: LicitacionesFilters) -> list[TipoEstadoValorFila]:
        """(tipo_contrato, estado, value) — flujo tipo→estado, NULLs excluidos."""
        where, params = _build_where(filters, presentacion=True)
        sql = (
            "SELECT tipo_contrato, estado, COUNT(*) AS value FROM licitaciones "
            "WHERE " + where + " AND tipo_contrato IS NOT NULL AND estado IS NOT NULL "
            "GROUP BY tipo_contrato, estado ORDER BY tipo_contrato, estado"
        )
        with connect_read() as c:
            return typed_rows(TipoEstadoValorFila, rows_to_dicts(c.execute(sql, params)))

    def resumen_top_licitaciones(
        self, filters: LicitacionesFilters, *, n: int
    ) -> list[TopLicitacionFila]:
        """Top-N por importe con adjudicatario y agregados de adjudicación.

        ``adjudicatario`` es el primer nombre no nulo del grupo (determinista
        por id de fila); ``sum_adj`` (total adjudicado del expediente) y ``n_adj``
        (nº de adjudicaciones/lotes) permiten al servicio calcular la baja
        agregada como ``1 - sum_adj / l.importe`` — todo lo adjudicado contra el
        presupuesto ÚNICO del expediente. NO multiplicar el presupuesto por
        ``n_adj``: eso replicaba el bug del pandas original, que sumaba
        ``importe_licitacion`` una vez por fila del join (n_adj * importe).
        """
        where, params = _build_where(filters, presentacion=True)
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
            return typed_rows(TopLicitacionFila, rows_to_dicts(c.execute(sql, [*params, n])))
