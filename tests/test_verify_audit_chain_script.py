"""Regression tests for the audit-chain runbook command."""

from __future__ import annotations

import runpy
from collections.abc import Callable
from pathlib import Path
from typing import cast


def _verify_chain_from_script() -> Callable[[], int]:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "verify_audit_chain.py"
    return cast(Callable[[], int], runpy.run_path(str(script_path))["verify_chain"])


def test_runbook_verifier_uses_signed_chain_validation(tmp_db, capsys) -> None:
    """The operational command detects a signed-head mismatch, not only hashes.

    Deleting the tail entry leaves every remaining row internally consistent,
    so a naive per-row hash check would pass. The signed header (final hash +
    row count) is what makes the deletion detectable.

    Since ADR-021 ``verify_chain`` takes no path: it verifies whatever
    ``DATABASE_URL`` points at, which here is the test's isolated Postgres
    schema.
    """
    db_mod, _ = tmp_db
    from db.audit import log_action

    log_action("u", "s", "first")
    log_action("u", "s", "second")
    with db_mod.connect() as connection:
        connection.execute("DELETE FROM audit_log WHERE action = ?", ("second",))

    verify_chain = _verify_chain_from_script()
    assert verify_chain() == 1
    assert "MANIPULACIÓN" in capsys.readouterr().out
