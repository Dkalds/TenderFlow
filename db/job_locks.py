"""Locks de exclusión mutua para jobs no idempotentes (ADR-012, ADR-022).

Respaldados por la tabla ``job_locks``. Un lock tiene TTL (``expires_at``); los
expirados se reemplazan de forma transparente en el siguiente ``acquire``.

**El holder es parte de la identidad del lock.** ``release`` solo borra el lock
si sigue siendo del holder que lo tomó: hasta 2026-08 borraba por nombre, así
que un job que se pasaba de su TTL —momento en el que otro proceso adquiere el
lock legítimamente— al terminar borraba el lock ajeno y habilitaba una tercera
ejecución simultánea. Es exactamente el escenario del que este módulo protege.
Para jobs que puedan exceder su ventana, ``renew`` extiende el TTL sin soltarlo.

Uso::

    from db.job_locks import acquire, release

    if acquire("retention_cleanup", ttl_seconds=600, holder="scheduler:loop"):
        try:
            do_retention()
        finally:
            release("retention_cleanup", holder="scheduler:loop")
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
    """Intenta adquirir un lock con nombre y TTL.

    Devuelve True si se adquirió, False si otro holder lo tiene y no ha expirado.

    Un solo statement atómico (``INSERT … ON CONFLICT DO UPDATE … WHERE``):
    hasta 2026-08 era un SELECT seguido de INSERT/UPDATE sin bloqueo, y dos
    procesos arrancando a la vez (p. ej. los dos workflows de scrape que
    coincidían a las 06:00 UTC) podían adquirir el mismo lock. ``ON CONFLICT``
    toma el row lock del conflicto, y el ``WHERE`` solo cede el lock si el
    existente ya expiró; ``rowcount`` distingue adquirido (1) de rechazado (0).
    """
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=ttl_seconds)
    now_iso = now.isoformat()
    expires_iso = expires_at.isoformat()

    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO job_locks (name, acquired_at, expires_at, holder) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (name) DO UPDATE SET "
            "acquired_at = excluded.acquired_at, "
            "expires_at = excluded.expires_at, "
            "holder = excluded.holder "
            "WHERE job_locks.expires_at <= %s",
            (name, now_iso, expires_iso, holder, now_iso),
        )
        acquired = cursor.rowcount > 0

    if not acquired:
        log.debug("job_lock_already_held", name=name)
        return False

    log.info("job_lock_acquired", name=name, holder=holder, ttl_seconds=ttl_seconds)
    return True


def release(name: str, holder: str = "") -> bool:
    """Libera el lock **solo si sigue siendo de ``holder``**.

    Devuelve True si se borró. False significa que el lock ya no era nuestro
    (expiró y lo tomó otro proceso) o que ya no existía: en el primer caso
    borrarlo habría dejado correr a un tercero en paralelo.
    """
    with connect() as conn:
        cursor = conn.execute(
            "DELETE FROM job_locks WHERE name = %s AND holder = %s",
            (name, holder),
        )
        deleted: bool = cursor.rowcount > 0

    if deleted:
        log.info("job_lock_released", name=name, holder=holder)
    else:
        log.debug("job_lock_release_noop", name=name, holder=holder)
    return deleted


def force_release(name: str) -> bool:
    """Borra el lock ignorando el holder. Solo para intervención manual.

    Los runbooks de operación lo necesitan cuando un proceso muere sin liberar
    y su TTL es largo. El código de jobs debe usar ``release``.
    """
    with connect() as conn:
        cursor = conn.execute("DELETE FROM job_locks WHERE name = %s", (name,))
        deleted: bool = cursor.rowcount > 0

    if deleted:
        log.warning("job_lock_force_released", name=name)
    return deleted


def renew(name: str, holder: str = "", ttl_seconds: int = 600) -> bool:
    """Extiende el TTL de un lock que seguimos teniendo (heartbeat).

    Devuelve False si el lock ya no es nuestro — señal de que otro proceso lo
    tomó y esta ejecución debería abortar en vez de seguir escribiendo.
    """
    now = datetime.now(UTC)
    expires_iso = (now + timedelta(seconds=ttl_seconds)).isoformat()

    with connect() as conn:
        cursor = conn.execute(
            "UPDATE job_locks SET expires_at = %s WHERE name = %s AND holder = %s",
            (expires_iso, name, holder),
        )
        renewed: bool = cursor.rowcount > 0

    if renewed:
        log.debug("job_lock_renewed", name=name, holder=holder, ttl_seconds=ttl_seconds)
    else:
        log.warning("job_lock_renew_lost", name=name, holder=holder)
    return renewed


def is_held(name: str) -> bool:
    """True si el lock está tomado y no ha expirado."""
    now_iso = datetime.now(UTC).isoformat()
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM job_locks WHERE name = %s AND expires_at > %s",
            (name, now_iso),
        ).fetchone()
    return row is not None


def get_all_locks() -> list[dict[str, Any]]:
    """Devuelve todos los locks vigentes (no expirados), para diagnóstico."""
    now_iso = datetime.now(UTC).isoformat()
    with connect() as conn:
        rows = conn.execute(
            "SELECT name, acquired_at, expires_at, holder "
            "FROM job_locks WHERE expires_at > %s ORDER BY acquired_at",
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
