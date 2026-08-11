"""Tests para db.job_locks (ADR-012, ADR-022).

Verifica acquire/release/is_held con TTL y expiración.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from db.database import connect


@pytest.fixture(autouse=True)
def _tmp_db(tmp_db):
    """Schema Postgres aislado por test (incluye ``job_locks``)."""


class TestJobLockAcquire:
    def test_acquire_returns_true_on_first_call(self) -> None:
        from db.job_locks import acquire

        assert acquire("test_job", ttl_seconds=60) is True

    def test_acquire_returns_false_when_held(self) -> None:
        from db.job_locks import acquire

        assert acquire("test_job", ttl_seconds=60) is True
        assert acquire("test_job", ttl_seconds=60) is False

    def test_acquire_succeeds_after_expiry(self) -> None:
        from db.job_locks import acquire

        # Acquire with 0-second TTL (already expired by the time we check)
        past = datetime.now(UTC) - timedelta(seconds=10)
        with connect() as conn:
            conn.execute(
                "INSERT INTO job_locks (name, acquired_at, expires_at, holder) VALUES (%s, %s, %s, %s)",
                ("test_job", past.isoformat(), past.isoformat(), "old"),
            )

        # Should succeed because the lock expired
        assert acquire("test_job", ttl_seconds=60) is True

    def test_acquire_records_holder(self) -> None:
        from db.job_locks import acquire

        acquire("test_job", ttl_seconds=60, holder="scheduler:loop")
        with connect() as conn:
            row = conn.execute(
                "SELECT holder FROM job_locks WHERE name = %s", ("test_job",)
            ).fetchone()
        assert row[0] == "scheduler:loop"


class TestJobLockRelease:
    def test_release_clears_lock(self) -> None:
        from db.job_locks import acquire, is_held, release

        acquire("test_job", ttl_seconds=60)
        assert is_held("test_job") is True
        assert release("test_job") is True
        assert is_held("test_job") is False

    def test_release_nonexistent_returns_false(self) -> None:
        from db.job_locks import release

        assert release("nonexistent") is False

    def test_release_does_not_steal_lock_from_another_holder(self) -> None:
        """El escenario del que protege el módulo: A se pasa de TTL, B toma el
        lock legítimamente, y A al terminar NO debe borrar el lock de B."""
        from db.job_locks import acquire, is_held, release

        # A adquiere con TTL ya vencido y B se lo queda.
        assert acquire("slow_job", ttl_seconds=0, holder="worker_a") is True
        assert acquire("slow_job", ttl_seconds=600, holder="worker_b") is True

        # A termina y libera: el lock ya no es suyo, así que no se toca.
        assert release("slow_job", holder="worker_a") is False
        assert is_held("slow_job") is True

        # B sí puede liberarlo.
        assert release("slow_job", holder="worker_b") is True
        assert is_held("slow_job") is False

    def test_force_release_ignores_holder(self) -> None:
        from db.job_locks import acquire, force_release, is_held

        acquire("stuck_job", ttl_seconds=3600, holder="dead_process")
        assert force_release("stuck_job") is True
        assert is_held("stuck_job") is False


class TestJobLockRenew:
    def test_renew_extends_ttl_for_owner(self) -> None:
        from db.job_locks import acquire, is_held, renew

        assert acquire("long_job", ttl_seconds=0, holder="worker_a") is True
        assert is_held("long_job") is False  # ya expirado

        assert renew("long_job", holder="worker_a", ttl_seconds=600) is True
        assert is_held("long_job") is True

    def test_renew_returns_false_when_lock_was_taken(self) -> None:
        from db.job_locks import acquire, renew

        acquire("long_job", ttl_seconds=0, holder="worker_a")
        acquire("long_job", ttl_seconds=600, holder="worker_b")

        assert renew("long_job", holder="worker_a", ttl_seconds=600) is False


class TestJobLockIsHeld:
    def test_is_held_false_when_no_lock(self) -> None:
        from db.job_locks import is_held

        assert is_held("test_job") is False

    def test_is_held_true_when_locked(self) -> None:
        from db.job_locks import acquire, is_held

        acquire("test_job", ttl_seconds=60)
        assert is_held("test_job") is True


class TestGetAllLocks:
    def test_returns_only_active_locks(self) -> None:
        from db.job_locks import acquire, get_all_locks

        acquire("active_job", ttl_seconds=3600)

        # Insert an expired lock
        past = datetime.now(UTC) - timedelta(seconds=10)
        with connect() as conn:
            conn.execute(
                "INSERT INTO job_locks (name, acquired_at, expires_at, holder) VALUES (%s, %s, %s, %s)",
                ("expired_job", past.isoformat(), past.isoformat(), "old"),
            )

        locks = get_all_locks()
        names = [lock["name"] for lock in locks]
        assert "active_job" in names
        assert "expired_job" not in names


class TestDoubleAcquireSafety:
    """ADR-012: doble acquire del mismo name dentro del TTL → segundo es no-op."""

    def test_double_acquire_within_ttl_is_noop(self) -> None:
        from db.job_locks import acquire

        assert acquire("retention_cleanup", ttl_seconds=600, holder="plane_a") is True
        assert acquire("retention_cleanup", ttl_seconds=600, holder="plane_b") is False
