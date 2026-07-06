"""Tests unitarios para la migración v52 (RLS lockdown) con ``alembic.op`` mockeado.

No requiere una BD Postgres real: mockea ``op.get_bind()``/``op.execute()`` para
verificar el guard de dialecto y qué SQL se ejecuta en cada rama. La aplicación
real de este SQL contra un Postgres vivo se valida por separado (ver
``docs/runbooks/migracion-persistencia.md``), no por esta suite unitaria.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock


def _load_migration():
    return importlib.import_module("db.alembic.versions.v52_rls_lockdown")


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


def test_upgrade_enables_rls_and_revokes_on_postgres(monkeypatch):
    mod = _load_migration()
    monkeypatch.setattr(mod, "_is_postgres", lambda: True)
    execute_mock = MagicMock()
    monkeypatch.setattr(mod.op, "execute", execute_mock)

    mod.upgrade()

    calls = [c.args[0] for c in execute_mock.call_args_list]
    assert calls == [mod._ENABLE_RLS, mod._REVOKE_EXPOSED_ROLES]


def test_downgrade_is_noop_on_sqlite(monkeypatch):
    mod = _load_migration()
    monkeypatch.setattr(mod, "_is_postgres", lambda: False)
    execute_mock = MagicMock()
    monkeypatch.setattr(mod.op, "execute", execute_mock)

    mod.downgrade()

    execute_mock.assert_not_called()


def test_downgrade_regrants_and_disables_rls_on_postgres(monkeypatch):
    """Downgrade reversa al estado inseguro previo -- solo para rollback."""
    mod = _load_migration()
    monkeypatch.setattr(mod, "_is_postgres", lambda: True)
    execute_mock = MagicMock()
    monkeypatch.setattr(mod.op, "execute", execute_mock)

    mod.downgrade()

    calls = [c.args[0] for c in execute_mock.call_args_list]
    assert calls == [mod._REGRANT_EXPOSED_ROLES, mod._DISABLE_RLS]


def test_revoke_sql_guards_role_existence():
    """El REVOKE debe estar guardado por pg_roles (no falla si anon/authenticated no existen)."""
    mod = _load_migration()
    assert "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')" in mod._REVOKE_EXPOSED_ROLES
    assert (
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated')"
        in mod._REVOKE_EXPOSED_ROLES
    )


def test_enable_rls_excludes_alembic_version_table():
    mod = _load_migration()
    assert "tablename <> 'alembic_version'" in mod._ENABLE_RLS
