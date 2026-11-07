"""Búsquedas sobre ``licitaciones``: avanzada, FTS y la de ``/ask``."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, and_, func, or_, select

from db.database import connect_read, fts_available
from db.models import compile_query, licitaciones
from db.repositories.base import ambito_busqueda_sql, rows_to_dicts, typed_rows
from db.repositories.licitaciones.filas import LicitacionResumenRow
from db.repositories.licitaciones.filtros import (
    _COLUMNAS_BUSQUEDA,
    _DATE_RE,
    _DEFAULT_ORDER,
    _SORT_MAP,
    _SUMMARY_COLS,
    _plegado,
    _tecnologia_en_csv,
)
from db.sql_fragments import FOLD_TABLE, escape_like
from observability.logging import get_logger

# El nombre de antes de partir el módulo: `logger` sale en cada línea de log.
log = get_logger("db.repositories.licitaciones")


class BusquedaMixin:
    """Búsquedas de texto y avanzada."""

    def search_advanced(
        self,
        *,
        q: str | None = None,
        estado: list[str] | None = None,
        ccaa: list[str] | None = None,
        tecnologia: list[str] | None = None,
        importe_min: float | None = None,
        importe_max: float | None = None,
        fecha_desde: str | None = None,
        fecha_hasta: str | None = None,
        sort: str | None = None,
        limit: int = 50,
        offset: int = 0,
        with_total: bool = True,
    ) -> tuple[list[LicitacionResumenRow], int]:
        """Búsqueda avanzada con criterios complejos (multi-valor, rangos de importe).

        Extiende ``list_paginated`` con soporte para listas de estado/ccaa
        (``IN``) y rangos de importe. ``tecnologia`` casa contra el CSV de
        códigos de cada fila, igual que en el resto del producto (ver
        :func:`_tecnologia_en_csv`). Usada por POST /licitaciones/search.
        """
        order = _SORT_MAP.get(sort or "", _DEFAULT_ORDER)
        clauses: list[Any] = [
            and_(
                licitaciones.c.tecnologia.isnot(None),
                licitaciones.c.tecnologia != "",
            )
        ]

        if q and q.strip():
            like = f"%{escape_like(q.strip().translate(FOLD_TABLE).lower())}%"
            clauses.append(or_(*[_plegado(c).like(like) for c in _COLUMNAS_BUSQUEDA]))
        if estado:
            clauses.append(licitaciones.c.estado.in_(estado))
        if ccaa:
            clauses.append(licitaciones.c.ccaa.in_(ccaa))
        if tecnologia:
            clauses.append(_tecnologia_en_csv(list(tecnologia)))
        if importe_min is not None:
            clauses.append(licitaciones.c.importe >= importe_min)
        if importe_max is not None:
            clauses.append(licitaciones.c.importe <= importe_max)
        if fecha_desde and _DATE_RE.match(fecha_desde):
            clauses.append(licitaciones.c.fecha_publicacion >= fecha_desde)
        if fecha_hasta and _DATE_RE.match(fecha_hasta):
            clauses.append(licitaciones.c.fecha_publicacion <= fecha_hasta)

        base: Select[Any] = select(*_SUMMARY_COLS).select_from(licitaciones)
        if clauses:
            base = base.where(and_(*clauses))

        count_stmt = select(func.count()).select_from(base.subquery())
        data_stmt = base.order_by(order).limit(limit).offset(offset)

        count_sql, count_params = compile_query(count_stmt)
        data_sql, data_params = compile_query(data_stmt)

        with connect_read() as c:
            total = -1
            if with_total:
                row = c.execute(count_sql, count_params).fetchone()
                total = int(row[0]) if row else 0
            items = typed_rows(
                LicitacionResumenRow, rows_to_dicts(c.execute(data_sql, data_params))
            )

        return items, total

    def search_fts_ids(self, query: str, limit: int = 1000) -> list[str] | None:
        """Busca con FTS5/search_vector y devuelve id_externo ordenados por rank.

        Returns ``None`` si FTS no está disponible o la query falla.
        """
        if not fts_available() or not query.strip():
            return None
        try:
            with connect_read() as c:
                cur = c.execute(
                    "SELECT id_externo FROM licitaciones "
                    "WHERE search_vector @@ websearch_to_tsquery('spanish', %s) "
                    "ORDER BY ts_rank_cd(search_vector, websearch_to_tsquery('spanish', %s)) DESC "
                    "LIMIT %s",
                    [query, query, limit],
                )
                return [row[0] for row in cur.fetchall()]
        except Exception:
            log.warning("fts_ids_search_failed", exc_info=True)
            return None

    def search_fts_docs(
        self,
        query: str,
        *,
        ccaa: str | Sequence[str] | None = None,
        tecnologia: str | Sequence[str] | None = None,
        fecha_desde: str | None = None,
        fecha_hasta: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Búsqueda por ``search_vector`` con metadatos completos (para RAG endpoint).

        Los filtros son los de :func:`ambito_busqueda_sql`, los mismos que
        aplica la fusión híbrida.
        """
        ambito, valores = ambito_busqueda_sql(
            "l", ccaa=ccaa, tecnologia=tecnologia, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta
        )
        where = " AND ".join(["l.search_vector @@ websearch_to_tsquery('spanish', %s)", *ambito])
        cols = (
            "l.id_externo, l.titulo, l.organo_contratacion, l.importe, "
            "l.descripcion, l.url, l.fecha_publicacion, l.ccaa, l.estado, l.tecnologia"
        )
        with connect_read() as c:
            cur = c.execute(
                f"SELECT {cols} FROM licitaciones l "
                f"WHERE {where} "
                "ORDER BY ts_rank_cd(l.search_vector, websearch_to_tsquery('spanish', %s)) DESC "
                "LIMIT %s",
                [query, *valores, query, limit],
            )
            return rows_to_dicts(cur)
