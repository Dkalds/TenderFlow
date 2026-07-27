"""Regression tests for the audit-chain runbook command."""

from __future__ import annotations

import runpy
from collections.abc import Callable
from pathlib import Path
from typing import cast


def _verify_chain_from_script() -> Callable[[Path], int]:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "verify_audit_chain.py"
    return cast(Callable[[Path], int], runpy.run_path(str(script_path))["verify_chain"])


def test_runbook_verifier_uses_signed_chain_validation(tmp_path, capsys) -> None:
    """The operational command detects a signed-head mismatch, not only hashes.

    ``verify_chain`` always operates on a local SQLite file by design (it
    overrides the active backend even in Postgres production, per its own
    docstring), so this test builds its own SQLite db directly instead of
    the shared ``tmp_db`` fixture — which points at Postgres when
    ``TEST_DATABASE_URL`` is set and would never create the file this test
    inspects.
    """
    import db.database as db_mod
    from db.audit import log_action

    db_path = tmp_path / "test.db"
    db_mod.close_pool()
    db_mod.set_db_path_override(str(db_path))
    db_mod.init_db()
    try:
        log_action("u", "s", "first")
        log_action("u", "s", "second")
        with db_mod.connect() as connection:
            connection.execute("DELETE FROM audit_log WHERE action = ?", ("second",))
    finally:
        db_mod.close_pool()
        db_mod.set_db_path_override(None)

    verify_chain = _verify_chain_from_script()
    assert verify_chain(db_path) == 1
    assert "MANIPULACIÓN" in capsys.readouterr().out
