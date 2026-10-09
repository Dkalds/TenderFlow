"""Persistencia transaccional de recuperación de contraseña.

Las dos transacciones bloquean primero la fila del usuario y después tocan sus
tokens. Ese orden común es lo que serializa por cuenta la emisión y el consumo
sin que puedan esperarse la una a la otra en círculo.
"""

from __future__ import annotations

from db.database import connect, now_utc_iso


def create_reset_token_for_email(email: str, token_hash: str, expires_at: str) -> bool:
    """Emite un token para una cuenta local activa sin revelar si existe."""
    with connect() as connection:
        # `FOR UPDATE`: dos solicitudes simultáneas de la misma cuenta leían
        # ambas «sin pendientes» e insertaban cada una su token, y quedaban dos
        # vivos. Con la fila del usuario bloqueada, la segunda espera a la
        # primera y su `UPDATE` ya ve —e invalida— el token recién emitido.
        row = connection.execute(
            "SELECT id FROM users WHERE lower(email) = lower(%s) "
            "AND password_hash IS NOT NULL AND deactivated_at IS NULL FOR UPDATE",
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
    """Cambia la contraseña una vez; invalida los demás enlaces y revoca las sesiones.

    Todo en una transacción: o se cambia la contraseña, se gastan los tokens
    pendientes de la cuenta y caen sus sesiones, o no cambia nada.
    """
    with connect() as connection:
        # Primero la cuenta y después el token, en dos sentencias: el mismo
        # orden que sigue la emisión. Un solo `FOR UPDATE OF` sobre el JOIN
        # dejaría ese orden en manos de cómo recorra Postgres las tablas, que
        # no está documentado.
        owner = connection.execute(
            "SELECT u.id FROM users u WHERE u.id = "
            "(SELECT prt.user_id FROM password_reset_tokens prt WHERE prt.token_hash = %s) "
            "AND u.deactivated_at IS NULL AND u.password_hash IS NOT NULL FOR UPDATE",
            (token_hash,),
        ).fetchone()
        if owner is None:
            return None
        user_id = int(owner[0])
        # Con la cuenta ya bloqueada se mira el token: si otra confirmación o
        # una solicitud nueva lo gastó mientras esta esperaba, aquí ya se ve.
        token = connection.execute(
            "SELECT id FROM password_reset_tokens "
            "WHERE token_hash = %s AND user_id = %s "
            "AND used_at IS NULL AND expires_at > NOW() FOR UPDATE",
            (token_hash, user_id),
        ).fetchone()
        if token is None:
            return None
        connection.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s",
            (password_hash, user_id),
        )
        # Todos los pendientes de la cuenta, no solo el consumido: otro enlace
        # vivo seguiría valiendo hasta caducar y permitiría cambiar otra vez
        # una contraseña que su titular acaba de elegir.
        connection.execute(
            "UPDATE password_reset_tokens SET used_at = NOW() "
            "WHERE user_id = %s AND used_at IS NULL",
            (user_id,),
        )
        # `revoked_at` es TEXT: ISO 8601 desde Python, como en `db/sessions.py`.
        # Un `NOW()` de Postgres dejaba ahí otro formato («2026-10-09 12:00:00+00»).
        connection.execute(
            "UPDATE sessions SET revoked = 1, revoked_at = %s WHERE user_id = %s AND revoked = 0",
            (now_utc_iso(), user_id),
        )
    return user_id
