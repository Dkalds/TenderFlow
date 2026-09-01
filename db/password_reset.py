"""Persistencia transaccional de recuperación de contraseña."""

from __future__ import annotations

from db.database import connect


def create_reset_token_for_email(email: str, token_hash: str, expires_at: str) -> bool:
    """Emite un token para una cuenta local activa sin revelar si existe."""
    with connect() as connection:
        row = connection.execute(
            "SELECT id FROM users WHERE lower(email) = lower(%s) "
            "AND password_hash IS NOT NULL AND deactivated_at IS NULL",
            (email.strip(),),
        ).fetchone()
        if row is None:
            return False
        user_id = int(row[0])
        connection.execute(
            "UPDATE password_reset_tokens SET used_at = NOW() "
            "WHERE user_id = %s AND used_at IS NULL",
            (user_id,),
        )
        connection.execute(
            "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) "
            "VALUES (%s, %s, %s)",
            (user_id, token_hash, expires_at),
        )
    return True


def consume_reset_token(token_hash: str, password_hash: str) -> int | None:
    """Cambia la contraseña una vez y revoca todas las sesiones en la transacción."""
    with connect() as connection:
        row = connection.execute(
            "SELECT prt.id, prt.user_id FROM password_reset_tokens prt "
            "JOIN users u ON u.id = prt.user_id "
            "WHERE prt.token_hash = %s AND prt.used_at IS NULL "
            "AND prt.expires_at > NOW() AND u.deactivated_at IS NULL "
            "AND u.password_hash IS NOT NULL FOR UPDATE OF prt, u",
            (token_hash,),
        ).fetchone()
        if row is None:
            return None
        reset_id, user_id = int(row[0]), int(row[1])
        connection.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s",
            (password_hash, user_id),
        )
        connection.execute(
            "UPDATE password_reset_tokens SET used_at = NOW() WHERE id = %s",
            (reset_id,),
        )
        connection.execute(
            "UPDATE sessions SET revoked = 1, revoked_at = NOW() "
            "WHERE user_id = %s AND revoked = 0",
            (user_id,),
        )
    return user_id


def purge_password_reset_tokens() -> int:
    """Elimina tokens usados o expirados con más de siete días."""
    with connect() as connection:
        cursor = connection.execute(
            "DELETE FROM password_reset_tokens "
            "WHERE expires_at < NOW() - INTERVAL '7 days' "
            "OR used_at < NOW() - INTERVAL '7 days'"
        )
        return int(cursor.rowcount or 0)
