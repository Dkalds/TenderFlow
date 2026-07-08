"""Abstracción de búsqueda full-text multi-backend (ADR-016, F3a).

Define el protocolo ``SearchBackend`` y dos implementaciones:

- ``Fts5Backend``: FTS5 de SQLite (comportamiento actual, código verbatim).
- ``PgTsBackend``: ``tsvector``/``tsquery`` de Postgres con pg_trgm fallback.

El módulo expone ``get_search_backend()`` que detecta el backend activo y
devuelve la instancia correcta. Los call-sites en:
  - ``db/repositories/licitaciones.py``
  - ``db/upsert.py`` (``fts_available()``)
  - ``services/investigador/search_engine.py``
  - ``api/routes/ask.py`` y ``api/routes/search.py``
…se recablearán a este módulo en F3b.

Durante F3a el backend activo es siempre FTS5 (SQLite); PgTsBackend se
instancia pero no se expone en producción hasta que DATABASE_URL apunte a
Postgres y la migración v50 haya creado search_vector + índice GIN.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Protocolo
# ---------------------------------------------------------------------------


@runtime_checkable
class SearchBackend(Protocol):
    """Contrato mínimo de un backend de búsqueda full-text."""

    def available(self) -> bool:
        """True si el backend está operativo en la BD actual."""
        ...

    def search_ids(
        self,
        conn: Any,
        query: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[str]:
        """Devuelve lista de id_externo ordenados por relevancia."""
        ...

    def search_docs(
        self,
        conn: Any,
        query: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Devuelve dicts con id_externo + campos de contexto (snippet)."""
        ...

    def ranked_search(
        self,
        conn: Any,
        query: str,
        *,
        limit: int = 50,
    ) -> list[tuple[str, float]]:
        """Devuelve (id_externo, score) ordenados por relevancia."""
        ...


# ---------------------------------------------------------------------------
# Backend FTS5 (SQLite — actual)
# ---------------------------------------------------------------------------


class Fts5Backend:
    """Implementación FTS5 para SQLite/Turso.

    Replica el comportamiento actual de ``db/upsert.py:search_fts`` y de
    ``services/investigador/search_engine.py:fts5_search`` sin cambiar la
    semántica. Los call-sites que ya usan esas funciones no cambian para el
    cutover; este backend es el envoltorio formal para la abstracción.
    """

    def available(self) -> bool:
        """True si la tabla FTS5 ``licitaciones_fts`` existe."""
        try:
            from db.database import fts_available

            return fts_available()
        except Exception:
            return False

    def search_ids(
        self,
        conn: Any,
        query: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[str]:
        from db.database import search_fts

        rows, _ = search_fts(query, limit=limit, offset=offset)
        return [r["id_externo"] for r in rows]

    def search_docs(
        self,
        conn: Any,
        query: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        from db.database import search_fts

        rows, _ = search_fts(query, limit=limit, offset=offset)
        return list(rows)

    def ranked_search(
        self,
        conn: Any,
        query: str,
        *,
        limit: int = 50,
    ) -> list[tuple[str, float]]:
        """FTS5 bm25 rank (valores negativos = más relevante)."""
        try:
            from db.connection import _translate_qmarks

            sql = _translate_qmarks(
                "SELECT l.id_externo, bm25(licitaciones_fts) AS score "
                "FROM licitaciones_fts "
                "JOIN licitaciones l ON l.id_externo = licitaciones_fts.id_externo "
                "WHERE licitaciones_fts MATCH ? "
                "ORDER BY score "
                "LIMIT ?"
            )
            rows = conn.execute(sql, (query, limit)).fetchall()
            return [(r[0], float(r[1])) for r in rows]
        except Exception:
            return []


# ---------------------------------------------------------------------------
# Backend PgTs (Postgres — destino F3)
# ---------------------------------------------------------------------------


class PgTsBackend:
    """Implementación tsvector/tsquery para Postgres (ADR-016).

    Usa ``websearch_to_tsquery('spanish', query)`` — inmune a inyección SQL,
    sustituye a ``escape_fts5``. Fallback a pg_trgm LIKE si la columna
    ``search_vector`` no existe aún (antes de v50).

    ``ts_rank_cd`` (cover density) para ranking.
    """

    _LANG = "spanish"

    def available(self) -> bool:
        """True si Postgres está activo y la columna search_vector existe."""
        from db.connection import is_postgres_backend

        if not is_postgres_backend():
            return False
        try:
            from db.database import connect_read

            with connect_read() as conn:
                cur = conn.execute(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name='licitaciones' AND column_name='search_vector' LIMIT 1"
                )
                return cur.fetchone() is not None
        except Exception:
            return False

    def search_ids(
        self,
        conn: Any,
        query: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[str]:
        rows = self._ts_search(conn, query, limit=limit, offset=offset)
        return [r[0] for r in rows]

    def search_docs(
        self,
        conn: Any,
        query: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = self._ts_search(conn, query, limit=limit, offset=offset)
        return [{"id_externo": r[0], "score": r[1]} for r in rows]

    def ranked_search(
        self,
        conn: Any,
        query: str,
        *,
        limit: int = 50,
    ) -> list[tuple[str, float]]:
        return self._ts_search(conn, query, limit=limit)

    def _ts_search(
        self,
        conn: Any,
        query: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[tuple[str, float]]:
        """Búsqueda con tsvector + ts_rank_cd; fallback a pg_trgm si search_vector no existe."""
        # Intento 1: tsvector GIN (óptimo)
        try:
            sql = (
                "SELECT id_externo, ts_rank_cd(search_vector, websearch_to_tsquery(%s, %s)) AS rank "
                "FROM licitaciones "
                "WHERE search_vector @@ websearch_to_tsquery(%s, %s) "
                "ORDER BY rank DESC "
                "LIMIT %s OFFSET %s"
            )
            rows = conn.execute(
                sql, (self._LANG, query, self._LANG, query, limit, offset)
            ).fetchall()
            return [(r[0], float(r[1])) for r in rows]
        except Exception:
            pass

        # Fallback: pg_trgm ILIKE (antes de que exista search_vector)
        try:
            pattern = f"%{query}%"
            sql = (
                "SELECT id_externo, 0.5 AS rank "
                "FROM licitaciones "
                "WHERE titulo ILIKE %s OR descripcion ILIKE %s "
                "LIMIT %s OFFSET %s"
            )
            rows = conn.execute(sql, (pattern, pattern, limit, offset)).fetchall()
            return [(r[0], float(r[1])) for r in rows]
        except Exception:
            return []


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_BACKEND: SearchBackend | None = None


def get_search_backend() -> SearchBackend:
    """Devuelve el backend de búsqueda activo.

    - Postgres con search_vector → ``PgTsBackend``
    - SQLite con FTS5 → ``Fts5Backend``
    - Fallback → ``Fts5Backend`` (puede devolver listas vacías si FTS no está disponible)
    """
    from db.connection import is_postgres_backend

    if is_postgres_backend():
        pg = PgTsBackend()
        if pg.available():
            return pg
        # Postgres activo pero sin search_vector aún (antes de v50)
        return pg  # pg.search_ids usará el fallback pg_trgm

    return Fts5Backend()
