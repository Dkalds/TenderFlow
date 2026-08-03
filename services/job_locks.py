"""Job lock service — lightweight mutual exclusion for non-idempotent jobs (ADR-012).

Provides ``acquire`` / ``release`` / ``is_held`` backed by the ``job_locks``
table in Postgres. A lock has a TTL (``expires_at``); expired locks are
transparently replaced on the next ``acquire`` call.

Usage::

    from services.job_locks import acquire, release

    if acquire("retention_cleanup", ttl_seconds=600, holder="scheduler:loop"):
        try:
            do_retention()
        finally:
            release("retention_cleanup")
    else:
        log.info("retention_cleanup already locked, skipping")
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from db.database import connect
from observability.logging import get_logger

log = get_logger(__name__)


def acquire(name: str, ttl_seconds: int = 600, holder: str = "") -> bool:
    """Try to acquire a named lock with the given TTL.

    Returns True if the lock was acquired, False if it's already held by
    another holder and has not expired.

    Un solo statement atómico (``INSERT … ON CONFLICT DO UPDATE … WHERE``):
    hasta 2026-08 era un SELECT seguido de INSERT/UPDATE sin bloqueo, y dos
    procesos arrancando a la vez (p. ej. los dos workflows de scrape que
    coincidían a las 06:00 UTC) podían adquirir el mismo lock — exactamente el
    escenario del que este módulo debe proteger. ``ON CONFLICT`` toma el row
    lock del conflicto, y el ``WHERE`` solo cede el lock si el existente ya
    expiró; ``rowcount`` distingue adquirido (1) de rechazado (0).
    """
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=ttl_seconds)
    now_iso = now.isoformat()
    expires_iso = expires_at.isoformat()

    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO job_locks (name, acquired_at, expires_at, holder) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT (name) DO UPDATE SET "
            "acquired_at = excluded.acquired_at, "
            "expires_at = excluded.expires_at, "
            "holder = excluded.holder "
            "WHERE job_locks.expires_at <= ?",
            (name, now_iso, expires_iso, holder, now_iso),
        )
        acquired = cursor.rowcount > 0

    if not acquired:
        log.debug("job_lock_already_held", name=name)
        return False

    log.info("job_lock_acquired", name=name, holder=holder, ttl_seconds=ttl_seconds)
    return True


def release(name: str) -> bool:
    """Release a named lock. Returns True if the lock existed and was deleted."""
    with connect() as conn:
        cursor = conn.execute("DELETE FROM job_locks WHERE name = ?", (name,))
        deleted: bool = cursor.rowcount > 0

    if deleted:
        log.info("job_lock_released", name=name)
    return deleted


def is_held(name: str) -> bool:
    """Check if a named lock is currently held (not expired)."""
    now_iso = datetime.now(UTC).isoformat()
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM job_locks WHERE name = ? AND expires_at > ?",
            (name, now_iso),
        ).fetchone()
    return row is not None


def get_all_locks() -> list[dict[str, Any]]:
    """Return all current (non-expired) locks for diagnostics."""
    now_iso = datetime.now(UTC).isoformat()
    with connect() as conn:
        rows = conn.execute(
            "SELECT name, acquired_at, expires_at, holder "
            "FROM job_locks WHERE expires_at > ? ORDER BY acquired_at",
            (now_iso,),
        ).fetchall()
    return [
        {
            "name": r[0],
            "acquired_at": r[1],
            "expires_at": r[2],
            "holder": r[3],
        }
        for r in rows
    ]
