"""Regresiones de la migración de endurecimiento de identidad v58."""

from __future__ import annotations

import importlib
from types import SimpleNamespace


class _PostgresOp:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def get_bind(self) -> SimpleNamespace:
        return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    def execute(self, statement: str) -> None:
        self.statements.append(statement)


def test_v58_postgres_upgrade_adds_key_ownership_and_scopes(monkeypatch) -> None:
    """Un bootstrap Postgres obtiene columnas que habilitan RBAC y aislamiento."""
    migration = importlib.import_module("db.alembic.versions.v58_security_identity_hardening")
    fake_op = _PostgresOp()
    monkeypatch.setattr(migration, "op", fake_op)

    migration.upgrade()

    assert "ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS user_id INTEGER" in fake_op.statements
    assert "ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS scopes TEXT NOT NULL DEFAULT '*'" in fake_op.statements
    assert any("api_keys_user_id_fkey" in statement for statement in fake_op.statements)
