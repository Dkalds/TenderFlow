"""Tecnologías: ranking, cruces por órgano y CCAA, evolución y detalle."""

from __future__ import annotations

from typing import Any, TypedDict

from db.database import connect_read
from db.repositories.aggregates.filtros import (
    LicitacionesFilters,
    _AgregadosBase,
    _build_where,
    _lectura,
)
from db.repositories.base import rows_to_dicts, typed_rows
from db.sql_fragments import (
    iso_guard,
    tecnologia_en_csv_sql,
    tecnologia_tokens_sql,
)


class TecnologiaEntradaFila(TypedDict):
    code: str
    count: int
    importe: float
    adjudicadas: int


class TecnologiaOrganoFila(TypedDict):
    organo: str
    code: str
    count: int


class TecnologiaCcaaFila(TypedDict):
    ccaa: str
    code: str
    count: int


class TecnologiaMesFila(TypedDict):
    mes: str
    tech_grp: str
    count: int
    importe: float


class TecnologiaItemFila(TypedDict):
    id_externo: str
    titulo: str
    organo_contratacion: str | None
    importe: float | None
    estado: str | None
    ccaa: str | None
    fecha_publicacion: str | None


class TecnologiasMixin(_AgregadosBase):
    """Tecnologías: ranking, cruces por órgano y CCAA, evolución y detalle."""

    def tecnologias_mas_frecuentes(self, n: int, *, conn: Any | None = None) -> list[str]:
        """Los ``n`` códigos de tecnología con más expedientes en toda la tabla.

        Lo usa el precálculo del overview para elegir de qué tecnologías deja
        variantes en ``kpi_snapshots`` (``db/repositories/kpi_snapshots.py``):
        precalcular todas costaría dos agregaciones por código en cada pasada,
        y las que la gente filtra son las que más pesan en el corpus.

        Explota el CSV con :func:`db.sql_fragments.tecnologia_tokens_sql`, la
        misma normalización que usa el filtro, para que el código que sale de
        aquí sea exactamente el que el filtro compara. Empate por nombre: el
        conjunto elegido no puede cambiar entre dos pasadas sin que cambien
        los datos. Un CSV con el mismo código repetido lo contaría dos veces;
        para elegir un top da igual, y la ingesta no lo produce.
        """
        if n <= 0:
            return []
        sql = (
            "SELECT t.codigo, COUNT(*) AS n "
            f"FROM licitaciones, unnest({tecnologia_tokens_sql('tecnologia')}) AS t(codigo) "
            f"WHERE {self._CON_TECNOLOGIA} AND t.codigo <> '' "
            "GROUP BY t.codigo ORDER BY n DESC, t.codigo LIMIT %s"
        )
        with _lectura(conn) as c:
            rows = c.execute(sql, [n]).fetchall()
        return [str(r[0]) for r in rows]

    def tecnologias_total_y_sin_clasificar(self, filters: LicitacionesFilters) -> tuple[int, int]:
        """(total del ámbito, filas sin tecnología).

        Dos subconsultas en una sola sentencia —una sola foto de la tabla— y no
        un ``COUNT(*) FILTER`` sobre el mismo recorrido: el ``FILTER`` necesita
        leer ``tecnologia`` de cada fila, y eso obligaba a un Seq Scan de la tabla
        entera (~15 s en producción). Separadas, el total puede ir por un Index
        Only Scan del índice más pequeño que sirva al ``WHERE`` y las
        clasificadas por el índice parcial de tecnología: 1,6 s medido en
        producción sin filtros (2026-09-25).

        Las filas sin clasificar son el complemento exacto: toda fila cumple
        ``tecnologia IS NULL OR trim(tecnologia) = ''`` o su negación, que es lo
        que cuenta la segunda subconsulta.
        """
        where, params = _build_where(filters)
        sql = (
            f"SELECT (SELECT COUNT(*) FROM licitaciones WHERE {where}) AS total, "
            f"       (SELECT COUNT(*) FROM licitaciones WHERE {where} "
            f"          AND {self._CON_TECNOLOGIA} AND trim(tecnologia) != '') AS clasificadas"
        )
        with connect_read() as c:
            row = c.execute(sql, [*params, *params]).fetchone()
        if row is None:
            return 0, 0
        total = int(row[0] or 0)
        return total, total - int(row[1] or 0)

    def tecnologias_entries(self, filters: LicitacionesFilters) -> list[TecnologiaEntradaFila]:
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
            f"WHERE {where} AND {self._CON_TECNOLOGIA} AND trim(code) != '' "
            "GROUP BY trim(code)"
        )
        with connect_read() as c:
            return typed_rows(TecnologiaEntradaFila, rows_to_dicts(c.execute(sql, params)))

    def tecnologias_cross_organo(
        self, filters: LicitacionesFilters, *, top_organos: int, top_techs: int
    ) -> list[TecnologiaOrganoFila]:
        where, params = _build_where(filters)
        sql = (
            "WITH exploded AS ("
            "  SELECT organo_contratacion AS organo, trim(code) AS code "
            "  FROM licitaciones, unnest(string_to_array(COALESCE(tecnologia, ''), ',')) AS code "
            f"  WHERE {where} AND {self._CON_TECNOLOGIA} AND trim(code) != '' "
            "    AND organo_contratacion IS NOT NULL"
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
            return typed_rows(
                TecnologiaOrganoFila,
                rows_to_dicts(c.execute(sql, [*params, top_organos, top_techs])),
            )

    def tecnologias_cross_geo(
        self, filters: LicitacionesFilters, *, top_ccaa: int, top_techs: int
    ) -> list[TecnologiaCcaaFila]:
        where, params = _build_where(filters)
        sql = (
            "WITH exploded AS ("
            "  SELECT ccaa, trim(code) AS code "
            "  FROM licitaciones, unnest(string_to_array(COALESCE(tecnologia, ''), ',')) AS code "
            f"  WHERE {where} AND {self._CON_TECNOLOGIA} AND trim(code) != '' AND ccaa IS NOT NULL"
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
            return typed_rows(
                TecnologiaCcaaFila, rows_to_dicts(c.execute(sql, [*params, top_ccaa, top_techs]))
            )

    def tecnologias_evolucion(
        self, filters: LicitacionesFilters, *, top_techs: int
    ) -> list[TecnologiaMesFila]:
        where, params = _build_where(filters)
        guard = iso_guard("fecha_publicacion")
        sql = (
            "WITH exploded AS ("
            "  SELECT substr(fecha_publicacion, 1, 7) AS mes, trim(code) AS code, importe "
            "  FROM licitaciones, unnest(string_to_array(COALESCE(tecnologia, ''), ',')) AS code "
            f"  WHERE {where} AND {self._CON_TECNOLOGIA} AND trim(code) != '' AND {guard}"
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
            return typed_rows(
                TecnologiaMesFila, rows_to_dicts(c.execute(sql, [*params, top_techs]))
            )

    def tecnologia_detalle_items(
        self, filters: LicitacionesFilters, *, tech_codes: list[str], limit: int
    ) -> list[TecnologiaItemFila]:
        """Top-N licitaciones (por importe) para los códigos crudos de UN label.

        ``tech_codes`` es la lista de códigos de ``tecnologia`` que mapean al
        label solicitado (resuelta en ``services/analytics/tecnologias.py`` vía
        ``TECHNOLOGY_LABELS`` — lógica de dominio, no SQL).
        """
        if not tech_codes:
            return []
        where, params = _build_where(filters)
        # C3.2: el top-N se recorta en SQL, no en Python.
        #
        # Hasta 2026-09 este método materializaba **todas** las licitaciones del
        # label —el corpus tecnológico entero para un label ancho—, las ordenaba
        # en memoria y devolvía las `limit` primeras. Pagaba en RSS de la API lo
        # que la BD sabe hacer con un `LIMIT`.
        #
        # Solapamiento de arrays en vez de explotar el CSV: cada licitación sale
        # una vez aunque lleve varios de los códigos pedidos, sin `DISTINCT ON`.
        # `id_externo` desempata: sin él, dos filas con el mismo importe saldrían
        # en orden indefinido y la lista cambiaría entre peticiones idénticas.
        sql = (
            "SELECT l.id_externo, l.titulo, l.organo_contratacion, l.importe, "
            "       l.estado, l.ccaa, l.fecha_publicacion "
            "FROM licitaciones l "
            f"WHERE {where} AND {tecnologia_en_csv_sql('l.tecnologia', n=len(tech_codes))} "
            "ORDER BY l.importe DESC NULLS LAST, l.id_externo "
            "LIMIT %s"
        )
        with connect_read() as c:
            return typed_rows(
                TecnologiaItemFila, rows_to_dicts(c.execute(sql, [*params, *tech_codes, limit]))
            )

    def tecnologia_detalle_kpis(
        self, filters: LicitacionesFilters, *, tech_codes: list[str]
    ) -> tuple[int, float, float]:
        """(n, importe_total, importe_medio) — una vez por licitación: el
        solapamiento de arrays no explota el CSV, así que una fila con varios de
        los códigos pedidos no se cuenta dos veces. ``importe_medio`` usa
        ``AVG`` (ignora NULLs, igual que ``Series.mean(skipna=True)``) — puede
        diferir de ``importe_total / n`` si hay filas con ``importe`` nulo
        entre las ``n``.
        """
        if not tech_codes:
            return 0, 0.0, 0.0
        where, params = _build_where(filters)
        sql = (
            "SELECT COUNT(*) AS n, COALESCE(SUM(l.importe), 0) AS importe_total, "
            "       AVG(l.importe) AS importe_medio "
            "FROM licitaciones l "
            f"WHERE {where} AND {tecnologia_en_csv_sql('l.tecnologia', n=len(tech_codes))}"
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
