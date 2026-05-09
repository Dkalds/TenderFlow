"""CRUD para la tabla ``users`` — gestión de usuarios OAuth y locales."""

from __future__ import annotations

from typing import Any

from db.database import connect, now_utc_iso


def get_or_create_oauth_user(
    *,
    email: str,
    oauth_provider: str,
    oauth_sub: str,
    display_name: str | None = None,
) -> int:
    """Busca un usuario por (oauth_provider, oauth_sub); si no existe lo crea.

    Returns:
        El ``id`` del usuario.
    """
    with connect() as c:
        row = c.execute(
            "SELECT id FROM users WHERE oauth_provider = ? AND oauth_sub = ?",
            (oauth_provider, oauth_sub),
        ).fetchone()
        if row:
            return int(row[0])

        # Si el email ya existe (usuario previo sin OAuth), vincular
        if email:
            row = c.execute(
                "SELECT id FROM users WHERE email = ?",
                (email,),
            ).fetchone()
            if row:
                c.execute(
                    "UPDATE users SET oauth_provider = ?, oauth_sub = ?, "
                    "display_name = COALESCE(?, display_name) WHERE id = ?",
                    (oauth_provider, oauth_sub, display_name, row[0]),
                )
                return int(row[0])

        cur = c.execute(
            "INSERT INTO users (email, oauth_provider, oauth_sub, display_name, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (email or None, oauth_provider, oauth_sub, display_name, now_utc_iso()),
        )
        return int(cur.lastrowid)  # type: ignore[arg-type]


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    """Devuelve un dict con los datos del usuario o None."""
    with connect() as c:
        cur = c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row, strict=False))


def get_user_by_email(email: str) -> dict[str, Any] | None:
    """Busca usuario por email."""
    with connect() as c:
        cur = c.execute("SELECT * FROM users WHERE email = ?", (email,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row, strict=False))


def is_admin(user_id: int) -> bool:
    """Devuelve True si el usuario tiene el flag is_admin activo."""
    with connect() as c:
        row = c.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
        return bool(row and row[0])


def log_access(
    *,
    auth_method: str,
    user_id: int | None = None,
    email: str | None = None,
) -> None:
    """Registra un inicio de sesión en ``access_log``."""
    with connect() as c:
        c.execute(
            "INSERT INTO access_log (user_id, email, auth_method, logged_in_at) "
            "VALUES (?, ?, ?, ?)",
            (user_id, email, auth_method, now_utc_iso()),
        )
