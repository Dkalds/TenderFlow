"""Regression tests for the audit-chain runbook command."""

from __future__ import annotations

import runpy
from collections.abc import Callable
from pathlib import Path
from typing import cast


def _verify_chain_from_script() -> Callable[[Path], int]:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "verify_audit_chain.py"
    return cast(Callable[[Path], int], runpy.run_path(str(script_path))["verify_chain"])


def test_runbook_verifier_uses_signed_chain_validation(tmp_db, capsys) -> None:
    """The operational command detects a signed-head mismatch, not only hashes."""
    db_mod, tmp_path = tmp_db
    from db.audit import log_action

    log_action("u", "s", "first")
    log_action("u", "s", "second")
    with db_mod.connect() as connection:
        connection.execute("DELETE FROM audit_log WHERE action = ?", ("second",))
    db_mod.close_pool()

    verify_chain = _verify_chain_from_script()
    assert verify_chain(tmp_path / "test.db") == 1
    assert "MANIPULACIÓN" in capsys.readouterr().out
