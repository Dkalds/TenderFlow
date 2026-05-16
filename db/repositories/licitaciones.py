"""Repository para licitaciones."""

from __future__ import annotations

import re
from typing import Any

from db.database import connect_read, fts_available
from db.repositories.base import count_where, rows_to_dicts

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_SUMMARY_COLS = (
    "id_externo, titulo, organo_contratacion, importe, estado, "
    "fecha_publicacion, ccaa, cpv, url, tecnologia"
)

_SORT_WHITELIST: dict[str, str] = {
    "fecha_publicacion": "fecha_publicacion DESC",
    "-fecha_publicacion": "fecha_publicacion ASC",
    "importe": "importe ASC",
    "-importe": "importe DESC",
    "titulo": "titulo ASC",
    "-titulo": "titulo DESC",
}

_DEFAULT_SORT = "fecha_publicacion DESC"


class LicitacionRepository:
    """Acceso de lectura a la tabla ``licitaciones``."""

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _build_filters(
        *,
        q: str | None = None,
        estado: str | None = None,
        ccaa: str | None = None,
        tecnologia: str | None = None,
        fecha_desde: str | None = None,
        fecha_hasta: str | None = None,
        only_classified: bool = True,
    ) -> tuple[str, list[Any]]:
        conditions: list[str] = []
        params: list[Any] = []

        if only_classified:
            conditions.append("tecnologia IS NOT NULL AND tecnologia != ''")

        if q:
            conditions.append("(titulo LIKE ? OR descripcion LIKE ?)")
            like = f"%{q}%"
            params.extend([like, like])
        if estado:
            conditions.append("estado = ?")
            params.append(estado)
        if ccaa:
            conditions.append("ccaa = ?")
            params.append(ccaa)
        if tecnologia:
            conditions.append("tecnologia = ?")
            params.append(tecnologia)
        if fecha_desde and _DATE_RE.match(fecha_desde):
            conditions.append("fecha_publicacion >= ?")
            params.append(fecha_desde)
        if fecha_hasta and _DATE_RE.match(fecha_hasta):
            conditions.append("fecha_publicacion <= ?")
            params.append(fecha_hasta)

        return " AND ".join(conditions), params

    # ── public API ────────────────────────────────────────────────────────────

    def list_paginated(
        self,
        *,
        q: str | None = None,
        estado: str | None = None,
        ccaa: str | None = None,
        tecnologia: str | None = None,
        fecha_desde: str | None = None,
        fecha_hasta: str | None = None,
        limit: int = 50,
        offset: int = 0,
        sort: str | None = None,
        with_total: bool = True,
    ) -> tuple[list[dict[str, Any]], int]:
        """Devuelve (items, total).  Si ``with_total=False`` total==-1."""
        order = _SORT_WHITELIST.get(sort or "", _DEFAULT_SORT)
        where, params = self._build_filters(
            q=q,
            estado=estado,
            ccaa=ccaa,
            tecnologia=tecnologia,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
        )

        # Usar FTS5 para búsquedas de texto si disponible
        if q and fts_available():
            return self._list_fts(
                q=q,
                estado=estado,
                ccaa=ccaa,
                tecnologia=tecnologia,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
                limit=limit,
                offset=offset,
                order=order,
                with_total=with_total,
            )

        with connect_read() as c:
            total = count_where(c, "licitaciones", where, tuple(params)) if with_total else -1
            sql = f"SELECT {_SUMMARY_COLS} FROM licitaciones"
            if where:
                sql += f" WHERE {where}"
            sql += f" ORDER BY {order} LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            items = rows_to_dicts(c.execute(sql, tuple(params)))

        return items, total

    def _list_fts(
        self,
        *,
        q: str,
        estado: str | None,
        ccaa: str | None,
        tecnologia: str | None,
        fecha_desde: str | None,
        fecha_hasta: str | None,
        limit: int,
        offset: int,
        order: str,
        with_total: bool,
    ) -> tuple[list[dict[str, Any]], int]:
        extra_conditions: list[str] = ["tecnologia IS NOT NULL AND tecnologia != ''"]
        extra_params: list[Any] = []
        if estado:
            extra_conditions.append("l.estado = ?")
            extra_params.append(estado)
        if ccaa:
            extra_conditions.append("l.ccaa = ?")
            extra_params.append(ccaa)
        if tecnologia:
            extra_conditions.append("l.tecnologia = ?")
            extra_params.append(tecnologia)
        if fecha_desde and _DATE_RE.match(fecha_desde):
            extra_conditions.append("l.fecha_publicacion >= ?")
            extra_params.append(fecha_desde)
        if fecha_hasta and _DATE_RE.match(fecha_hasta):
            extra_conditions.append("l.fecha_publicacion <= ?")
            extra_params.append(fecha_hasta)

        extra_where = " AND ".join(extra_conditions)
        base_sql = (
            f"SELECT {', '.join('l.' + c.strip() for c in _SUMMARY_COLS.split(','))} "
            "FROM licitaciones l "
            "JOIN licitaciones_fts f ON l.rowid = f.rowid "
            f"WHERE licitaciones_fts MATCH ? AND {extra_where}"
        )
        count_sql = (
            "SELECT COUNT(*) FROM licitaciones l "
            "JOIN licitaciones_fts f ON l.rowid = f.rowid "
            f"WHERE licitaciones_fts MATCH ? AND {extra_where}"
        )

        with connect_read() as c:
            total = -1
            if with_total:
                count_row = c.execute(count_sql, [q, *extra_params]).fetchone()
                total = int(count_row[0]) if count_row else 0
            items = rows_to_dicts(
                c.execute(
                    base_sql + f" ORDER BY {order} LIMIT ? OFFSET ?",
                    [q, *extra_params, limit, offset],
                )
            )
        return items, total

    def list_cursor(
        self,
        *,
        cursor_fecha: str | None = None,
        cursor_id: str | None = None,
        tecnologia: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Paginación por cursor (fecha_publicacion, id_externo) DESC."""
        conditions: list[str] = ["tecnologia IS NOT NULL AND tecnologia != ''"]
        params: list[Any] = []

        if tecnologia:
            conditions.append("tecnologia = ?")
            params.append(tecnologia)

        if cursor_fecha is not None and cursor_id is not None:
            conditions.append(
                "(fecha_publicacion < ? OR (fecha_publicacion = ? AND id_externo < ?))"
            )
            params.extend([cursor_fecha, cursor_fecha, cursor_id])

        where = " AND ".join(conditions)
        sql = (
            f"SELECT {_SUMMARY_COLS} FROM licitaciones WHERE {where} "
            "ORDER BY fecha_publicacion DESC, id_externo DESC LIMIT ?"
        )
        params.append(limit + 1)

        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, tuple(params)))

    def get_by_id(self, id_externo: str) -> dict[str, Any] | None:
        """Devuelve el registro completo o None."""
        with connect_read() as c:
            cur = c.execute(
                "SELECT * FROM licitaciones WHERE id_externo = ?", (id_externo,)
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row, strict=False))

    def get_text_for_ml(self, id_externo: str) -> tuple[str, str, str | None] | None:
        """Devuelve (titulo, descripcion, tecnologia) o None."""
        with connect_read() as c:
            row = c.execute(
                "SELECT titulo, descripcion, tecnologia FROM licitaciones WHERE id_externo = ?",
                (id_externo,),
            ).fetchone()
        return (str(row[0] or ""), str(row[1] or ""), row[2]) if row else None

    def get_unlabelled_candidates(self, limit: int = 500) -> list[dict[str, Any]]:
        """Licitaciones no presentes en ml_feedback para active learning."""
        with connect_read() as c:
            cur = c.execute(
                "SELECT id_externo, titulo, descripcion "
                "FROM licitaciones "
                "WHERE id_externo NOT IN (SELECT expediente FROM ml_feedback) "
                "ORDER BY fecha_publicacion DESC LIMIT ?",
                (limit,),
            )
            return rows_to_dicts(cur)

    def get_unlabelled_random(self, limit: int = 20) -> list[dict[str, Any]]:
        with connect_read() as c:
            cur = c.execute(
                "SELECT id_externo, titulo "
                "FROM licitaciones "
                "WHERE id_externo NOT IN (SELECT expediente FROM ml_feedback) "
                "ORDER BY RANDOM() LIMIT ?",
                (limit,),
            )
            return rows_to_dicts(cur)

    def get_filter_options(self) -> dict[str, list[str]]:
        """Devuelve listas de valores únicos para filtros (CCAA, estado, tecnologia, CPV)."""
        with connect_read() as c:
            def _distinct(col: str) -> list[str]:
                rows = c.execute(
                    f"SELECT DISTINCT {col} FROM licitaciones "
                    f"WHERE {col} IS NOT NULL AND {col} != '' "
                    f"ORDER BY {col}"
                ).fetchall()
                return [r[0] for r in rows]

            return {
                "estado": _distinct("estado"),
                "ccaa": _distinct("ccaa"),
                "tecnologia": _distinct("tecnologia"),
                "cpv": _distinct("cpv"),
            }

    def get_last_extraction_date(self) -> str | None:
        """MAX(fecha_extraccion) para Last-Modified header."""
        with connect_read() as c:
            row = c.execute(
                "SELECT MAX(fecha_extraccion) FROM licitaciones"
            ).fetchone()
        return str(row[0]) if row and row[0] else None

    def get_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        """Obtiene múltiples licitaciones por id_externo en una sola query.

        Preserva el orden de entrada. IDs no encontrados se omiten.
        Máximo 100 IDs por llamada (responsabilidad del llamante).
        """
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        with connect_read() as c:
            cur = c.execute(
                f"SELECT {_SUMMARY_COLS} FROM licitaciones "
                f"WHERE id_externo IN ({placeholders})",
                ids,
            )
            rows = rows_to_dicts(cur)
        # Preservar orden del input
        order = {id_: i for i, id_ in enumerate(ids)}
        return sorted(rows, key=lambda r: order.get(r.get("id_externo", ""), 999))
