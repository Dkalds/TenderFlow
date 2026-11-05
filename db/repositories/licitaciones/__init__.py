"""Repository para licitaciones.

Las queries complejas usan SQLAlchemy Core para construcción type-safe
(ver :mod:`db.models`). Las queries simples por PK usan SQL directo.

El paquete se parte por familia de métodos —cada una un mixin del que hereda
:class:`LicitacionRepository`—: ``filtros`` (traducción de
``FiltrosLicitacion`` y helpers de columna y orden), ``listado`` (offset,
cursor y FTS), ``busqueda``, ``ml`` y ``export``; las formas de fila viven en
``filas``. Aquí se quedan las lecturas por expediente y la bandeja «Próximas».
La ruta de import pública sigue siendo ``db.repositories.licitaciones``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, and_, func, select

from db.database import connect_read
from db.models import compile_query, licitaciones
from db.repositories.base import loose_distinct_strings, rows_to_dicts, typed_rows
from db.repositories.licitaciones.busqueda import BusquedaMixin
from db.repositories.licitaciones.export import ExportMixin
from db.repositories.licitaciones.filas import (
    CandidatoEtiquetadoRow,
    DriftRow,
    ExportPdfRow,
    HistorialRow,
    LicitacionLoteRow,
    LicitacionResumenRow,
    ProximaRow,
    RecienteRow,
    TechScoreRow,
    ZonaIncertidumbreRow,
)
from db.repositories.licitaciones.filtros import (
    _PROXIMAS_COLS,
    _SUMMARY_COLS,
    OBJETO_ETIQUETA_EXPEDIENTE,
    SORTS_CURSOR,
    _any_of,
)
from db.repositories.licitaciones.listado import ListadoMixin
from db.repositories.licitaciones.ml import PREFIJO_REPORTE, MlMixin, etiqueta_humana
from db.repositories.publico import FilaLotePublico
from db.sql_fragments import fechas_ts_lectura_activa, instante_sql
from shared.estados import abierta_core

__all__ = [
    "OBJETO_ETIQUETA_EXPEDIENTE",
    "PREFIJO_REPORTE",
    "SORTS_CURSOR",
    "CandidatoEtiquetadoRow",
    "DriftRow",
    "ExportPdfRow",
    "HistorialRow",
    "LicitacionLoteRow",
    "LicitacionRepository",
    "LicitacionResumenRow",
    "ProximaRow",
    "RecienteRow",
    "TechScoreRow",
    "ZonaIncertidumbreRow",
    "etiqueta_humana",
    "licitaciones_por_lote",
    "lotes_de",
]


class LicitacionRepository(ListadoMixin, BusquedaMixin, MlMixin, ExportMixin):
    """Acceso de lectura a la tabla ``licitaciones``."""

    def get_by_id(self, id_externo: str) -> dict[str, Any] | None:
        """Devuelve el registro completo o None."""
        with connect_read() as c:
            cur = c.execute(
                "SELECT * FROM licitaciones WHERE id_externo = %s", (id_externo,)
            )  # SELECT *: ficha completa: get_by_id devuelve toda la fila (db/repositories/publico.py la recorta)
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row, strict=False))

    def exists(self, id_externo: str) -> bool:
        """``True`` si el expediente existe. Para los guardas de 404.

        No es ``get_by_id(...) is not None``: quien pregunta esto solo quiere
        saber si responder 404, y traerse la fila entera (``SELECT *``) para
        tirarla es trabajo que nadie mira. Vive aquí y no en la ruta porque
        todo el SQL vive en ``db/`` (ADR-022).
        """
        with connect_read() as c:
            row = c.execute(
                "SELECT 1 FROM licitaciones WHERE id_externo = %s",
                (id_externo,),
            ).fetchone()
        return row is not None

    def proximas(
        self,
        *,
        estados: Sequence[str],
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ProximaRow], int, int]:
        """Compras anunciadas que aún no han salido a licitación.

        Devuelve ``(items, total, con_fecha_prevista)``. Los tres números son
        del **universo entero** que cumple el filtro, no de la página: el
        llamante tiene que poder decir «X de Y traen fecha prevista» sin
        derivarlo de las filas que le llegaron (ADR-014 — sin denominador no se
        pinta una proporción).

        ``estados`` lo elige el llamante (la ruta pasa
        ``services.classification.ESTADOS_PRE_LICITACION``, es decir ``PRE`` y
        ``CPM``) y no se enumera aquí: este estrato posee el SQL, no el juicio
        de qué es una compra anunciada.

        «Abierta» significa lo mismo que en el resto del Radar —el predicado de
        :func:`shared.estados.abierta_core`, que excluye los terminales— y se
        aplica aunque hoy sea redundante: ni ``PRE`` ni ``CPM`` están en
        ``ESTADOS_CERRADOS``. Escribirlo es lo que hace que el día que uno de
        esos dos códigos pase a contar como cerrado, la bandeja lo respete sin
        que nadie tenga que acordarse de esta consulta.

        La **fecha prevista es ``licitaciones.fecha_inicio``** y sale de
        ``ProcurementProject/PlannedPeriod/cbc:StartDate``
        (``scraper/codice_parser.py:526,667``). Es el inicio de ejecución
        previsto del contrato, no una fecha de licitación: es lo único que la
        fuente publica para un expediente sin pliego, y no se deriva ni se
        estima nada a partir de ella. Cuando falta, la fila viaja con ``None``.

        El orden es por fecha prevista ascendente **con las nulas al final**:
        lo que tiene fecha se lee como un calendario, y lo que no la tiene queda
        detrás ordenado por publicación reciente en vez de encabezar la lista
        con un hueco. No se inventa una fecha para las nulas ni se las esconde:
        son el caso mayoritario y la bandeja tiene que saber pintarlas.
        """
        if not estados:
            return [], 0, 0

        clauses = [
            _any_of(licitaciones.c.estado, list(estados)),
            abierta_core(licitaciones.c.estado),
        ]
        base: Select[Any] = select(*_PROXIMAS_COLS).select_from(licitaciones).where(and_(*clauses))

        # Un solo viaje para las dos cifras: contarlas por separado permitiría
        # que discreparan si entra una fila entre las dos consultas, y la
        # proporción «X de Y» dejaría de sumar. `count(col)` no cuenta NULL,
        # que es exactamente la definición de «trae fecha prevista».
        conteos_stmt = (
            select(
                func.count(),
                func.count(licitaciones.c.fecha_inicio),
            )
            .select_from(licitaciones)
            .where(and_(*clauses))
        )
        data_stmt = (
            base.order_by(
                # `nullslast` explícito y no el defecto del motor: en Postgres
                # los NULL van últimos en ASC por defecto, pero ese defecto no
                # es el mismo en DESC, y aquí el orden es parte del contrato de
                # la bandeja y no una casualidad del dialecto.
                licitaciones.c.fecha_inicio.asc().nullslast(),
                licitaciones.c.fecha_publicacion.desc(),
                # Desempate estable: sin él dos filas con la misma fecha pueden
                # cambiar de sitio entre páginas y una de ellas no salir nunca.
                licitaciones.c.id_externo.asc(),
            )
            .limit(limit)
            .offset(offset)
        )

        conteos_sql, conteos_params = compile_query(conteos_stmt)
        data_sql, data_params = compile_query(data_stmt)

        with connect_read() as c:
            fila = c.execute(conteos_sql, conteos_params).fetchone()
            total = int(fila[0]) if fila else 0
            con_fecha = int(fila[1]) if fila else 0
            items = typed_rows(ProximaRow, rows_to_dicts(c.execute(data_sql, data_params)))

        return items, total, con_fecha

    def get_filter_options(self, *, cpv_values: list[str] | None = None) -> dict[str, list[str]]:
        """Devuelve listas de valores únicos para filtros (CCAA, estado, tecnologia, CPV).

        Usa el *loose index scan* de :func:`db.repositories.base.
        loose_distinct_strings` en vez de ``SELECT DISTINCT``, que recorría el
        índice entero: 39 s de media con picos de 116 s para devolver 19 CCAA,
        medido en producción el 2026-08-10. Con el salto por el btree, 41,8 ms.

        ``cpv`` es la excepción que el cambio de algoritmo no arregló: 18.203
        valores distintos son 18.203 descensiones, unos 9,5 s. Por eso
        ``cpv_values`` permite inyectar la lista que el precálculo de KPIs deja
        en ``kpi_snapshots`` (los CPV nuevos solo aparecen al ingerir, así que
        el desfase es como mucho el de la última pasada del scraper). Sin
        inyección se calcula en vivo, que es lo que sigue haciendo la suite y
        cualquier despliegue sin snapshot todavía.
        """
        with connect_read() as c:
            return {
                "estado": loose_distinct_strings(c, "licitaciones", "estado"),
                "ccaa": loose_distinct_strings(c, "licitaciones", "ccaa"),
                "tecnologia": loose_distinct_strings(c, "licitaciones", "tecnologia"),
                "cpv": (
                    cpv_values
                    if cpv_values is not None
                    else loose_distinct_strings(c, "licitaciones", "cpv")
                ),
            }

    def get_last_extraction_date(self) -> str | None:
        """MAX(fecha_extraccion) para Last-Modified header.

        Con ``FECHAS_TS_LECTURA`` lee primero ``MAX(fecha_extraccion_ts)``
        (índice de ``v160``) y lo devuelve en ISO UTC; si la sombra está vacía
        —backfill sin empezar— cae a la columna de texto. El máximo del texto
        es un máximo lexicográfico: con ``' '`` y ``'T'`` mezclados en
        producción, puede no ser el instante más reciente; el de la sombra sí.
        """
        with connect_read() as c:
            if fechas_ts_lectura_activa():
                fila = c.execute("SELECT MAX(fecha_extraccion_ts) FROM licitaciones").fetchone()
                if fila and isinstance(fila[0], datetime):
                    return str(fila[0].astimezone(UTC).isoformat())
            row = c.execute("SELECT MAX(fecha_extraccion) FROM licitaciones").fetchone()
        return str(row[0]) if row and row[0] else None

    def get_by_ids(self, ids: list[str]) -> list[LicitacionResumenRow]:
        """Obtiene múltiples licitaciones por id_externo en una sola query.

        Preserva el orden de entrada. IDs no encontrados se omiten.
        Máximo 100 IDs por llamada (responsabilidad del llamante).
        """
        if not ids:
            return []
        placeholders = ",".join(["%s"] * len(ids))
        col_names = ", ".join(col.key for col in _SUMMARY_COLS)
        with connect_read() as conn:
            cur = conn.execute(
                f"SELECT {col_names} FROM licitaciones WHERE id_externo IN ({placeholders})",
                ids,
            )
            rows = typed_rows(LicitacionResumenRow, rows_to_dicts(cur))
        order = {id_: i for i, id_ in enumerate(ids)}
        return sorted(rows, key=lambda r: order.get(r["id_externo"], 999))

    def get_history(self, id_externo: str, limit: int = 50) -> list[HistorialRow]:
        """Devuelve el historial de cambios de una licitación."""
        limit = max(1, min(limit, 1000))
        with connect_read() as c:
            cur = c.execute(
                "SELECT id, id_externo, captured_at, source, snapshot_json, changed_fields "
                "FROM licitaciones_history "
                "WHERE id_externo = %s "
                f"ORDER BY {instante_sql('licitaciones_history', 'captured_at')} DESC LIMIT %s",
                [id_externo, limit],
            )
            return typed_rows(HistorialRow, rows_to_dicts(cur))


def lotes_de(id_externo: str) -> list[FilaLotePublico]:
    """Lotes de un expediente, ordenados por número (C1.4).

    `db/repositories/publico.py` ya tenía esta consulta para la superficie
    anónima, pero la ficha autenticada no la usaba: `GET /licitaciones/{id}`
    devolvía el expediente sin sus lotes, y el frontend no tenía de dónde
    sacarlos. Un expediente multi-lote se presentaba como uno solo con el
    presupuesto total, que es la misma confusión que `EFFECTIVE_BUDGET_SQL`
    resolvió del lado del cálculo.

    Orden numérico cuando el número lo permite: `ORDER BY numero` como texto
    pone el lote 10 antes del 2. El `CASE` cae al orden textual para los
    números que no son enteros ("1.A", "Lote 3"), que existen en PLACSP.
    """
    sql = (
        "SELECT numero, titulo, cpv, importe, fecha_limite FROM lotes "
        "WHERE licitacion_id = %s "
        "ORDER BY CASE WHEN numero ~ '^[0-9]+$' THEN CAST(numero AS INTEGER) END, numero"
    )
    with connect_read() as c:
        return typed_rows(FilaLotePublico, rows_to_dicts(c.execute(sql, (id_externo,))))


def licitaciones_por_lote(ids: list[str]) -> list[LicitacionLoteRow]:
    """Una fila por lote para los expedientes dados (C1.4, export).

    Los expedientes **sin** lotes salen igual, con los campos de lote a `NULL`:
    un export que solo trajera los multi-lote perdería la mayoría del corpus
    sin decirlo. El `LEFT JOIN` es esa decisión.
    """
    if not ids:
        return []
    marcadores = ",".join("%s" for _ in ids)
    sql = (
        "SELECT l.id_externo, l.titulo, l.organo_contratacion, l.importe, "
        "       l.cpv, l.estado, l.ccaa, l.fecha_publicacion, l.fecha_limite, l.url, "
        "       lo.numero AS lote_numero, lo.titulo AS lote_titulo, lo.cpv AS lote_cpv, "
        "       lo.importe AS lote_importe, lo.fecha_limite AS lote_fecha_limite "
        "FROM licitaciones l "
        "LEFT JOIN lotes lo ON lo.licitacion_id = l.id_externo "
        f"WHERE l.id_externo IN ({marcadores}) "
        "ORDER BY l.id_externo, "
        "  CASE WHEN lo.numero ~ '^[0-9]+$' THEN CAST(lo.numero AS INTEGER) END, lo.numero"
    )
    with connect_read() as c:
        return typed_rows(LicitacionLoteRow, rows_to_dicts(c.execute(sql, ids)))
