"""Feature flags helpers — CRUD sobre tabla ``feature_flags``.

La tabla ya está en el SCHEMA de db/database.py:

    feature_flags(id, name UNIQUE, enabled, rollout_pct, user_emails,
                  description, updated_at)

Uso:
    from db.feature_flags import is_enabled, set_flag

    if is_enabled("nueva_comparacion", user_email="user@example.com"):
        ...
"""

from __future__ import annotations

from typing import Any

from db.database import connect, now_utc_iso
from observability.logging import get_logger

log = get_logger(__name__)


def is_enabled(name: str, user_email: str | None = None) -> bool:
    """Devuelve True si el flag está activo para el usuario/porcentaje dado.

    Lógica de resolución:
    1. Si el flag no existe → False.
    2. Si ``enabled=0`` → False siempre.
    3. Si ``user_emails`` no está vacío y el email está en la lista → True.
    4. Si ``rollout_pct == 100`` → True.
    5. Si ``rollout_pct > 0``: determinista basado en hash(name+email) % 100.
    6. En otro caso → False.
    """
    row = _get_flag_row(name)
    if row is None:
        return False
    if not row["enabled"]:
        return False

    # Explicit user allowlist
    user_emails_raw = row.get("user_emails") or ""
    if user_email and user_emails_raw:
        allowed = [e.strip().lower() for e in user_emails_raw.split(",") if e.strip()]
        if user_email.lower() in allowed:
            return True

    pct = int(row.get("rollout_pct") or 0)
    if pct >= 100:
        return True
    if pct > 0 and user_email:
        import hashlib

        digest = int(hashlib.sha256(f"{name}:{user_email}".encode()).hexdigest(), 16)
        return (digest % 100) < pct

    return pct >= 100


def get_flag(name: str) -> dict[str, Any] | None:
    """Devuelve el dict del flag o None si no existe."""
    return _get_flag_row(name)


def set_flag(
    name: str,
    *,
    enabled: bool = True,
    rollout_pct: int = 100,
    user_emails: str = "",
    description: str = "",
) -> None:
    """Crea o actualiza un flag."""
    with connect() as c:
        c.execute(
            "INSERT INTO feature_flags (name, enabled, rollout_pct, user_emails, description, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT(name) DO UPDATE SET "
            "enabled=excluded.enabled, rollout_pct=excluded.rollout_pct, "
            "user_emails=excluded.user_emails, description=excluded.description, "
            "updated_at=excluded.updated_at",
            (name, int(enabled), rollout_pct, user_emails, description, now_utc_iso()),
        )
    log.info("feature_flag.set", name=name, enabled=enabled, rollout_pct=rollout_pct)


def delete_flag(name: str) -> bool:
    """Elimina un flag. Devuelve True si existía."""
    with connect() as c:
        cur = c.execute("DELETE FROM feature_flags WHERE name=%s", (name,))
        return (cur.rowcount or 0) > 0


def list_flags() -> list[dict[str, Any]]:
    """Lista todos los flags con sus metadatos."""
    with connect() as c:
        cur = c.execute(
            "SELECT id, name, enabled, rollout_pct, user_emails, description, updated_at "
            "FROM feature_flags ORDER BY name"
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


# ── Internal ──────────────────────────────────────────────────────────────────


def _get_flag_row(name: str) -> dict[str, Any] | None:
    with connect() as c:
        cur = c.execute(
            "SELECT id, name, enabled, rollout_pct, user_emails, description, updated_at "
            "FROM feature_flags WHERE name=%s",
            (name,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row, strict=False))
