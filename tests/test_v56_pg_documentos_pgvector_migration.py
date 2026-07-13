"""Tests unitarios para la migración v56 (pgvector + documentos) con ``alembic.op`` mockeado.

No requiere una BD Postgres real: mockea ``op.get_bind()``/``op.execute()`` para
verificar el guard de dialecto y qué SQL se ejecuta en cada rama, mismo patrón
que ``test_v52_rls_lockdown_migration.py``. La aplicación real de este SQL
contra Postgres se valida en CI (job ``schema-migrations-postgres``, imagen
``pgvector/pgvector:pg16``).

El equivalente SQLite (``db/schema.py::documentos``/``documento_chunks``) se
valida por separado en ``test_documentos_schema_sqlite.py`` (contra ``tmp_db``).
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock


def _load_migration():
    return importlib.import_module("db.alembic.versions.v56_pg_documentos_pgvector")


def _fake_bind(dialect_name: str) -> SimpleNamespace:
    return SimpleNamespace(dialect=SimpleNamespace(name=dialect_name))


def test_is_postgres_true_for_postgresql_dialect(monkeypatch):
    mod = _load_migration()
    monkeypatch.setattr(mod.op, "get_bind", lambda: _fake_bind("postgresql"))
    assert mod._is_postgres() is True


def test_is_postgres_false_for_sqlite_dialect(monkeypatch):
    mod = _load_migration()
    monkeypatch.setattr(mod.op, "get_bind", lambda: _fake_bind("sqlite"))
    assert mod._is_postgres() is False


def test_upgrade_is_noop_on_sqlite(monkeypatch):
    mod = _load_migration()
    monkeypatch.setattr(mod, "_is_postgres", lambda: False)
    execute_mock = MagicMock()
    monkeypatch.setattr(mod.op, "execute", execute_mock)

    mod.upgrade()

    execute_mock.assert_not_called()


def test_downgrade_is_noop_on_sqlite(monkeypatch):
    mod = _load_migration()
    monkeypatch.setattr(mod, "_is_postgres", lambda: False)
    execute_mock = MagicMock()
    monkeypatch.setattr(mod.op, "execute", execute_mock)

    mod.downgrade()

    execute_mock.assert_not_called()


def test_upgrade_creates_extension_tables_and_indexes_on_postgres(monkeypatch):
    mod = _load_migration()
    monkeypatch.setattr(mod, "_is_postgres", lambda: True)
    execute_mock = MagicMock()
    monkeypatch.setattr(mod.op, "execute", execute_mock)

    mod.upgrade()

    calls = [c.args[0] for c in execute_mock.call_args_list]
    assert calls[0] == mod._CREATE_EXTENSION_VECTOR
    assert calls[1] == mod._CREATE_DOCUMENTOS
    assert calls[2] == mod._CREATE_DOCUMENTO_CHUNKS
    assert calls[3:] == list(mod._INDEXES)


def test_downgrade_drops_in_reverse_dependency_order_on_postgres(monkeypatch):
    """Los chunks (FK -> documentos) se dropean antes que documentos."""
    mod = _load_migration()
    monkeypatch.setattr(mod, "_is_postgres", lambda: True)
    execute_mock = MagicMock()
    monkeypatch.setattr(mod.op, "execute", execute_mock)

    mod.downgrade()

    calls = [c.args[0] for c in execute_mock.call_args_list]
    chunks_drop_idx = next(
        i for i, s in enumerate(calls) if "DROP TABLE" in s and "documento_chunks" in s
    )
    documentos_drop_idx = next(
        i for i, s in enumerate(calls) if "DROP TABLE" in s and s.endswith("documentos")
    )
    assert chunks_drop_idx < documentos_drop_idx
    assert not any("vector" in s and "EXTENSION" in s for s in calls)  # no se dropea la extension


def test_create_extension_is_idempotent():
    mod = _load_migration()
    assert "IF NOT EXISTS" in mod._CREATE_EXTENSION_VECTOR


def test_documentos_ddl_has_expected_shape():
    mod = _load_migration()
    ddl = mod._CREATE_DOCUMENTOS
    assert "REFERENCES licitaciones(id_externo) ON DELETE CASCADE" in ddl
    assert "CHECK (tipo IN ('legal', 'technical', 'additional'))" in ddl
    assert "storage_key   TEXT," in ddl  # reservado para blob storage futuro
    assert "UNIQUE (licitacion_id, uri)" in ddl


def test_documento_chunks_ddl_has_vector_and_search_columns():
    mod = _load_migration()
    ddl = mod._CREATE_DOCUMENTO_CHUNKS
    assert "embedding     vector(384)" in ddl
    assert "GENERATED ALWAYS AS" in ddl and "to_tsvector('spanish'" in ddl
    assert "UNIQUE (documento_id, chunk_index)" in ddl


def test_hnsw_index_uses_vector_cosine_ops():
    mod = _load_migration()
    hnsw = next(s for s in mod._INDEXES if "hnsw" in s)
    assert "vector_cosine_ops" in hnsw
    assert "embedding" in hnsw
