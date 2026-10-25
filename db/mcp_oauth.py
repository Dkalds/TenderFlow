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
familia los alcanza. Un cerrojo por familia (``pg_advisory_xact_lock``) cubre
el caso de dos tokens **distintos** de la misma familia: la reutilización de
uno alcanza lo que emite a la vez la rotación del otro. :func:`buscar_token`
devuelve la fila en cualquier estado para distinguir «desconocido» de
«reutilizado».
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from db.connection import connect, connect_read

TipoToken = Literal["pendiente", "code", "access", "refresh"]

_VIGENTE = "revoked_at IS NULL AND expires_at > now()"

#: Columnas de ``mcp_oauth_tokens`` / ``mcp_oauth_clients`` (v150) que consume el
#: proveedor OAuth: la fila entera, nombrada para que una columna nueva no viaje
#: sin que alguien decida que hace falta.
_COLS_OAUTH = (
    "token_hash, kind, client_id, user_id, family_id, scopes, datos, "
    "expires_at, revoked_at, created_at"
)
_COLS_CLIENTE = "client_id, client_name, redirect_uris, datos, created_at"


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

    No lleva familia: hereda siempre la del token consumido.
    """

    token: str
    kind: TipoToken
    client_id: str
    user_id: int | None
    scopes: list[str]
    expires_at: datetime
    datos: Mapping[str, object] | None = None

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
            c.execute(
                f"SELECT {_COLS_CLIENTE} FROM mcp_oauth_clients WHERE client_id = %s",
                (client_id,),
            )
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
                f"SELECT {_COLS_OAUTH} FROM mcp_oauth_tokens "
                f"WHERE token_hash = %s AND kind = %s AND {_VIGENTE}",
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
                f"SELECT {_COLS_OAUTH} FROM mcp_oauth_tokens WHERE token_hash = %s AND kind = %s",
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
                f"WHERE token_hash = %s AND kind = %s AND {_VIGENTE} RETURNING {_COLS_OAUTH}",
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


#: Gancho de tests: se llama con la conexión entre el consumo y la emisión del
#: ganador, ya con el cerrojo de familia tomado. Lo usa
#: ``tests/test_mcp_oauth_integration.py`` para fijar una carrera sin dormir.
_antes_de_emitir: Callable[[Any], None] | None = None


def _cerrar_familia(c: Any, family_id: str) -> None:
    """Cerrojo de la familia hasta el fin de la transacción (``pg_advisory_xact_lock``).

    Serializa a quien emite en una familia con quien la revoca por reutilización.
    Sin él, un ``UPDATE`` de revocación bloqueado por una rotación simultánea
    re-evalúa solo las filas que ya veía y no alcanza el token que esa rotación
    inserta. Se toma **antes** de cualquier bloqueo de fila: tomarlo después del
    ``UPDATE`` condicional cruza el orden con el revocador (que lo tiene y espera
    la fila) y Postgres aborta uno por *deadlock*.
    """
    c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (family_id,))


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
      confirma todo junto → ``(fila_consumida, False)``. Los ``nuevos`` heredan
      la familia del token consumido; un ``code`` recibe ``family_id`` si se
      pasa, si no conserva la suya o estrena una, y la guarda una vez consumido (un
      ``code`` reutilizado después puede así revocar lo que emitió). Si un
      INSERT falla, nada se consume.
    - **Reutilizado** (ya consumido o revocado): en la misma transacción
      revoca los tokens vivos de su familia (si tiene) → ``(fila, True)``.
    - **Desconocido, de otro tipo o caducado sin consumir**: ``(None, False)``
      sin cambios.

    ``family_id`` solo se admite con ``kind == "code"`` (``ValueError`` si no):
    un refresh no cambia nunca de familia.

    Concurrencia: el ganador y el revocador toman el cerrojo de la familia
    (:func:`_cerrar_familia`) antes de tocar filas. Dos canjes del mismo token
    se serializan además sobre su fila: el perdedor espera a que el ganador
    confirme consumo *y* emisión, y su revocación, posterior, ve lo emitido. Lo
    mismo vale para la reutilización de **otro** token de la familia mientras
    se rota uno vivo.
    """
    if family_id is not None and kind != "code":
        raise ValueError("family_id solo se admite al canjear un code")
    th = hash_token(token)
    with connect() as c:
        actual = c.execute(
            "SELECT family_id FROM mcp_oauth_tokens WHERE token_hash = %s AND kind = %s",
            (th, kind),
        ).fetchone()
        if actual is None:
            return None, False
        # La que el UPDATE dejará: la de un refresh no cambia nunca; un code la
        # recibe aquí (la pedida, la suya o una nueva).
        familia: str = family_id or actual[0] or uuid.uuid4().hex
        _cerrar_familia(c, familia)
        fila = _fila(
            c.execute(
                "UPDATE mcp_oauth_tokens SET revoked_at = now(), family_id = %s "
                f"WHERE token_hash = %s AND kind = %s AND {_VIGENTE} RETURNING {_COLS_OAUTH}",
                (familia, th, kind),
            )
        )
        if fila is not None:
            if _antes_de_emitir is not None:
                _antes_de_emitir(c)
            for nuevo in nuevos:
                _insertar(
                    c,
                    nuevo.token,
                    kind=nuevo.kind,
                    client_id=nuevo.client_id,
                    user_id=nuevo.user_id,
                    family_id=familia,
                    scopes=nuevo.scopes,
                    datos=nuevo.datos,
                    expires_at=nuevo.expires_at,
                )
            return fila, False
        previo = _fila(
            c.execute(
                f"SELECT {_COLS_OAUTH} FROM mcp_oauth_tokens "
                "WHERE token_hash = %s AND kind = %s AND revoked_at IS NOT NULL",
                (th, kind),
            )
        )
        if previo is None:
            return None, False
        if previo["family_id"] is not None:
            if previo["family_id"] != familia:
                # Un code que otro canje consumió con otra familia que la
                # cerrada arriba.
                _cerrar_familia(c, previo["family_id"])
            c.execute(
                "UPDATE mcp_oauth_tokens SET revoked_at = now() "
                "WHERE family_id = %s AND revoked_at IS NULL",
                (previo["family_id"],),
            )
    return previo, True


def revocar_familia(family_id: str) -> int:
    """Revoca los tokens vivos de una familia. Devuelve cuántos cerró.

    Con el cerrojo de la familia (:func:`_cerrar_familia`): una rotación en
    curso termina antes, y la revocación alcanza el par que acaba de emitir.
    """
    with connect() as c:
        _cerrar_familia(c, family_id)
        return int(
            c.execute(
                "UPDATE mcp_oauth_tokens SET revoked_at = now() "
                "WHERE family_id = %s AND revoked_at IS NULL",
                (family_id,),
            ).rowcount
        )


#: Pasadas de :func:`revocar_de_usuario`: cada una solo existe si un canje
#: simultáneo estrenó familia (un code) mientras la anterior esperaba.
_MAX_PASADAS = 5


def revocar_de_usuario(user_id: int) -> int:
    """Revoca todos los tokens vivos de un usuario. Devuelve cuántos cerró.

    Cierra cada familia viva del usuario, en orden estable, antes de tocar
    filas, como :func:`revocar_familia`. Un code no tiene familia hasta que se
    canjea: si un canje la estrena mientras esta revocación espera su fila, la
    pasada siguiente la ve, la cierra y revoca lo emitido. Un cerrojo por
    usuario serializa dos revocaciones del mismo usuario, que si no podrían
    cruzar el orden de esas familias tardías.
    """
    total = 0
    cerradas: set[str] = set()
    with connect() as c:
        c.execute("SELECT pg_advisory_xact_lock(hashtext('mcp_oauth_usuario:' || %s))", (user_id,))
        for pasada in range(_MAX_PASADAS):
            vivas = {
                str(f[0])
                for f in c.execute(
                    "SELECT DISTINCT family_id FROM mcp_oauth_tokens "
                    "WHERE user_id = %s AND revoked_at IS NULL AND family_id IS NOT NULL",
                    (user_id,),
                ).fetchall()
            }
            nuevas = sorted(vivas - cerradas)
            if pasada and not nuevas:
                break
            for familia in nuevas:
                _cerrar_familia(c, familia)
            cerradas.update(nuevas)
            total += int(
                c.execute(
                    "UPDATE mcp_oauth_tokens SET revoked_at = now() "
                    "WHERE user_id = %s AND revoked_at IS NULL",
                    (user_id,),
                ).rowcount
            )
    return total


def revocar_token(token: str) -> None:
    """Revoca un token concreto (sea cual sea su tipo). Idempotente."""
    with connect() as c:
        c.execute(
            "UPDATE mcp_oauth_tokens SET revoked_at = now() "
            "WHERE token_hash = %s AND revoked_at IS NULL",
            (hash_token(token),),
        )


# ---------------------------------------------------------------------------
# Purga
# ---------------------------------------------------------------------------

#: Lo que el servidor de autorización deja de necesitar y cuándo (R18).
_SQL_PURGA = (
    (
        "peticiones_y_codigos",
        # Viven 10 min y 60 s; un día de margen para investigar un incidente.
        "DELETE FROM mcp_oauth_tokens WHERE kind IN ('pendiente', 'code') "
        "AND expires_at < now() - interval '1 day'",
    ),
    (
        "tokens",
        # 30 días de margen, lo que vive un refresh: un refresh rotado sigue
        # detectando su reutilización (y revocando la familia) durante toda la
        # vida que habría tenido. Plazo confirmado por el dueño el 2026-10-19
        # (la revisión del MCP había dejado 7 días pendiente de confirmar).
        "DELETE FROM mcp_oauth_tokens WHERE kind IN ('access', 'refresh') "
        "AND (revoked_at < now() - interval '30 days' OR expires_at < now() - interval '30 days')",
    ),
    (
        "clientes",
        # Registros del DCR abierto que nunca llegaron a tener un token (o cuyos
        # tokens ya se purgaron). Va después: ve lo que acaban de borrar las otras.
        "DELETE FROM mcp_oauth_clients c WHERE c.created_at < now() - interval '30 days' "
        "AND NOT EXISTS (SELECT 1 FROM mcp_oauth_tokens t WHERE t.client_id = c.client_id)",
    ),
)


def purgar() -> dict[str, int]:
    """Borra lo caducado o revocado y los clientes huérfanos; devuelve cuántas filas por clase.

    - ``pendiente`` y ``code`` caducados hace más de un día;
    - ``access`` y ``refresh`` revocados (o consumidos) o caducados hace más de 30 días;
    - clientes registrados hace más de 30 días sin ningún token.

    Una transacción. La llama el servidor MCP al arrancar y cada hora
    (``mcp_server/servidor.py``); el DCR y ``/authorize`` son abiertos, y sin
    esto sus filas crecerían sin fin.
    """
    with connect() as c:
        return {clase: int(c.execute(sql).rowcount) for clase, sql in _SQL_PURGA}
