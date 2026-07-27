"""Regression checks for the v59 Postgres security migration."""

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


def test_v59_creates_signed_audit_head_and_revokes_public_execute(monkeypatch) -> None:
    migration = importlib.import_module(
        "db.alembic.versions.v59_audit_chain_state_and_public_execute"
    )
    fake_op = _PostgresOp()
    monkeypatch.setattr(migration, "op", fake_op)

    migration.upgrade()

    joined = "\n".join(fake_op.statements)
    assert "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)" in joined
    assert "CREATE TABLE IF NOT EXISTS audit_chain_state" in joined
    assert "REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM PUBLIC" in joined
    assert (
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC"
        in joined
    )
    assert "response_json::jsonb - 'secret'" in joined
