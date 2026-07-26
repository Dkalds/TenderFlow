"""Static safety checks for the production PostgreSQL role bootstrap script."""

from __future__ import annotations

from pathlib import Path


def test_runtime_role_is_explicitly_non_privileged() -> None:
    script = Path("scripts/setup_pg_roles.sql").read_text(encoding="utf-8")
    assert "NOBYPASSRLS" in script
    assert "NOCREATEDB" in script
    assert "NOCREATEROLE" in script
    assert "REVOKE CREATE ON SCHEMA public FROM tenderflow_app" in script
