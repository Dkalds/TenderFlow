"""Repository para licitaciones.

Las queries complejas usan SQLAlchemy Core para construcción type-safe
(ver :mod:`db.models`). Las queries simples por PK usan SQL directo.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import Select, and_, func, or_, select, text

from db.database import connect_read, fts_available
from db.models import _DIALECT, compile_query, licitacion_tecnologia_score, licitaciones
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger
from shared.estados import ESTADOS_CERRADOS

log = get_logger(__name__)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _escape_like(s: str) -> str:
    """Escape SQL LIKE wildcards (%, _) in user input."""
    return s.replace("%", r"\%").replace("_", r"\_")


# Columnas devueltas en listados (resumen)
_SUMMARY_COLS = [
    licitaciones.c.id_externo,
    licitaciones.c.titulo,
    licitaciones.c.organo_contratacion,
    licitaciones.c.importe,
    licitaciones.c.estado,
    licitaciones.c.fecha_publicacion,
    licitaciones.c.fecha_limite,
    licitaciones.c.ccaa,
    licitaciones.c.cpv,
    licitaciones.c.url,
    licitaciones.c.tecnologia,
    licitaciones.c.ml_tecnologias,
    licitaciones.c.ml_proba_max,
    licitaciones.c.ml_tech_principal,
]

_SORT_MAP: dict[str, Any] = {
    "fecha_publicacion": licitaciones.c.fecha_publicacion.desc(),
    "-fecha_publicacion": licitaciones.c.fecha_publicacion.asc(),
    "importe": licitaciones.c.importe.asc(),
    "-importe": licitaciones.c.importe.desc(),
    "titulo": licitaciones.c.titulo.asc(),
    "-titulo": licitaciones.c.titulo.desc(),
}

_DEFAULT_ORDER = licitaciones.c.fecha_publicacion.desc()

# ---------------------------------------------------------------------------
# Backward-compat string aliases (used by services/licitaciones.py)
# ---------------------------------------------------------------------------

_SUMMARY_COLS_STR = (
    "id_externo, titulo, organo_contratacion, importe, estado, "
    "fecha_publicacion, fecha_limite, ccaa, cpv, url, tecnologia, "
    "ml_tecnologias, ml_proba_max, ml_tech_principal"
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
    def _base_filters(
        *,
        q: str | None = None,
        estado: str | None = None,
        solo_abiertas: bool = False,
        ccaa: str | None = None,
        tecnologia: str | None = None,
        tecnologia_predicha: str | None = None,
        min_proba_tech: float | None = None,
        fecha_desde: str | None = None,
        fecha_hasta: str | None = None,
        only_classified: bool = True,
    ) -> list[Any]:
        """Devuelve lista de cláusulas SA Core para WHERE."""
        clauses = []

        if only_classified:
            clauses.append(
                and_(
                    licitaciones.c.tecnologia.isnot(None),
                    licitaciones.c.tecnologia != "",
                )
            )

        if q:
            like = f"%{_escape_like(q)}%"
            clauses.append(
                or_(
                    licitaciones.c.titulo.like(like),
                    licitaciones.c.descripcion.like(like),
                )
            )
        if estado:
            clauses.append(licitaciones.c.estado == estado)
        if solo_abiertas:
            # `COALESCE` y no `NOT IN` a secas: en SQL `NULL NOT IN (...)` es
            # NULL, así que las filas sin estado —que son oportunidades hasta
            # que se demuestre lo contrario— quedarían fuera del resultado.
            clauses.append(func.coalesce(licitaciones.c.estado, "").notin_(ESTADOS_CERRADOS))
        if ccaa:
            clauses.append(licitaciones.c.ccaa == ccaa)
        if tecnologia:
            clauses.append(licitaciones.c.tecnologia == tecnologia)

        if tecnologia_predicha:
            if min_proba_tech is not None:
                # Subquery EXISTS en licitacion_tecnologia_score
                sub = (
                    select(text("1"))
                    .select_from(licitacion_tecnologia_score)
                    .where(
                        and_(
                            licitacion_tecnologia_score.c.licitacion_id
                            == licitaciones.c.id_externo,
                            licitacion_tecnologia_score.c.tecnologia == tecnologia_predicha,
                            licitacion_tecnologia_score.c.probabilidad >= float(min_proba_tech),
                        )
                    )
                )
                clauses.append(sub.exists())
            else:
                t = tecnologia_predicha
                clauses.append(
                    or_(
                        licitaciones.c.ml_tech_principal == t,
                        licitaciones.c.ml_tecnologias == t,
                        licitaciones.c.ml_tecnologias.like(f"{t},%"),
                        licitaciones.c.ml_tecnologias.like(f"%,{t},%"),
                        licitaciones.c.ml_tecnologias.like(f"%,{t}"),
                    )
                )

        if fecha_desde and _DATE_RE.match(fecha_desde):
            clauses.append(licitaciones.c.fecha_publicacion >= fecha_desde)
        if fecha_hasta and _DATE_RE.match(fecha_hasta):
            clauses.append(licitaciones.c.fecha_publicacion <= fecha_hasta)

        return clauses

    # ── public API ────────────────────────────────────────────────────────────

    def ids_for_filters(
        self,
        *,
        ccaa: list[str] | None = None,
        tecnologia: list[str] | None = None,
        fecha_desde: str | None = None,
        fecha_hasta: str | None = None,
        cap: int = 5000,
    ) -> set[str]:
        """Conjunto de ``id_externo`` que cumplen los filtros (multi-valor).

        Lo usa la búsqueda semántica para restringir los hits a los filtros
        activos (``allowed_ids``) sin fabricar el filtrado en el cliente. Devuelve
        un set acotado a ``cap``. Sin cláusulas devuelve ``set()`` — el caller solo
        debe invocarlo cuando hay al menos un filtro activo.
        """
        clauses: list[Any] = []
        if ccaa:
            clauses.append(licitaciones.c.ccaa.in_(ccaa))
        if tecnologia:
            clauses.append(licitaciones.c.tecnologia.in_(tecnologia))
        if fecha_desde and _DATE_RE.match(fecha_desde):
            clauses.append(licitaciones.c.fecha_publicacion >= fecha_desde)
        if fecha_hasta and _DATE_RE.match(fecha_hasta):
            clauses.append(licitaciones.c.fecha_publicacion <= fecha_hasta)
        if not clauses:
            return set()
        stmt = select(licitaciones.c.id_externo).where(and_(*clauses)).limit(cap)
        sql, params = compile_query(stmt)
        with connect_read() as c:
            return {row[0] for row in c.execute(sql, params).fetchall()}

    def list_paginated(
        self,
        *,
        q: str | None = None,
        estado: str | None = None,
        solo_abiertas: bool = False,
        ccaa: str | None = None,
        tecnologia: str | None = None,
        tecnologia_predicha: str | None = None,
        min_proba_tech: float | None = None,
        fecha_desde: str | None = None,
        fecha_hasta: str | None = None,
        limit: int = 50,
        offset: int = 0,
        sort: str | None = None,
        with_total: bool = True,
    ) -> tuple[list[dict[str, Any]], int]:
        """Devuelve (items, total).  Si ``with_total=False`` total==-1.

        ``solo_abiertas`` descarta los estados terminales de
        :data:`shared.estados.ESTADOS_CERRADOS` (resuelta, adjudicada,
        anulada). Es el filtro que necesita cualquier superficie de
        oportunidad — el Radar — para no proponer expedientes cerrados.
        """
        order = _SORT_MAP.get(sort or "", _DEFAULT_ORDER)
        clauses = self._base_filters(
            q=q,
            estado=estado,
            solo_abiertas=solo_abiertas,
            ccaa=ccaa,
            tecnologia=tecnologia,
            tecnologia_predicha=tecnologia_predicha,
            min_proba_tech=min_proba_tech,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
        )

        # Usar FTS5 para búsquedas de texto si disponible
        if q and fts_available():
            return self._list_fts(
                q=q,
                estado=estado,
                solo_abiertas=solo_abiertas,
                ccaa=ccaa,
                tecnologia=tecnologia,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
                limit=limit,
                offset=offset,
                order=order,
                with_total=with_total,
            )

        # Query SA Core
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
            items = rows_to_dicts(c.execute(data_sql, data_params))

        return items, total

    def _list_fts(
        self,
        *,
        q: str,
        estado: str | None,
        solo_abiertas: bool,
        ccaa: str | None,
        tecnologia: str | None,
        fecha_desde: str | None,
        fecha_hasta: str | None,
        limit: int,
        offset: int,
        order: Any,
        with_total: bool,
    ) -> tuple[list[dict[str, Any]], int]:
        """Búsqueda FTS5: usa SQL directo porque FTS MATCH no tiene soporte SA."""
        extra_conditions: list[str] = ["tecnologia IS NOT NULL AND tecnologia != ''"]
        extra_params: list[Any] = []
        if estado:
            extra_conditions.append("l.estado = %s")
            extra_params.append(estado)
        if solo_abiertas:
            # Mismo criterio que la rama SA Core: COALESCE para que un estado
            # NULL no se caiga del NOT IN.
            placeholders = ", ".join(["%s"] * len(ESTADOS_CERRADOS))
            extra_conditions.append(f"COALESCE(l.estado, '') NOT IN ({placeholders})")
            extra_params.extend(ESTADOS_CERRADOS)
        if ccaa:
            extra_conditions.append("l.ccaa = %s")
            extra_params.append(ccaa)
        if tecnologia:
            extra_conditions.append("l.tecnologia = %s")
            extra_params.append(tecnologia)
        if fecha_desde and _DATE_RE.match(fecha_desde):
            extra_conditions.append("l.fecha_publicacion >= %s")
            extra_params.append(fecha_desde)
        if fecha_hasta and _DATE_RE.match(fecha_hasta):
            extra_conditions.append("l.fecha_publicacion <= %s")
            extra_params.append(fecha_hasta)

        # Compilar order clause a string para insertar en FTS SQL
        compiled_order = str(order.compile(dialect=_DIALECT))
        # SA prefija la tabla: "licitaciones.fecha_publicacion DESC" → quitar prefijo
        compiled_order = compiled_order.replace("licitaciones.", "l.")

        extra_where = " AND ".join(extra_conditions)
        col_list = ", ".join(f"l.{c.key}" for c in _SUMMARY_COLS)
        match_clause = "l.search_vector @@ websearch_to_tsquery('spanish', %s)"
        base_sql = f"SELECT {col_list} FROM licitaciones l WHERE {match_clause} AND {extra_where}"
        count_sql = f"SELECT COUNT(*) FROM licitaciones l WHERE {match_clause} AND {extra_where}"

        with connect_read() as c:
            total = -1
            if with_total:
                count_row = c.execute(count_sql, [q, *extra_params]).fetchone()
                total = int(count_row[0]) if count_row else 0
            items = rows_to_dicts(
                c.execute(
                    base_sql + f" ORDER BY {compiled_order} LIMIT %s OFFSET %s",
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
        clauses = [
            and_(
                licitaciones.c.tecnologia.isnot(None),
                licitaciones.c.tecnologia != "",
            )
        ]

        if tecnologia:
            clauses.append(licitaciones.c.tecnologia == tecnologia)

        if cursor_fecha is not None and cursor_id is not None:
            clauses.append(
                or_(
                    licitaciones.c.fecha_publicacion < cursor_fecha,
                    and_(
                        licitaciones.c.fecha_publicacion == cursor_fecha,
                        licitaciones.c.id_externo < cursor_id,
                    ),
                )
            )

        stmt = (
            select(*_SUMMARY_COLS)
            .where(and_(*clauses))
            .order_by(
                licitaciones.c.fecha_publicacion.desc(),
                licitaciones.c.id_externo.desc(),
            )
            .limit(limit + 1)
        )
        sql, params = compile_query(stmt)
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, params))

    def get_by_id(self, id_externo: str) -> dict[str, Any] | None:
        """Devuelve el registro completo o None."""
        with connect_read() as c:
            cur = c.execute("SELECT * FROM licitaciones WHERE id_externo = %s", (id_externo,))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row, strict=False))

    def get_text_for_ml(self, id_externo: str) -> tuple[str, str, str | None] | None:
        """Devuelve (titulo, descripcion, tecnologia) o None."""
        with connect_read() as c:
            row = c.execute(
                "SELECT titulo, descripcion, tecnologia FROM licitaciones WHERE id_externo = %s",
                (id_externo,),
            ).fetchone()
        return (str(row[0] or ""), str(row[1] or ""), row[2]) if row else None

    def get_unlabelled_candidates(self, limit: int = 500) -> list[dict[str, Any]]:
        """Licitaciones no presentes en ml_feedback para active learning."""
        with connect_read() as c:
            cur = c.execute(
                "SELECT l.id_externo, l.titulo, l.descripcion, l.cpv, l.importe, "
                "l.organo_contratacion, l.ccaa, l.fecha_publicacion, l.url, "
                "l.tecnologia, l.ml_tecnologias, l.ml_proba_max, l.ml_tech_principal "
                "FROM licitaciones l "
                "LEFT JOIN ml_feedback f ON l.id_externo = f.expediente "
                "WHERE f.expediente IS NULL "
                "ORDER BY l.fecha_publicacion DESC LIMIT %s",
                (limit,),
            )
            return rows_to_dicts(cur)

    def get_unlabelled_random(self, limit: int = 20) -> list[dict[str, Any]]:
        with connect_read() as c:
            cur = c.execute(
                "SELECT l.id_externo, l.titulo, l.descripcion, l.cpv, l.importe, "
                "l.organo_contratacion, l.ccaa, l.fecha_publicacion, l.url, "
                "l.tecnologia, l.ml_tecnologias, l.ml_proba_max, l.ml_tech_principal "
                "FROM licitaciones l "
                "LEFT JOIN ml_feedback f ON l.id_externo = f.expediente "
                "WHERE f.expediente IS NULL "
                "ORDER BY RANDOM() LIMIT %s",
                (limit,),
            )
            return rows_to_dicts(cur)

    def get_filter_options(self) -> dict[str, list[str]]:
        """Devuelve listas de valores únicos para filtros (CCAA, estado, tecnologia, CPV)."""
        _ALLOWED_FILTER_COLS = {"estado", "ccaa", "tecnologia", "cpv"}

        with connect_read() as c:

            def _distinct(col: str) -> list[str]:
                if col not in _ALLOWED_FILTER_COLS:
                    raise ValueError(f"Columna no permitida para filtro: {col}")
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
            row = c.execute("SELECT MAX(fecha_extraccion) FROM licitaciones").fetchone()
        return str(row[0]) if row and row[0] else None

    def get_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
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
            rows = rows_to_dicts(cur)
        order = {id_: i for i, id_ in enumerate(ids)}
        return sorted(rows, key=lambda r: order.get(r.get("id_externo", ""), 999))

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
    ) -> tuple[list[dict[str, Any]], int]:
        """Búsqueda avanzada con criterios complejos (multi-valor, rangos de importe).

        Extiende ``list_paginated`` con soporte para listas de estado/ccaa/tecnologia
        (IN clause) y rangos de importe. Usada por el endpoint POST /licitaciones/search.
        """
        order = _SORT_MAP.get(sort or "", _DEFAULT_ORDER)
        clauses: list[Any] = [
            and_(
                licitaciones.c.tecnologia.isnot(None),
                licitaciones.c.tecnologia != "",
            )
        ]

        if q:
            like = f"%{_escape_like(q)}%"
            clauses.append(
                or_(
                    licitaciones.c.titulo.like(like),
                    licitaciones.c.descripcion.like(like),
                )
            )
        if estado:
            clauses.append(licitaciones.c.estado.in_(estado))
        if ccaa:
            clauses.append(licitaciones.c.ccaa.in_(ccaa))
        if tecnologia:
            clauses.append(licitaciones.c.tecnologia.in_(tecnologia))
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
            items = rows_to_dicts(c.execute(data_sql, data_params))

        return items, total

    def tech_scores_for(self, id_externo: str) -> list[dict[str, Any]]:
        """Devuelve scores por tecnología desde ``licitacion_tecnologia_score``."""
        stmt = (
            select(
                licitacion_tecnologia_score.c.tecnologia,
                licitacion_tecnologia_score.c.probabilidad,
                licitacion_tecnologia_score.c.threshold_aplicado,
                licitacion_tecnologia_score.c.computed_at,
            )
            .where(licitacion_tecnologia_score.c.licitacion_id == id_externo)
            .order_by(licitacion_tecnologia_score.c.probabilidad.desc())
        )
        sql, params = compile_query(stmt)
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, params))

    # ── Métodos para services (carga raw/stats/FTS/drift/stream) ─────────

    def load_uncertainty_zone(self, lo: float, hi: float, limit: int) -> list[dict[str, Any]]:
        """Licitaciones con ``ml_proba`` en zona de incertidumbre (active learning)."""
        with connect_read() as c:
            cur = c.execute(
                "SELECT id_externo, titulo, descripcion, organo_contratacion, importe, "
                "fecha_publicacion, cpv, ml_proba FROM licitaciones "
                "WHERE ml_proba IS NOT NULL AND ml_proba BETWEEN %s AND %s "
                "ORDER BY (importe IS NULL), importe DESC, ml_proba LIMIT %s",
                (lo, hi, limit),
            )
            return rows_to_dicts(cur)

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

    def load_drift_window(self, start: str, end: str) -> list[dict[str, Any]]:
        """Carga licitaciones de un rango de fechas para drift detection."""
        with connect_read() as c:
            cur = c.execute(
                "SELECT importe, cpv, ccaa, tecnologia, estado "
                "FROM licitaciones "
                "WHERE fecha_publicacion >= %s AND fecha_publicacion <= %s",
                (start, end),
            )
            return rows_to_dicts(cur)

    def fetch_recent(
        self,
        *,
        since_extraccion: str,
        since_actualizacion: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Carga licitaciones recientes para SSE streaming."""
        with connect_read() as c:
            cur = c.execute(
                "SELECT id_externo, titulo, organo_contratacion, importe, estado, "
                "url, fecha_publicacion, ccaa, tecnologia, fecha_extraccion, "
                "fecha_actualizacion_fuente "
                "FROM licitaciones "
                "WHERE fecha_extraccion >= %s OR fecha_actualizacion_fuente >= %s "
                "ORDER BY COALESCE(fecha_actualizacion_fuente, fecha_extraccion) DESC "
                "LIMIT %s",
                (since_extraccion, since_actualizacion, limit),
            )
            return rows_to_dicts(cur)

    def fetch_for_pdf(
        self,
        *,
        ccaa: str | None = None,
        estado: str | None = None,
        q: str | None = None,
        tecnologia: str | None = None,
        fecha_desde: str | None = None,
        fecha_hasta: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Carga licitaciones para exportación PDF.

        ``tecnologia``/``fecha_desde``/``fecha_hasta`` se filtran aquí y no en
        el llamador: la ruta de descarga los aplicaba en Python **después** de
        traer hasta 50 000 filas, así que el LIMIT se consumía con filas que
        luego se descartaban (una exportación filtrada podía salir corta).
        """
        conditions: list[str] = []
        params: list[Any] = []
        if ccaa:
            conditions.append("ccaa = %s")
            params.append(ccaa)
        if estado:
            conditions.append("estado = %s")
            params.append(estado)
        if tecnologia:
            conditions.append("tecnologia = ?")
            params.append(tecnologia)
        if fecha_desde:
            conditions.append("fecha_publicacion >= ?")
            params.append(fecha_desde)
        if fecha_hasta:
            conditions.append("fecha_publicacion <= ?")
            params.append(fecha_hasta)
        if q:
            like_op = "ILIKE"
            conditions.append(
                f"(titulo {like_op} %s ESCAPE '\\' OR descripcion {like_op} %s ESCAPE '\\')"
            )
            eq = _escape_like(q)
            params.extend([f"%{eq}%", f"%{eq}%"])
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with connect_read() as c:
            cur = c.execute(
                "SELECT id_externo, titulo, organo_contratacion, importe, estado, "
                "fecha_publicacion, ccaa, cpv, url, tecnologia "
                "FROM licitaciones" + where + " ORDER BY fecha_publicacion DESC LIMIT %s",
                [*params, limit],
            )
            return rows_to_dicts(cur)

    def search_fts_docs(
        self,
        query: str,
        *,
        ccaa: str | None = None,
        tecnologia: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Búsqueda por ``search_vector`` con metadatos completos (para RAG endpoint)."""
        conditions: list[str] = ["l.search_vector @@ websearch_to_tsquery('spanish', %s)"]
        params: list[Any] = [query]
        if ccaa:
            conditions.append("l.ccaa = %s")
            params.append(ccaa)
        if tecnologia:
            conditions.append("l.tecnologia = %s")
            params.append(tecnologia)
        where = " AND ".join(conditions)
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
                [*params, query, limit],
            )
            return rows_to_dicts(cur)

    def fts5_bm25_search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        """Búsqueda por ``ts_rank_cd`` normalizada para search_engine.

        Conserva el nombre histórico (``fts5_bm25``) porque es el contrato que
        consumen ``services/investigador/search_engine.py`` y sus tests; el
        motor detrás es Postgres desde ADR-021.
        """
        try:
            with connect_read() as c:
                cur = c.execute(
                    "SELECT id_externo, "
                    "ts_rank_cd(search_vector, websearch_to_tsquery('spanish', %s)) AS score "
                    "FROM licitaciones "
                    "WHERE search_vector @@ websearch_to_tsquery('spanish', %s) "
                    f"ORDER BY score DESC LIMIT {top_k * 2}",
                    [query, query],
                )
                rows = cur.fetchall()
        except Exception:
            log.warning("fts_bm25_search_failed", exc_info=True)
            return []

        if not rows:
            return []
        raw_scores = [abs(float(r[1])) for r in rows]
        max_s = max(raw_scores) if raw_scores else 1.0
        return [(r[0], s / max_s) for r, s in zip(rows, raw_scores, strict=False)]

    def like_fallback_search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        """LIKE fallback para cuando FTS5/search_vector no está disponible."""
        token = next(
            (w for w in query.split() if len(w) >= 4),
            query.split()[0] if query.split() else "",
        )
        if not token:
            return []
        # Postgres LIKE es case-sensitive: ILIKE para búsqueda insensible.
        like_op = "ILIKE"
        try:
            with connect_read() as c:
                cur = c.execute(
                    f"SELECT id_externo FROM licitaciones "
                    f"WHERE titulo {like_op} %s ESCAPE '\\' OR descripcion {like_op} %s ESCAPE '\\' "
                    "LIMIT %s",
                    [f"%{_escape_like(token)}%", f"%{_escape_like(token)}%", top_k],
                )
                return [(r[0], 0.20) for r in cur.fetchall()]
        except Exception:
            log.warning("like_fallback_search_failed", exc_info=True)
            return []

    def fetch_metadata_by_ids(
        self, ids: list[str], allowed_ids: set[str] | None = None
    ) -> dict[str, dict[str, Any]]:
        """Recupera metadatos de la BD para una lista de IDs."""
        if not ids:
            return {}
        if allowed_ids is not None:
            ids = [i for i in ids if i in allowed_ids]
        if not ids:
            return {}
        placeholders = ",".join("%s" for _ in ids)
        try:
            with connect_read() as c:
                cur = c.execute(
                    f"SELECT id_externo, titulo, organo_contratacion, importe, "
                    f"       descripcion, url, fecha_publicacion, ccaa, estado "
                    f"FROM licitaciones WHERE id_externo IN ({placeholders})",
                    ids,
                )
                cols = [d[0] for d in cur.description]
                return {r[0]: dict(zip(cols, r, strict=False)) for r in cur.fetchall()}
        except Exception:
            log.warning("metadata_fetch_by_ids_failed", exc_info=True)
            return {}

    def get_history(self, id_externo: str, limit: int = 50) -> list[dict[str, Any]]:
        """Devuelve el historial de cambios de una licitación."""
        limit = max(1, min(limit, 1000))
        with connect_read() as c:
            cur = c.execute(
                "SELECT id, id_externo, captured_at, source, snapshot_json, changed_fields "
                "FROM licitaciones_history "
                "WHERE id_externo = %s "
                "ORDER BY captured_at DESC LIMIT %s",
                [id_externo, limit],
            )
            return rows_to_dicts(cur)

    def search_like_for_ask(
        self,
        question: str,
        *,
        ccaa: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """LIKE fallback para /ask endpoint cuando FTS5 no devuelve resultados."""
        from services.investigador.search_engine import extract_keywords

        # Reutiliza la misma extracción de keywords que FTS5 (filtra stopwords
        # y palabras interrogativas) para no buscar por conectores genéricos
        # que devuelven documentos irrelevantes.
        words = extract_keywords(question)[:5]
        if not words:
            words = [w for w in question.split() if len(w) > 3][:5]
        if not words:
            return []
        like_op = "ILIKE"
        like_clauses = " OR ".join(
            f"titulo {like_op} %s ESCAPE '\\' OR descripcion {like_op} %s ESCAPE '\\'"
            for _ in words
        )
        params: list[Any] = []
        for w in words:
            escaped = f"%{_escape_like(w)}%"
            params.extend([escaped, escaped])
        conditions = [f"({like_clauses})"]
        if ccaa:
            conditions.append("ccaa = %s")
            params.append(ccaa)
        where = " AND ".join(conditions)
        try:
            with connect_read() as c:
                cur = c.execute(
                    "SELECT id_externo, titulo, organo_contratacion, importe, "
                    "estado, descripcion, ccaa, tecnologia, fecha_publicacion "
                    f"FROM licitaciones WHERE {where} LIMIT %s",
                    [*params, limit],
                )
                return rows_to_dicts(cur)
        except Exception:
            log.warning("like_search_for_ask_failed", exc_info=True)
            return []
