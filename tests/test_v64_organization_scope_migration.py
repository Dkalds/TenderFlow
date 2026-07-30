"""Regresiones unitarias de la migración organizativa v64."""

from __future__ import annotations

import hashlib
import importlib
from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any


class _Rows:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> list[dict[str, Any]]:
        return self._rows


class _Bind:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.dialect = SimpleNamespace(name="postgresql")
        self.rows = rows or []
        self.calls: list[tuple[Any, Any]] = []

    def execute(self, statement: Any, params: Any = None) -> _Rows:
        self.calls.append((statement, params))
        if "SELECT u.id AS user_id" in str(statement):
            return _Rows(self.rows)
        return _Rows([])


class _PostgresOp:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.bind = _Bind(rows)
        self.statements: list[str] = []
        self.autocommit_entries = 0

    def get_bind(self) -> _Bind:
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


def _load_migration() -> Any:
    return importlib.import_module("db.alembic.versions.v64_organization_scope")


def test_v64_revision_chain_and_scope_shape() -> None:
    migration = _load_migration()

    assert migration.revision == "v64_organization_scope"
    assert migration.down_revision == "v63_lineage_index_concurrent"
    assert set(migration._SCOPED_TABLES) == {
        "watchlist_items",
        "watchlist_rules",
        "watchlist_empresas",
        "watchlist_cpv",
        "saved_filters",
        "user_profiles",
        "user_notifications",
    }
    assert migration._SCOPED_TABLES["user_notifications"] == (False, False)


def test_v64_identity_keys_cover_current_and_legacy_forms() -> None:
    migration = _load_migration()
    api_key_hash = "a" * 64

    keys = list(
        migration._identity_keys(
            user_id=7,
            email=" User@Example.com ",
            api_key_hash=api_key_hash,
        )
    )

    assert keys[0] == hashlib.sha256(b"user@example.com").hexdigest()[:16]
    assert "user@example.com" in keys
    assert "7" in keys
    assert api_key_hash in keys
    assert hashlib.sha256(api_key_hash.encode()).hexdigest()[:16] in keys


def test_v64_upgrade_is_noop_outside_postgres(monkeypatch) -> None:
    migration = _load_migration()
    monkeypatch.setattr(migration, "_is_postgres", lambda: False)

    class _FailingOp:
        def execute(self, statement: Any) -> None:
            raise AssertionError(f"unexpected SQL: {statement}")

    monkeypatch.setattr(migration, "op", _FailingOp())
    migration.upgrade()


def test_v64_upgrade_adds_scope_backfills_and_locks_down(monkeypatch) -> None:
    migration = _load_migration()
    fake_op = _PostgresOp(
        [
            {
                "user_id": 7,
                "email": "user@example.com",
                "organization_id": 70,
                "key_hash": "a" * 64,
            }
        ]
    )
    monkeypatch.setattr(migration, "op", fake_op)

    migration.upgrade()

    sql = "\n".join(fake_op.statements)
    assert migration._ENSURE_PERSONAL_ORGANIZATIONS.strip() in sql
    assert migration._ENSURE_PERSONAL_MEMBERSHIPS.strip() in sql
    for table, (_has_user_id, has_visibility) in migration._SCOPED_TABLES.items():
        assert f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS organization_id" in sql
        assert f"fk_{table}_organization_id" in sql
        assert f"UPDATE {table} AS target" in sql
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in sql
        assert f"REVOKE ALL ON TABLE {table} FROM anon" in sql
        assert f"REVOKE ALL ON TABLE {table} FROM authenticated" in sql
        assert f"CREATE POLICY tenderflow_app_full_access ON {table}" in sql
        assert (
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            f"idx_{table}_organization ON {table} (organization_id)"
        ) in sql
        if has_visibility:
            assert f"ck_{table}_visibility" in sql
            assert f"ALTER TABLE {table} ALTER COLUMN visibility SET NOT NULL" in sql
        else:
            assert f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS visibility" not in sql
    assert "FOREIGN KEY (organization_id)" in sql
    assert "ON DELETE CASCADE NOT VALID" in sql
    assert sql.count("SET organization_id = personal.id") == sum(
        has_user_id for has_user_id, _ in migration._SCOPED_TABLES.values()
    )
    assert fake_op.autocommit_entries == 1

    identity_insert = [
        params
        for statement, params in fake_op.bind.calls
        if "INSERT INTO v64_identity_scope" in str(statement)
    ]
    assert identity_insert
    assert {row["user_key"] for row in identity_insert[0]} >= {
        hashlib.sha256(b"user@example.com").hexdigest()[:16],
        "a" * 64,
    }


def test_v64_downgrade_removes_only_added_scope(monkeypatch) -> None:
    migration = _load_migration()
    fake_op = _PostgresOp()
    monkeypatch.setattr(migration, "op", fake_op)

    migration.downgrade()

    sql = "\n".join(fake_op.statements)
    for table, (_, has_visibility) in migration._SCOPED_TABLES.items():
        assert f"DROP INDEX CONCURRENTLY IF EXISTS idx_{table}_organization" in sql
        assert f"ALTER TABLE {table} DROP COLUMN IF EXISTS organization_id" in sql
        if has_visibility:
            assert f"ALTER TABLE {table} DROP COLUMN IF EXISTS visibility" in sql
    assert "DISABLE ROW LEVEL SECURITY" not in sql
    assert "FROM anon" not in sql
    assert fake_op.autocommit_entries == 1
