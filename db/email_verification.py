"""Persistencia del alta con verificación de correo (RFC 2026-10-21).

El alta cerrada crea la cuenta **sin verificar** y emite un token; la cuenta no
entra con contraseña hasta que alguien pulsa el enlace que llega a ese buzón.

Mismo orden de bloqueo que ``db/password_reset.py``: primero la fila del
usuario, después sus tokens. Es lo que serializa por cuenta el alta, el
reenvío y el consumo sin que puedan esperarse en círculo.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Literal, TypeAlias

from psycopg import Connection

from db.database import connect, now_utc, now_utc_iso

#: Las filas de ``connect()``: tuplas, como en el resto de ``db/``.
_Conexion: TypeAlias = Connection[tuple[object, ...]]

#: Qué encontró el alta para ese correo.
#:
#: - ``created``: no había cuenta; se creó sin verificar y hay token nuevo.
#: - ``replaced``: había una sin verificar; se le puso la contraseña nueva y el
#:   token anterior dejó de valer. Gana quien controla el buzón.
#: - ``verified``: la cuenta ya está verificada; no se tocó nada.
#: - ``deactivated``: la cuenta está desactivada; no se tocó nada ni se escribe.
EstadoAlta = Literal["created", "replaced", "verified", "deactivated"]


def _cuenta_por_correo(connection: _Conexion, email: str) -> tuple[object, ...] | None:
    return connection.execute(
        "SELECT id, email_verified_at, deactivated_at FROM users "
        "WHERE lower(email) = lower(%s) ORDER BY id LIMIT 1 FOR UPDATE",
        (email,),
    ).fetchone()


def _emitir_token(connection: _Conexion, user_id: int, token_hash: str, expires_at: str) -> None:
    """Gasta los tokens pendientes de la cuenta y deja vivo solo el nuevo."""
    connection.execute(
        "UPDATE email_verification_tokens SET used_at = NOW() "
        "WHERE user_id = %s AND used_at IS NULL",
        (user_id,),
    )
    connection.execute(
        "INSERT INTO email_verification_tokens (user_id, token_hash, expires_at) "
        "VALUES (%s, %s, %s)",
        (user_id, token_hash, expires_at),
    )


def register_unverified(
    *,
    email: str,
    password_hash: str,
    display_name: str | None,
    token_hash: str,
    expires_at: str,
) -> tuple[EstadoAlta, int | None]:
    """Alta cerrada: crea o reemplaza la cuenta sin verificar y emite su token.

    Devuelve qué encontró y el ``id`` de la cuenta (``None`` solo si no la
    hay). Las ramas ``verified`` y ``deactivated`` no escriben nada: quien
    llama decide qué correo mandar, si alguno.
    """
    correo = email.strip().lower()
    with connect() as connection:
        fila = _cuenta_por_correo(connection, correo)
        if fila is None:
            # `ON CONFLICT DO NOTHING`: dos altas simultáneas del mismo correo
            # leían ambas «no existe»; la segunda caía en la restricción
            # UNIQUE. Así la segunda no inserta y vuelve a leer —ya con la
            # fila de la primera, bloqueada— como un reemplazo normal.
            creada = connection.execute(
                "INSERT INTO users (email, password_hash, display_name, created_at, "
                "email_verified_at) VALUES (%s, %s, %s, %s, NULL) "
                "ON CONFLICT (email) DO NOTHING RETURNING id",
                (correo, password_hash, display_name, now_utc_iso()),
            ).fetchone()
            if creada is not None:
                user_id = int(str(creada[0]))
                _emitir_token(connection, user_id, token_hash, expires_at)
                return "created", user_id
            fila = _cuenta_por_correo(connection, correo)
            if fila is None:  # pragma: no cover - el conflicto implica que existe
                return "deactivated", None

        user_id = int(str(fila[0]))
        if fila[2] is not None:
            return "deactivated", user_id
        if fila[1] is not None:
            return "verified", user_id

        connection.execute(
            "UPDATE users SET password_hash = %s, "
            "display_name = COALESCE(%s, display_name) WHERE id = %s",
            (password_hash, display_name, user_id),
        )
        _emitir_token(connection, user_id, token_hash, expires_at)
        return "replaced", user_id


def pending_token_email(token_hash: str) -> str | None:
    """Correo de la cuenta de un token vivo, sin gastarlo.

    Sirve para comprobar la concesión antes de consumir: si se revocó entre el
    alta y el clic, el enlace no abre sesión y tampoco se gasta.
    """
    with connect() as connection:
        fila = connection.execute(
            "SELECT u.email FROM email_verification_tokens t "
            "JOIN users u ON u.id = t.user_id "
            "WHERE t.token_hash = %s AND t.used_at IS NULL AND t.expires_at > NOW() "
            "AND u.deactivated_at IS NULL",
            (token_hash,),
        ).fetchone()
    return None if fila is None else str(fila[0])


def consume_verification_token(token_hash: str) -> int | None:
    """Marca la cuenta como verificada y gasta sus tokens; ``None`` si no vale.

    Todo en una transacción. Como en el reset, primero la cuenta y después el
    token, en dos sentencias, para no dejar el orden de bloqueo en manos del
    planificador.
    """
    with connect() as connection:
        owner = connection.execute(
            "SELECT u.id FROM users u WHERE u.id = "
            "(SELECT t.user_id FROM email_verification_tokens t WHERE t.token_hash = %s) "
            "AND u.deactivated_at IS NULL FOR UPDATE",
            (token_hash,),
        ).fetchone()
        if owner is None:
            return None
        user_id = int(str(owner[0]))
        token = connection.execute(
            "SELECT id FROM email_verification_tokens "
            "WHERE token_hash = %s AND user_id = %s "
            "AND used_at IS NULL AND expires_at > NOW() FOR UPDATE",
            (token_hash, user_id),
        ).fetchone()
        if token is None:
            return None
        connection.execute(
            "UPDATE users SET email_verified_at = COALESCE(email_verified_at, NOW()) WHERE id = %s",
            (user_id,),
        )
        connection.execute(
            "UPDATE email_verification_tokens SET used_at = NOW() "
            "WHERE user_id = %s AND used_at IS NULL",
            (user_id,),
        )
    return user_id


def delete_stale_unverified(days: int, *, apply: bool = True) -> int:
    """Borra las altas locales que nadie verificó en ``days`` días.

    Solo cuentas sin verificar, sin OAuth y sin sesiones: un alta que nadie
    confirmó no tiene nada que conservar, y su correo es un dato personal. Con
    ``apply=False`` solo cuenta (el modo de ensayo de la retención).
    """
    corte = (now_utc() - timedelta(days=days)).isoformat()
    with connect() as connection:
        if not apply:
            fila = connection.execute(
                "SELECT count(*) FROM users WHERE " + _ALTA_ABANDONADA,
                (corte,),
            ).fetchone()
            return 0 if fila is None else int(str(fila[0]))
        cur = connection.execute("DELETE FROM users WHERE " + _ALTA_ABANDONADA, (corte,))
        return int(cur.rowcount or 0)


#: Una cuenta del alta cerrada que nadie verificó y que nunca llegó a usarse.
_ALTA_ABANDONADA = (
    "email_verified_at IS NULL AND oauth_sub IS NULL AND created_at < %s "
    "AND NOT EXISTS (SELECT 1 FROM sessions s WHERE s.user_id = users.id)"
)
