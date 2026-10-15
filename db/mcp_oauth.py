"""Persistencia OAuth del MCP interno: clientes registrados y tokens hasheados.

El MCP es su propio servidor de autorización (``mcp_server``). Este módulo es
lo único que toca ``mcp_oauth_clients`` y ``mcp_oauth_tokens`` (migración
``v150_mcp_oauth``). Todo es síncrono: el proveedor lo llama desde
``anyio.to_thread``.

Tokens
------
Solo se guarda ``sha256(token)`` (``token_hash``). ``mcp_oauth_tokens`` mezcla
cuatro clases de fila (``TipoToken``); ``kind`` forma parte de cada búsqueda,
de modo que un access token no se puede presentar como refresh ni al revés.

``revoked_at`` significa a la vez «revocado» y «consumido». Vigente es sin
revocar y sin caducar.

Un ``code`` o un ``refresh`` se canjea con :func:`consumir_y_emitir`: un único
``UPDATE … RETURNING`` condicional, la inserción de los tokens nuevos y, si era
una reutilización, la revocación de su familia, **todo en una transacción**. Si
dos peticiones presentan el mismo token a la vez, la base serializa las dos
sobre la fila: solo una ve ``revoked_at IS NULL``, y la perdedora espera a que
la ganadora confirme también sus tokens nuevos, de modo que su revocación de la
familia los alcanza. :func:`buscar_token` devuelve la fila en cualquier estado
para distinguir «desconocido» de «reutilizado».
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from db.connection import connect, connect_read

TipoToken = Literal["pendiente", "code", "access", "refresh"]

_VIGENTE = "revoked_at IS NULL AND expires_at > now()"


def hash_token(token: str) -> str:
    """``sha256`` hexadecimal del token: lo único que se persiste."""
    return hashlib.sha256(token.encode()).hexdigest()


def _fila(cursor: Any) -> dict[str, Any] | None:
    # `Any`: `connect()` entrega el adaptador de psycopg sin tipar (db/connection.py).
    row = cursor.fetchone()
    if row is None:
        return None
    columnas = [d[0] for d in cursor.description]
    return dict(zip(columnas, row, strict=True))


def _exigir_aware(expires_at: datetime) -> None:
    """Rechaza un ``datetime`` ingenuo: Postgres lo leería en la zona de la sesión."""
    if expires_at.tzinfo is None:
        raise ValueError("expires_at debe llevar zona horaria (datetime aware)")


@dataclass(frozen=True)
class TokenNuevo:
    """Un token a emitir dentro de :func:`consumir_y_emitir` (campos de ``guardar_token``).

    ``family_id=None`` hereda la familia del token consumido.
    """

    token: str
    kind: TipoToken
    client_id: str
    user_id: int | None
    scopes: list[str]
    expires_at: datetime
    datos: Mapping[str, object] | None = None
    family_id: str | None = None

    def __post_init__(self) -> None:
        _exigir_aware(self.expires_at)


def _insertar(
    c: Any,
    token: str,
    *,
    kind: TipoToken,
    client_id: str,
    user_id: int | None,
    family_id: str | None,
    scopes: list[str],
    datos: Mapping[str, object] | None,
    expires_at: datetime,
) -> None:
    c.execute(
        "INSERT INTO mcp_oauth_tokens "
        "(token_hash, kind, client_id, user_id, family_id, scopes, datos, expires_at) "
        "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)",
        (
            hash_token(token),
            kind,
            client_id,
            user_id,
            family_id,
            json.dumps(scopes),
            None if datos is None else json.dumps(dict(datos)),
            expires_at,
        ),
    )


# ---------------------------------------------------------------------------
# Clientes
# ---------------------------------------------------------------------------


def guardar_cliente(
    client_id: str,
    client_name: str | None,
    redirect_uris: list[str],
    datos: Mapping[str, object],
) -> None:
    """Alta o actualización idempotente de un cliente registrado."""
    with connect() as c:
        c.execute(
            "INSERT INTO mcp_oauth_clients (client_id, client_name, redirect_uris, datos) "
            "VALUES (%s, %s, %s::jsonb, %s::jsonb) "
            "ON CONFLICT (client_id) DO UPDATE SET "
            "client_name = EXCLUDED.client_name, "
            "redirect_uris = EXCLUDED.redirect_uris, datos = EXCLUDED.datos",
            (client_id, client_name, json.dumps(redirect_uris), json.dumps(dict(datos))),
        )


def obtener_cliente(client_id: str) -> dict[str, Any] | None:
    with connect_read() as c:
        return _fila(
            c.execute("SELECT * FROM mcp_oauth_clients WHERE client_id = %s", (client_id,))
        )


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


def guardar_token(
    token: str,
    *,
    kind: TipoToken,
    client_id: str,
    user_id: int | None,
    family_id: str | None,
    scopes: list[str],
    datos: Mapping[str, object] | None,
    expires_at: datetime,
) -> None:
    """Guarda ``sha256(token)``; el token en claro no llega a la base.

    ``expires_at`` debe ser aware (``ValueError`` si no). Para emitir tokens a
    partir de otro que se consume, usa :func:`consumir_y_emitir`.
    """
    _exigir_aware(expires_at)
    with connect() as c:
        _insertar(
            c,
            token,
            kind=kind,
            client_id=client_id,
            user_id=user_id,
            family_id=family_id,
            scopes=scopes,
            datos=datos,
            expires_at=expires_at,
        )


def obtener_token(token: str, kind: TipoToken) -> dict[str, Any] | None:
    """La fila del token si está vigente (sin revocar y sin caducar), o ``None``."""
    with connect_read() as c:
        return _fila(
            c.execute(
                f"SELECT * FROM mcp_oauth_tokens WHERE token_hash = %s AND kind = %s AND {_VIGENTE}",
                (hash_token(token), kind),
            )
        )


def buscar_token(token: str, kind: TipoToken) -> dict[str, Any] | None:
    """La fila del token en cualquier estado (vigente, revocado o caducado), o ``None``.

    Para distinguir «desconocido» de «reutilizado o caducado» antes de actuar
    (``load_refresh_token``); la autorización de una petición usa
    :func:`obtener_token`.
    """
    with connect_read() as c:
        return _fila(
            c.execute(
                "SELECT * FROM mcp_oauth_tokens WHERE token_hash = %s AND kind = %s",
                (hash_token(token), kind),
            )
        )


def consumir_token(token: str, kind: Literal["pendiente"]) -> tuple[dict[str, Any] | None, bool]:
    """Consume una petición ``pendiente`` (no emite nada). Devuelve ``(fila, reutilizado)``.

    Un único ``UPDATE … RETURNING``: de dos consumos simultáneos solo uno
    devuelve fila. ``reutilizado`` es ``True`` si no hubo fila pero el token
    existe ya consumido; desconocido, de otro tipo o caducado sin consumir no
    cuenta. Los ``code`` y ``refresh``, que sí emiten tokens, usan
    :func:`consumir_y_emitir`.
    """
    th = hash_token(token)
    with connect() as c:
        fila = _fila(
            c.execute(
                "UPDATE mcp_oauth_tokens SET revoked_at = now() "
                f"WHERE token_hash = %s AND kind = %s AND {_VIGENTE} RETURNING *",
                (th, kind),
            )
        )
        if fila is not None:
            return fila, False
        previo = c.execute(
            "SELECT 1 FROM mcp_oauth_tokens "
            "WHERE token_hash = %s AND kind = %s AND revoked_at IS NOT NULL",
            (th, kind),
        ).fetchone()
    return None, previo is not None


def consumir_y_emitir(
    token: str,
    kind: Literal["code", "refresh"],
    nuevos: Sequence[TokenNuevo],
    *,
    family_id: str | None = None,
) -> tuple[dict[str, Any] | None, bool]:
    """Consume un ``code``/``refresh`` y emite sus tokens nuevos en UNA transacción.

    Devuelve ``(fila, reutilizado)``:

    - **Gana** (vigente): marca el token como consumido, inserta ``nuevos`` y
      confirma todo junto → ``(fila_consumida, False)``. La familia de lo
      emitido es ``family_id`` si se pasa, si no la del token consumido, si no
      una nueva; el token consumido la conserva (un ``code`` reutilizado
      después puede así revocar lo que emitió) y los ``nuevos`` sin
      ``family_id`` la heredan. Si un INSERT falla, nada se consume.
    - **Reutilizado** (ya consumido o revocado): en la misma transacción
      revoca los tokens vivos de su familia (si tiene) → ``(fila, True)``. Quien
      pierde una carrera espera, en el ``UPDATE``, a que el ganador confirme
      consumo *y* emisión, así que su revocación ve los tokens recién emitidos.
    - **Desconocido, de otro tipo o caducado sin consumir**: ``(None, False)``
      sin cambios.
    """
    th = hash_token(token)
    with connect() as c:
        fila = _fila(
            c.execute(
                "UPDATE mcp_oauth_tokens SET revoked_at = now(), "
                "family_id = COALESCE(%s, family_id, %s) "
                f"WHERE token_hash = %s AND kind = %s AND {_VIGENTE} RETURNING *",
                (family_id, uuid.uuid4().hex, th, kind),
            )
        )
        if fila is not None:
            for nuevo in nuevos:
                _insertar(
                    c,
                    nuevo.token,
                    kind=nuevo.kind,
                    client_id=nuevo.client_id,
                    user_id=nuevo.user_id,
                    family_id=nuevo.family_id or fila["family_id"],
                    scopes=nuevo.scopes,
                    datos=nuevo.datos,
                    expires_at=nuevo.expires_at,
                )
            return fila, False
        previo = _fila(
            c.execute(
                "SELECT * FROM mcp_oauth_tokens "
                "WHERE token_hash = %s AND kind = %s AND revoked_at IS NOT NULL",
                (th, kind),
            )
        )
        if previo is None:
            return None, False
        if previo["family_id"] is not None:
            c.execute(
                "UPDATE mcp_oauth_tokens SET revoked_at = now() "
                "WHERE family_id = %s AND revoked_at IS NULL",
                (previo["family_id"],),
            )
    return previo, True


def revocar_familia(family_id: str) -> int:
    """Revoca los tokens vivos de una familia. Devuelve cuántos cerró."""
    with connect() as c:
        return int(
            c.execute(
                "UPDATE mcp_oauth_tokens SET revoked_at = now() "
                "WHERE family_id = %s AND revoked_at IS NULL",
                (family_id,),
            ).rowcount
        )


def revocar_de_usuario(user_id: int) -> int:
    """Revoca todos los tokens vivos de un usuario. Devuelve cuántos cerró."""
    with connect() as c:
        return int(
            c.execute(
                "UPDATE mcp_oauth_tokens SET revoked_at = now() "
                "WHERE user_id = %s AND revoked_at IS NULL",
                (user_id,),
            ).rowcount
        )


def revocar_token(token: str) -> None:
    """Revoca un token concreto (sea cual sea su tipo). Idempotente."""
    with connect() as c:
        c.execute(
            "UPDATE mcp_oauth_tokens SET revoked_at = now() "
            "WHERE token_hash = %s AND revoked_at IS NULL",
            (hash_token(token),),
        )
