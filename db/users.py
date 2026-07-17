"""CRUD para la tabla ``users`` — gestión de usuarios OAuth y locales."""

from __future__ import annotations

from typing import Any

from db.database import connect, is_postgres_backend, now_utc_iso


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

        if is_postgres_backend():
            cur = c.execute(
                "INSERT INTO users (email, oauth_provider, oauth_sub, display_name, created_at) "
                "VALUES (?, ?, ?, ?, ?) RETURNING id",
                (email or None, oauth_provider, oauth_sub, display_name, now_utc_iso()),
            )
            return int(cur.fetchone()[0])
        cur = c.execute(
            "INSERT INTO users (email, oauth_provider, oauth_sub, display_name, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (email or None, oauth_provider, oauth_sub, display_name, now_utc_iso()),
        )
        return int(cur.lastrowid)


def create_user(
    *,
    email: str,
    password_hash: str,
    display_name: str | None = None,
) -> int:
    """Crea un usuario local (email + password) y devuelve su ``id``.

    Pensado para el alta self-service (``POST /auth/register``). El ``email``
    tiene constraint ``UNIQUE``: si ya existe, SQLite lanza ``IntegrityError``.
    Para un error limpio (409), el caller debe verificar antes con
    :func:`get_user_by_email`.
    """
    with connect() as c:
        if is_postgres_backend():
            cur = c.execute(
                "INSERT INTO users (email, password_hash, display_name, created_at) "
                "VALUES (?, ?, ?, ?) RETURNING id",
                (email, password_hash, display_name, now_utc_iso()),
            )
            return int(cur.fetchone()[0])
        cur = c.execute(
            "INSERT INTO users (email, password_hash, display_name, created_at) "
            "VALUES (?, ?, ?, ?)",
            (email, password_hash, display_name, now_utc_iso()),
        )
        return int(cur.lastrowid)


def get_user_by_id(user_id: int, *, include_deactivated: bool = False) -> dict[str, Any] | None:
    """Devuelve un dict con los datos del usuario o None."""
    with connect() as c:
        sql = "SELECT * FROM users WHERE id = ?"
        if not include_deactivated:
            sql += " AND deactivated_at IS NULL"
        cur = c.execute(sql, (user_id,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row, strict=False))


def get_user_by_email(email: str, *, include_deactivated: bool = False) -> dict[str, Any] | None:
    """Busca usuario por email."""
    with connect() as c:
        sql = "SELECT * FROM users WHERE email = ?"
        if not include_deactivated:
            sql += " AND deactivated_at IS NULL"
        cur = c.execute(sql, (email,))
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


def set_admin(user_id: int, is_admin_value: bool) -> None:
    """Actualiza el flag ``is_admin`` de un usuario."""
    with connect() as c:
        c.execute(
            "UPDATE users SET is_admin = ? WHERE id = ?",
            (1 if is_admin_value else 0, user_id),
        )


def set_admin_by_email(email: str, *, is_admin: bool) -> None:
    """Promueve o degrada un usuario por email."""
    with connect() as c:
        c.execute(
            "UPDATE users SET is_admin = ? WHERE email = ?",
            (1 if is_admin else 0, email),
        )


def list_users(limit: int = 200, *, include_deactivated: bool = False) -> list[dict[str, Any]]:
    """Devuelve todos los usuarios registrados con su último acceso."""
    with connect() as c:
        where = "" if include_deactivated else "WHERE u.deactivated_at IS NULL "
        cur = c.execute(
            "SELECT u.id, u.email, u.display_name, u.oauth_provider, u.is_admin, "
            "       u.created_at, u.deactivated_at, "
            "       MAX(a.logged_in_at) AS last_access "
            "FROM users u "
            "LEFT JOIN access_log a ON a.user_id = u.id "
            f"{where}"
            "GROUP BY u.id "
            "ORDER BY last_access DESC NULLS LAST "
            "LIMIT ?",
            (limit,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def deactivate_user(user_id: int) -> None:
    """Soft-delete: marca deactivated_at sin borrar datos ni audit trail."""
    with connect() as c:
        c.execute(
            "UPDATE users SET deactivated_at = ? WHERE id = ? AND deactivated_at IS NULL",
            (now_utc_iso(), user_id),
        )


def reactivate_user(user_id: int) -> None:
    """Revierte un soft-delete (operación administrativa)."""
    with connect() as c:
        c.execute(
            "UPDATE users SET deactivated_at = NULL WHERE id = ?",
            (user_id,),
        )


def anonymize_user(user_id: int) -> None:
    """Anonimiza PII del usuario (GDPR Art.17 erasure).

    - Desactiva la cuenta si no lo estaba.
    - Nullifica email, display_name, oauth_sub en users.
    - Nullifica email en access_log.
    - Conserva el esqueleto de auditoría (user_id, auth_method, logged_in_at).
    """
    with connect() as c:
        c.execute(
            "UPDATE users SET email = NULL, display_name = NULL, oauth_sub = NULL, "
            "deactivated_at = COALESCE(deactivated_at, ?) WHERE id = ?",
            (now_utc_iso(), user_id),
        )
        c.execute(
            "UPDATE access_log SET email = NULL WHERE user_id = ?",
            (user_id,),
        )


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
