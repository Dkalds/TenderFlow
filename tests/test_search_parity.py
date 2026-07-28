"""Tests de contrato del protocolo ``SearchBackend``.

Este fichero nació como gate de cutover FTS5 (SQLite) ↔ PgTsBackend
(Postgres): comparaba los resultados de ambos motores por Jaccard para
garantizar que la migración no perdía cobertura. Cumplido el cutover y
retirado SQLite (ADR-021) no queda con qué comparar, así que la comparación
se eliminó y quedan los tests de contrato del protocolo, que siguen siendo
útiles: son lo que garantiza que un backend alternativo (o un doble de test)
puede sustituir al real.
"""

from __future__ import annotations

# ── Tests de contrato del protocolo ──────────────────────────────────────────


class TestSearchBackendProtocol:
    """Verifica que PgTsBackend implementa el protocolo.

    ``Fts5Backend`` se retiró con SQLite (ADR-021); el protocolo se conserva
    como punto de extensión y para poder inyectar dobles en los call-sites.
    """

    def test_pg_backend_implements_protocol(self):
        from db.search_backend import PgTsBackend, SearchBackend

        backend = PgTsBackend()
        assert isinstance(backend, SearchBackend)
        assert hasattr(backend, "available")
        assert hasattr(backend, "search_ids")
        assert hasattr(backend, "search_docs")
        assert hasattr(backend, "ranked_search")

    def test_get_search_backend_returns_pgts(self):
        """get_search_backend devuelve siempre PgTsBackend (ADR-021)."""
        from db.search_backend import PgTsBackend, get_search_backend

        assert isinstance(get_search_backend(), PgTsBackend)

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

    def test_pg_ranked_search_returns_tuples(self, tmp_db):
        """ranked_search devuelve lista de (str, float)."""
        from db.database import connect
        from db.search_backend import PgTsBackend

        backend = PgTsBackend()
        with connect() as conn:
            result = backend.ranked_search(conn, "SAP", limit=5)
        assert isinstance(result, list)
        for item in result:
            assert len(item) == 2
            assert isinstance(item[0], str)
            assert isinstance(item[1], float)

    def test_pg_backend_not_available_without_database_url(self, monkeypatch):
        """PgTsBackend.available() devuelve False sin DATABASE_URL."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        from config import settings

        monkeypatch.setattr(settings, "DATABASE_URL", "", raising=False)

        from db.search_backend import PgTsBackend

        backend = PgTsBackend()
        assert not backend.available()
