"""Regresiones unitarias de la migración v129 (``user_id`` fase 2, ADR-030).

La ejecución real contra Postgres la cubre
``tests/test_user_id_cambio_email_integration.py``; aquí se congela la forma:
cadena de revisiones, inventario de tablas y qué DDL emite cada rama.
"""

from __future__ import annotations

import importlib
from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any


class _Inspector:
    def __init__(self, tablas: list[str]) -> None:
        self._tablas = tablas

    def get_table_names(self) -> list[str]:
        return self._tablas


class _PostgresOp:
    def __init__(self) -> None:
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
        self.statements: list[str] = []
        self.autocommit_entries = 0

    def get_bind(self) -> Any:
        return self.bind

    def execute(self, statement: Any) -> None:
        self.statements.append(str(statement))

    def get_context(self) -> Any:
        parent = self

        class _Context:
            def autocommit_block(self) -> Any:
                parent.autocommit_entries += 1
                return nullcontext()

        return _Context()


def _load() -> Any:
    return importlib.import_module("db.alembic.versions.v129_user_id_fase2")


def test_v129_cadena_e_inventario() -> None:
    migracion = _load()

    assert migracion.revision == "v129_user_id_fase2"
    assert migracion.down_revision == "v128_rls_tenant_policies"
    assert set(migracion.TABLAS_NUEVAS) == {
        "audit_log",
        "notification_reads",
        "pending_digests",
        "radar_dismissals",
        "saved_filters",
        "user_notifications",
        "user_profiles",
        "watchlist_empresas",
        "user_event_prefs",
    }
    assert set(migracion.TABLAS_PREVIAS) == {"watchlist_cpv", "watchlist_items", "watchlist_rules"}
    assert len(migracion.TABLAS) == 12


def test_v129_no_hace_nada_fuera_de_postgres(monkeypatch) -> None:
    migracion = _load()
    monkeypatch.setattr(migracion, "_is_postgres", lambda: False)

    class _FailingOp:
        def execute(self, statement: Any) -> None:
            raise AssertionError(f"SQL inesperado: {statement}")

    monkeypatch.setattr(migracion, "op", _FailingOp())
    migracion.upgrade()
    migracion.downgrade()


def test_v129_upgrade_anade_columnas_backfillea_e_indexa(monkeypatch) -> None:
    migracion = _load()
    fake_op = _PostgresOp()
    monkeypatch.setattr(migracion, "op", fake_op)
    monkeypatch.setattr(
        migracion.sa, "inspect", lambda _bind: _Inspector([*migracion.TABLAS, "users"])
    )

    migracion.upgrade()
    sql = "\n".join(fake_op.statements)

    # Columna sólo en las nueve nuevas.
    for tabla in migracion.TABLAS_NUEVAS:
        assert f"ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS user_id INTEGER" in sql
    for tabla in migracion.TABLAS_PREVIAS:
        assert f"ALTER TABLE {tabla} ADD COLUMN" not in sql
    # FK e índice en las once que no los tenían; watchlist_cpv los trae de v53.
    for tabla in migracion.TABLAS:
        if tabla == "watchlist_cpv":
            assert f"fk_{tabla}_user_id" not in sql
            assert f"idx_{tabla}_user_id" not in sql
            continue
        assert f"ADD CONSTRAINT fk_{tabla}_user_id" in sql
        assert f"VALIDATE CONSTRAINT fk_{tabla}_user_id" in sql
        assert f"CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_{tabla}_user_id" in sql
    # Backfill: claves en tabla temporal, un UPDATE por tabla y el extra de audit_log.
    assert "CREATE TEMPORARY TABLE v129_claves" in sql
    for tabla in migracion.TABLAS:
        assert migracion.sql_backfill(tabla) in sql
    assert migracion.SQL_BACKFILL_AUDIT_POR_ID in sql
    # El backfill va ANTES de validar las FK y los índices al final, concurrentes.
    assert sql.index("v129_claves") < sql.index("VALIDATE CONSTRAINT")
    assert sql.index("VALIDATE CONSTRAINT") < sql.index("CREATE INDEX CONCURRENTLY")
    assert fake_op.autocommit_entries == 1


def test_v129_downgrade_retira_solo_lo_anadido(monkeypatch) -> None:
    migracion = _load()
    fake_op = _PostgresOp()
    monkeypatch.setattr(migracion, "op", fake_op)
    monkeypatch.setattr(migracion.sa, "inspect", lambda _bind: _Inspector(list(migracion.TABLAS)))

    migracion.downgrade()
    sql = "\n".join(fake_op.statements)

    for tabla in migracion.TABLAS_NUEVAS:
        assert f"ALTER TABLE {tabla} DROP COLUMN IF EXISTS user_id" in sql
    for tabla in migracion.TABLAS_PREVIAS:
        assert f"ALTER TABLE {tabla} DROP COLUMN" not in sql
    assert "DROP INDEX CONCURRENTLY IF EXISTS idx_watchlist_cpv_user_id" not in sql
    assert "DROP CONSTRAINT IF EXISTS fk_watchlist_cpv_user_id" not in sql
    assert "DROP CONSTRAINT IF EXISTS fk_watchlist_items_user_id" in sql
