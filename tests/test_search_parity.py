"""Test de paridad de búsqueda FTS5 (SQLite) ↔ PgTsBackend (Postgres) — F3b.

Gate de cutover: ninguna query con resultados en FTS5 debe devolver lista
vacía en Postgres. Jaccard top-10 ≥ 0.6 (protege cobertura, no orden exacto).

Los tests se ejecutan en SQLite en CI normal (FTS5Backend).
Para ejecutar el test de paridad real contra Postgres, definir DATABASE_URL
en el entorno antes de correr pytest.

Marcadores:
  - unit: tests de contratos del protocolo SearchBackend
  - integration: test de paridad (requiere DATABASE_URL definida y tablas pobladas)
"""

from __future__ import annotations

import pytest

# ── Tests de contrato del protocolo ──────────────────────────────────────────


class TestSearchBackendProtocol:
    """Verifica que Fts5Backend y PgTsBackend implementan el protocolo."""

    def test_fts5_backend_implements_protocol(self):
        from db.search_backend import Fts5Backend, SearchBackend

        backend = Fts5Backend()
        assert isinstance(backend, SearchBackend)
        assert hasattr(backend, "available")
        assert hasattr(backend, "search_ids")
        assert hasattr(backend, "search_docs")
        assert hasattr(backend, "ranked_search")

    def test_pg_backend_implements_protocol(self):
        from db.search_backend import PgTsBackend, SearchBackend

        backend = PgTsBackend()
        assert isinstance(backend, SearchBackend)
        assert hasattr(backend, "available")
        assert hasattr(backend, "search_ids")
        assert hasattr(backend, "search_docs")
        assert hasattr(backend, "ranked_search")

    def test_get_search_backend_returns_fts5_without_pg(self, monkeypatch):
        """Sin DATABASE_URL, get_search_backend devuelve Fts5Backend."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        # Limpiar override de settings si existe
        import os

        os.environ.pop("DATABASE_URL", None)

        from db.search_backend import Fts5Backend, get_search_backend

        backend = get_search_backend()
        assert isinstance(backend, Fts5Backend)

    def test_fts5_available_reflects_db_state(self, tmp_db):
        """Fts5Backend.available() devuelve True si FTS5 existe en la BD."""
        from db.search_backend import Fts5Backend

        backend = Fts5Backend()
        # La BD tmp_db puede o no tener FTS5 según la migración aplicada
        result = backend.available()
        assert isinstance(result, bool)

    def test_fts5_search_ids_returns_list(self, tmp_db):
        """search_ids devuelve lista (vacía si no hay datos)."""
        from db.database import connect
        from db.search_backend import Fts5Backend

        backend = Fts5Backend()
        with connect() as conn:
            result = backend.search_ids(conn, "SAP", limit=10)
        assert isinstance(result, list)

    def test_fts5_ranked_search_returns_tuples(self, tmp_db):
        """ranked_search devuelve lista de (str, float)."""
        from db.database import connect
        from db.search_backend import Fts5Backend

        backend = Fts5Backend()
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
        import os

        os.environ.pop("DATABASE_URL", None)

        from db.search_backend import PgTsBackend

        backend = PgTsBackend()
        assert not backend.available()


# ── Test de paridad (solo cuando DATABASE_URL está definido) ──────────────────


_SAMPLE_QUERIES = [
    "SAP Basis",
    "ciberseguridad",
    "desarrollo software",
    "mantenimiento infraestructura",
    "consultoría tecnología",
    "licencias microsoft",
    "servicios cloud",
    "redes comunicaciones",
    "inteligencia artificial",
    "gestión documental",
]


def _jaccard(a: list[str], b: list[str]) -> float:
    """Coeficiente de Jaccard entre dos listas (conjuntos)."""
    set_a = set(a)
    set_b = set(b)
    if not set_a and not set_b:
        return 1.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


@pytest.mark.integration
def test_search_parity_fts5_vs_pg(tmp_db):
    """Paridad Jaccard top-10 ≥ 0.6 entre FTS5 y PgTs para todas las queries.

    Solo se ejecuta si DATABASE_URL está definida Y PgTsBackend está disponible.
    Si no, el test se saltea (no falla CI normal).
    """
    import os

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        pytest.skip("DATABASE_URL no definida — test de paridad PG saltado")

    from db.search_backend import Fts5Backend, PgTsBackend

    fts5 = Fts5Backend()
    pg = PgTsBackend()

    if not pg.available():
        pytest.skip("PgTsBackend no disponible (search_vector no existe aún)")

    if not fts5.available():
        pytest.skip("Fts5Backend no disponible (FTS5 no existe en la BD de test)")

    from db.database import connect

    failures: list[str] = []

    with connect() as conn:
        for query in _SAMPLE_QUERIES:
            fts5_ids = fts5.search_ids(conn, query, limit=10)
            pg_ids = pg.search_ids(conn, query, limit=10)

            if not fts5_ids:
                # No hay resultados en FTS5 → no hay contra qué comparar
                continue

            if not pg_ids:
                failures.append(
                    f"'{query}': FTS5 devolvió {len(fts5_ids)} resultados, PG devolvió 0"
                )
                continue

            jaccard = _jaccard(fts5_ids[:10], pg_ids[:10])
            if jaccard < 0.6:
                failures.append(
                    f"'{query}': Jaccard={jaccard:.2f} < 0.6 "
                    f"(fts5={fts5_ids[:3]}…, pg={pg_ids[:3]}…)"
                )

    if failures:
        pytest.fail(
            f"Paridad de búsqueda insuficiente ({len(failures)}/{len(_SAMPLE_QUERIES)} queries):\n"
            + "\n".join(f"  - {f}" for f in failures)
        )
