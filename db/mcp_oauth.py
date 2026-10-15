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
revocar y sin caducar. ``consumir_token`` es un único ``UPDATE … RETURNING``:
si dos peticiones presentan el mismo código o refresh a la vez, la base
serializa las dos sobre la fila y solo una ve ``revoked_at IS NULL``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from db.connection import connect, connect_read

TipoToken = Literal["pendiente", "code", "access", "refresh"]

_VIGENTE = "revoked_at IS NULL AND expires_at > now()"


def hash_token(token: str) -> str:
    """``sha256`` hexadecimal del token: lo único que se persiste."""
    return hashlib.sha256(token.encode()).hexdigest()


def _fila(cursor: Any) -> dict[str, Any] | None:
    row = cursor.fetchone()
    if row is None:
        return None
    columnas = [d[0] for d in cursor.description]
    return dict(zip(columnas, row, strict=True))


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
    """Guarda ``sha256(token)``; el token en claro no llega a la base."""
    with connect() as c:
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


def obtener_token(token: str, kind: TipoToken) -> dict[str, Any] | None:
    """La fila del token si está vigente (sin revocar y sin caducar), o ``None``."""
    with connect_read() as c:
        return _fila(
            c.execute(
                f"SELECT * FROM mcp_oauth_tokens WHERE token_hash = %s AND kind = %s AND {_VIGENTE}",
                (hash_token(token), kind),
            )
        )


def consumir_token(token: str, kind: TipoToken) -> tuple[dict[str, Any] | None, bool]:
    """Consume un token de un solo uso. Devuelve ``(fila, reutilizado)``.

    Un único ``UPDATE … RETURNING``: de dos consumos simultáneos del mismo
    token solo uno devuelve fila. ``reutilizado`` es ``True`` cuando no hubo
    fila pero el token existe ya revocado/consumido (quien reutiliza un
    refresh debe provocar la revocación de su familia); un token desconocido,
    de otro tipo o caducado sin consumir no cuenta como reutilización.
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
