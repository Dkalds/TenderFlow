"""Tests de ``PgTsBackend``: disponibilidad y búsqueda por texto.

Este fichero nació como gate de cutover FTS5 (SQLite) ↔ PgTsBackend
(Postgres). Retirado SQLite (ADR-021) y, el 2026-09-28, el protocolo
``SearchBackend`` que solo sostenían estos tests, quedan las comprobaciones
del backend real.
"""

from __future__ import annotations


class TestPgTsBackend:
    def test_pg_available_reflects_db_state(self, tmp_db):
        """available() refleja si la columna search_vector existe."""
        from db.search_backend import PgTsBackend

        assert isinstance(PgTsBackend().available(), bool)

    def test_pg_search_ids_returns_list(self, tmp_db):
        """search_ids devuelve lista (vacía si no hay datos)."""
        from db.database import connect
        from db.search_backend import PgTsBackend

        backend = PgTsBackend()
        with connect() as conn:
            result = backend.search_ids(conn, "SAP", limit=10)
        assert isinstance(result, list)

    def test_pg_backend_not_available_without_database_url(self, monkeypatch):
        """PgTsBackend.available() devuelve False sin DATABASE_URL."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        from config import settings

        monkeypatch.setattr(settings, "DATABASE_URL", "", raising=False)

        from db.search_backend import PgTsBackend

        backend = PgTsBackend()
        assert not backend.available()
