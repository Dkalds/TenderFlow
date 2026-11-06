"""Exportaciones de ``licitaciones``: el PDF filtrado y el stream de recientes."""

from __future__ import annotations

from db.database import connect_read
from db.repositories.base import cota_hasta, csv_values, rows_to_dicts, typed_rows
from db.repositories.licitaciones.filas import ExportPdfRow, RecienteRow
from db.repositories.licitaciones.filtros import _normaliza_codigo
from db.sql_fragments import (
    codigo_normalizado_sql,
    escape_like,
    exclude_duplicados_presentacion_sql,
    tecnologia_en_csv_sql,
)


class ExportMixin:
    """Lecturas para exportar: PDF y novedades recientes."""

    def fetch_recent(
        self,
        *,
        since_extraccion: str,
        since_actualizacion: str,
        limit: int,
    ) -> list[RecienteRow]:
        """Carga licitaciones recientes para SSE streaming.

        Es el feed en vivo del dashboard, otra cara del listado: esconde las
        republicaciones ``pending`` y ``confirmed`` con la misma regla de
        presentación (ADR-026 D23) para no anunciar como nueva una fila que la
        lista no va a enseñar.
        """
        with connect_read() as c:
            cur = c.execute(
                "SELECT id_externo, titulo, organo_contratacion, importe, estado, "
                "url, fecha_publicacion, ccaa, tecnologia, fecha_extraccion, "
                "fecha_actualizacion_fuente "
                "FROM licitaciones "
                "WHERE (fecha_extraccion >= %s OR fecha_actualizacion_fuente >= %s) "
                f"AND {exclude_duplicados_presentacion_sql('id_externo')} "
                "ORDER BY COALESCE(fecha_actualizacion_fuente, fecha_extraccion) DESC "
                "LIMIT %s",
                (since_extraccion, since_actualizacion, limit),
            )
            return typed_rows(RecienteRow, rows_to_dicts(cur))

    def fetch_for_pdf(
        self,
        *,
        ccaa: str | None = None,
        estado: str | None = None,
        q: str | None = None,
        tecnologia: str | None = None,
        fecha_desde: str | None = None,
        fecha_hasta: str | None = None,
        importe_min: float | None = None,
        importe_max: float | None = None,
        provincia: str | None = None,
        procedimiento: str | None = None,
        limit: int = 500,
    ) -> list[ExportPdfRow]:
        """Carga licitaciones para exportación PDF.

        ``tecnologia``/``fecha_desde``/``fecha_hasta`` se filtran aquí y no en
        el llamador: la ruta de descarga los aplicaba en Python **después** de
        traer hasta 50 000 filas, así que el LIMIT se consumía con filas que
        luego se descartaban (una exportación filtrada podía salir corta).

        ``importe_min``/``importe_max``/``provincia``/``procedimiento`` (F1.1)
        con la semántica de ``_base_filters``: cotas inclusivas que dejan fuera
        el importe NULL, provincia multi-valor y procedimiento por código
        normalizado. Sin ellos el export bajaba el corpus entero mientras el
        listado de la misma pantalla estaba acotado.

        Nace con la exclusión de presentación de duplicados (ADR-026 D23), la
        misma de ``_base_filters``: el export baja lo que el listado enseña, no
        las republicaciones ``pending`` y ``confirmed`` que la lista esconde.
        """
        conditions: list[str] = [exclude_duplicados_presentacion_sql("id_externo")]
        params: list[object] = []
        if ccaa:
            conditions.append("ccaa = %s")
            params.append(ccaa)
        if estado:
            conditions.append("estado = %s")
            params.append(estado)
        if tecnologias := csv_values(tecnologia):
            # Contención en el CSV, no igualdad: `tecnologia` guarda
            # "SAP,SALESFORCE", así que `= 'SAP'` escondía justo los
            # expedientes multi-tecnología. Es el mismo arreglo que ya llevan
            # el listado, el cursor y la rama FTS; estas dos superficies se
            # quedaron atrás.
            conditions.append(tecnologia_en_csv_sql("tecnologia", n=len(tecnologias)))
            params.extend(tecnologias)
        if fecha_desde:
            conditions.append("fecha_publicacion >= %s")
            params.append(fecha_desde)
        if fecha_hasta:
            clausula, valor = cota_hasta("fecha_publicacion", fecha_hasta)
            conditions.append(clausula)
            params.append(valor)
        if importe_min is not None:
            conditions.append("importe >= %s")
            params.append(float(importe_min))
        if importe_max is not None:
            conditions.append("importe <= %s")
            params.append(float(importe_max))
        if provincias := csv_values(provincia):
            conditions.append(f"provincia IN ({','.join('%s' for _ in provincias)})")
            params.extend(provincias)
        if codigos := sorted({_normaliza_codigo(c) for c in csv_values(procedimiento)}):
            conditions.append(
                f"{codigo_normalizado_sql('procedimiento')} IN ({','.join('%s' for _ in codigos)})"
            )
            params.extend(codigos)
        if q:
            like_op = "ILIKE"
            conditions.append(
                f"(titulo {like_op} %s ESCAPE '\\' OR descripcion {like_op} %s ESCAPE '\\')"
            )
            eq = escape_like(q)
            params.extend([f"%{eq}%", f"%{eq}%"])
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with connect_read() as c:
            cur = c.execute(
                "SELECT id_externo, titulo, organo_contratacion, importe, estado, "
                "fecha_publicacion, ccaa, cpv, url, tecnologia "
                "FROM licitaciones" + where + " ORDER BY fecha_publicacion DESC LIMIT %s",
                [*params, limit],
            )
            return typed_rows(ExportPdfRow, rows_to_dicts(cur))
