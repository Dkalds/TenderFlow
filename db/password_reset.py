"""Persistencia transaccional de recuperación y cambio de contraseña.

Las transacciones bloquean primero la fila del usuario y después tocan sus
tokens. Ese orden común es lo que serializa por cuenta la emisión, el consumo y
el cambio sin que puedan esperarse la una a la otra en círculo.

Cambiar la contraseña —por el enlace del correo o desde Ajustes— revoca en la
misma transacción las credenciales que quien tuviera la cuenta pudo dejarse:
sesiones y claves de API (:func:`_revocar_credenciales`).
"""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.sessions import _hash_token


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


def create_reset_token_for_user(user_id: int, token_hash: str, expires_at: str) -> bool:
    """Emite un token para una cuenta activa **tenga o no contraseña**.

    No lo usa ``POST /auth/password-reset/request``, que sigue limitado a
    cuentas locales: lo usa el alta cerrada cuando el correo ya tiene una cuenta
    verificada (``services/email_verification.py``). Ahí el enlace llega al
    buzón que la persona acaba de escribir, y para quien entró solo por Google
    es la forma de ponerse su primera contraseña sin que el endpoint público
    revele qué cuentas no tienen una.

    **No gasta los enlaces pendientes.** Lo dispara un anónimo con solo repetir
    el alta con ese correo, así que gastarlos le permitía matar el enlace que el
    titular acababa de pedir. Los dos viven hasta caducar o hasta que uno se
    canjee, que gasta todos (:func:`consume_reset_token`); el tope por correo
    del alta acota cuántos puede haber.
    """
    with connect() as connection:
        row = connection.execute(
            "SELECT id FROM users WHERE id = %s AND deactivated_at IS NULL FOR UPDATE",
            (user_id,),
        ).fetchone()
        if row is None:
            return False
        connection.execute(
            "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) "
            "VALUES (%s, %s, %s)",
            (user_id, token_hash, expires_at),
        )
    return True


def reset_token_vigente(token_hash: str) -> bool:
    """¿Hay un enlace de recuperación sin gastar ni caducar con este hash?

    Lectura sin bloqueos, para que ``POST /auth/password-reset/confirm`` no
    calcule un argon2 de 64 MiB por un token que no existe. No sustituye a
    :func:`consume_reset_token`, que vuelve a comprobarlo dentro de su
    transacción: entre las dos puede gastarlo otra petición.
    """
    with connect_read() as connection:
        fila = connection.execute(
            "SELECT 1 FROM password_reset_tokens prt JOIN users u ON u.id = prt.user_id "
            "WHERE prt.token_hash = %s AND prt.used_at IS NULL AND prt.expires_at > NOW() "
            "AND u.deactivated_at IS NULL",
            (token_hash,),
        ).fetchone()
    return fila is not None


def consume_reset_token(token_hash: str, password_hash: str) -> int | None:
    """Cambia la contraseña una vez; invalida los demás enlaces y revoca las sesiones.

    No exige que la cuenta ya tenga contraseña: los tokens de una cuenta sin
    ella solo los emite :func:`create_reset_token_for_user`, y consumirlo le
    pone la primera.

    Todo en una transacción: o se cambia la contraseña, se gastan los tokens
    pendientes de la cuenta y caen sus sesiones y sus claves de API, o no
    cambia nada. Las claves caen desde 2026-10: una creada por quien tuviera la
    cuenta seguía valiendo después de que el titular la recuperase.
    """
    with connect() as connection:
        # Primero la cuenta y después el token, en dos sentencias: el mismo
        # orden que sigue la emisión. Un solo `FOR UPDATE OF` sobre el JOIN
        # dejaría ese orden en manos de cómo recorra Postgres las tablas, que
        # no está documentado.
        owner = connection.execute(
            "SELECT u.id FROM users u WHERE u.id = "
            "(SELECT prt.user_id FROM password_reset_tokens prt WHERE prt.token_hash = %s) "
            "AND u.deactivated_at IS NULL FOR UPDATE",
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
        # Consumir el enlace demuestra el buzón: una cuenta del alta cerrada que
        # aún no verificó queda verificada.
        connection.execute(
            "UPDATE users SET password_hash = %s, "
            "email_verified_at = COALESCE(email_verified_at, NOW()) WHERE id = %s",
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
        _revocar_credenciales(connection, user_id)
    return user_id


def change_password(user_id: int, password_hash: str, *, sesion_actual: str) -> int | None:
    """Cambia la contraseña de una cuenta activa y revoca lo demás en una transacción.

    Para ``POST /auth/password/change``, que ya comprobó la contraseña actual.
    Revoca todas las sesiones **menos** ``sesion_actual`` (el token de la que
    hace el cambio: quien cambia su contraseña no tiene por qué volver a
    entrar) y todas las claves de API. Gasta además los enlaces de
    recuperación pendientes: uno pedido antes del cambio permitiría deshacerlo.

    Devuelve cuántas claves de API se desactivaron, o ``None`` si la cuenta ya
    no está activa.
    """
    with connect() as connection:
        fila = connection.execute(
            "SELECT id FROM users WHERE id = %s AND deactivated_at IS NULL FOR UPDATE",
            (user_id,),
        ).fetchone()
        if fila is None:
            return None
        connection.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s",
            (password_hash, user_id),
        )
        connection.execute(
            "UPDATE password_reset_tokens SET used_at = NOW() "
            "WHERE user_id = %s AND used_at IS NULL",
            (user_id,),
        )
        # El mismo hash con el que `db/sessions.py` guarda la sesión: el token
        # en claro no se compara contra la tabla.
        return _revocar_credenciales(connection, user_id, salvo_sesion=_hash_token(sesion_actual))


def _revocar_credenciales(connection: Any, user_id: int, *, salvo_sesion: str | None = None) -> int:
    """Revoca las sesiones (salvo la de hash ``salvo_sesion``) y las claves de API.

    Dentro de la transacción de quien la llama, y sin tragarse errores: si algo
    falla, la contraseña tampoco cambia. Por eso no usa
    ``ApiKeyRepository.deactivate_all_for_user``, que abre su propia conexión y
    devuelve 0 ante cualquier fallo — en el camino del RGPD es aceptable, aquí
    dejaría vivas las claves de quien tuviera la cuenta mientras el titular
    cree que la ha recuperado.

    Las claves que se desactivan son las del ``user_id``: las personales. Las
    de organización no tienen dueño individual (ADR-030 §D).

    Devuelve cuántas claves activas se desactivaron.
    """
    # `revoked_at` es TEXT: ISO 8601 desde Python, como en `db/sessions.py`.
    # Un `NOW()` de Postgres dejaba ahí otro formato («2026-10-09 12:00:00+00»).
    ahora = now_utc_iso()
    if salvo_sesion is None:
        connection.execute(
            "UPDATE sessions SET revoked = 1, revoked_at = %s WHERE user_id = %s AND revoked = 0",
            (ahora, user_id),
        )
    else:
        connection.execute(
            "UPDATE sessions SET revoked = 1, revoked_at = %s "
            "WHERE user_id = %s AND revoked = 0 AND token_hash <> %s",
            (ahora, user_id, salvo_sesion),
        )
    cursor = connection.execute(
        "UPDATE api_keys SET is_active = 0 WHERE user_id = %s AND is_active = 1",
        (user_id,),
    )
    return int(cursor.rowcount or 0)
