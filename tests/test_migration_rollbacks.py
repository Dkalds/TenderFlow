"""Rollback tests for db.migrations.

For each reversible version: apply all migrations → rollback to (v-1) →
verify the objects created by that version are gone and the version record
is removed from schema_version.
"""

from __future__ import annotations

import sqlite3

import pytest

from db.migrations import (
    _IRREVERSIBLE_VERSIONS,
    ROLLBACKS,
    apply_pending,
    current_version,
    rollback,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_conn() -> sqlite3.Connection:
    return sqlite3.connect(":memory:")


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }


def _indexes(conn: sqlite3.Connection) -> set[str]:
    return {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
    }


def _versions_in_schema(conn: sqlite3.Connection) -> set[int]:
    return {r[0] for r in conn.execute("SELECT version FROM schema_version").fetchall()}


# ---------------------------------------------------------------------------
# Basic mechanics
# ---------------------------------------------------------------------------


class TestRollbackMechanics:
    def test_raises_when_target_equals_current(self):
        conn = _fresh_conn()
        apply_pending(conn)
        cv = current_version(conn)
        with pytest.raises(RuntimeError):
            rollback(cv, conn)

    def test_raises_when_target_above_current(self):
        conn = _fresh_conn()
        apply_pending(conn)
        cv = current_version(conn)
        with pytest.raises(RuntimeError):
            rollback(cv + 5, conn)

    def test_returns_list_of_reverted_versions(self):
        conn = _fresh_conn()
        apply_pending(conn)
        reverted = rollback(12, conn)  # rolls back all reversible versions > 12
        # v14, v15 are irreversible → only v17, v16, v13 get rolled back
        assert reverted == [17, 16, 13]

    def test_removes_version_record_from_schema_version(self):
        conn = _fresh_conn()
        apply_pending(conn)
        rollback(12, conn)
        assert 13 not in _versions_in_schema(conn)

    def test_irreversible_versions_remain_in_schema_version_after_full_rollback(self):
        """Versions 3, 4, 6, 10 have no rollback SQL and must stay recorded."""
        conn = _fresh_conn()
        apply_pending(conn)
        rollback(0, conn)
        remaining = _versions_in_schema(conn)
        assert _IRREVERSIBLE_VERSIONS.issubset(remaining)

    def test_reversible_versions_all_removed_after_full_rollback(self):
        conn = _fresh_conn()
        apply_pending(conn)
        rollback(0, conn)
        remaining = _versions_in_schema(conn)
        for v in ROLLBACKS:
            assert v not in remaining


# ---------------------------------------------------------------------------
# Per-version: schema objects removed after rollback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "target, absent_tables, absent_indexes",
    [
        # v13 → kpi_snapshots
        (12, ["kpi_snapshots"], ["idx_kpi_snapshots_fecha"]),
        # v12 → rate_limits
        (11, ["rate_limits"], ["idx_rate_limits_expires"]),
        # v9 → access_log (v12, v13 also rolled back but that's fine)
        (8, ["access_log"], ["idx_access_log_user", "idx_access_log_time"]),
        # v8 → users (v9+ also rolled back)
        (7, ["users"], ["idx_users_email", "idx_users_oauth"]),
        # v5 → ingestion_cursors + licitaciones_history (v7+ also rolled back)
        (4, ["ingestion_cursors", "licitaciones_history"], ["idx_hist_externo"]),
        # v2 → watchlist_cpv (v5+ also rolled back)
        (1, ["watchlist_cpv"], ["idx_wl_user"]),
        # v1 → extraction_runs + failed_extractions (full rollback)
        (0, ["extraction_runs", "failed_extractions"], ["idx_runs_started", "idx_runs_status"]),
    ],
)
def test_rollback_removes_schema_objects(
    target: int,
    absent_tables: list[str],
    absent_indexes: list[str],
) -> None:
    conn = _fresh_conn()
    apply_pending(conn)
    rollback(target, conn)

    tables = _tables(conn)
    indexes = _indexes(conn)

    for table in absent_tables:
        assert table not in tables, (
            f"Table '{table}' should be absent after rollback(target={target})"
        )
    for idx in absent_indexes:
        assert idx not in indexes, f"Index '{idx}' should be absent after rollback(target={target})"


def test_rollback_v11_removes_only_dedup_index() -> None:
    """v11 creates only an index (no table). Verify the index is removed but
    failed_extractions (from v1) survives."""
    conn = _fresh_conn()
    apply_pending(conn)

    assert "idx_fail_unique_unresolved" in _indexes(conn)

    rollback(10, conn)

    assert "idx_fail_unique_unresolved" not in _indexes(conn)
    assert "failed_extractions" in _tables(conn)  # v1 table untouched


def test_rollback_v7_succeeds_even_without_fts_table() -> None:
    """In a memory test DB, licitaciones doesn't exist so FTS is never built.
    Rollback past v7 must succeed via DROP IF EXISTS without raising."""
    conn = _fresh_conn()
    apply_pending(conn)

    assert "licitaciones_fts" not in _tables(conn)

    rollback(6, conn)

    assert 7 not in _versions_in_schema(conn)


# ---------------------------------------------------------------------------
# Boundary: partial rollback does not disturb lower versions
# ---------------------------------------------------------------------------


def test_partial_rollback_leaves_lower_versions_intact() -> None:
    """Rolling back only v13 must not touch v12 and below."""
    conn = _fresh_conn()
    apply_pending(conn)

    rollback(12, conn)

    assert "rate_limits" in _tables(conn)  # v12 still present
    assert 12 in _versions_in_schema(conn)  # record still in schema_version
    assert 13 not in _versions_in_schema(conn)


def test_full_rollback_removes_all_reversible_tables() -> None:
    """After rollback(0), no table from a reversible migration should remain."""
    conn = _fresh_conn()
    apply_pending(conn)
    rollback(0, conn)

    tables = _tables(conn)
    for table in (
        "extraction_runs",  # v1
        "failed_extractions",  # v1
        "watchlist_cpv",  # v2
        "ingestion_cursors",  # v5
        "licitaciones_history",  # v5
        "users",  # v8
        "access_log",  # v9
        "rate_limits",  # v12
        "kpi_snapshots",  # v13
    ):
        assert table not in tables, f"Table '{table}' should be gone after full rollback"


# ---------------------------------------------------------------------------
# Verify schema objects exist BEFORE rollback (sanity checks)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "table",
    [
        "extraction_runs",
        "failed_extractions",
        "watchlist_cpv",
        "ingestion_cursors",
        "licitaciones_history",
        "users",
        "access_log",
        "rate_limits",
        "kpi_snapshots",
    ],
)
def test_table_exists_after_full_apply(table: str) -> None:
    """Sanity: after apply_pending, all expected tables must be present."""
    conn = _fresh_conn()
    apply_pending(conn)
    assert table in _tables(conn)
