"""Persistencia OAuth del MCP interno (v150 y ``db/mcp_oauth.py``), contra Postgres.

Qué se fija
-----------
- Solo se guarda ``sha256(token)``: el secreto en claro no aparece en ninguna
  columna.
- Un código o un refresh se consume **una sola vez**, y el consumo es atómico
  en la base: dos hilos que presentan el mismo refresh a la vez producen
  exactamente un ganador (Review Focus 4).
- Caducado o revocado equivale a inexistente para ``obtener_token``.
- Revocar por familia o por usuario devuelve cuántas filas cerró.
- Borrar al usuario borra sus tokens (``ON DELETE CASCADE``).
- La migración deja las dos tablas con RLS activa (sin FORCE) y, si el rol
  ``tenderflow_app`` existe, con su política de acceso total.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any

import psycopg.errors
import pytest

from db.connection import connect, connect_read, now_utc
from db.mcp_oauth import (
    TipoToken,
    TokenNuevo,
    buscar_token,
    consumir_token,
    consumir_y_emitir,
    guardar_cliente,
    guardar_token,
    hash_token,
    obtener_cliente,
    obtener_token,
    revocar_de_usuario,
    revocar_familia,
    revocar_token,
)
from db.users import create_user

CLIENTE = "cliente-1"


@pytest.fixture()
def cliente(tmp_db: Any) -> str:
    guardar_cliente(
        CLIENTE, "Claude", ["https://claude.ai/api/mcp/auth_callback"], {"grant_types": ["x"]}
    )
    return CLIENTE


@pytest.fixture()
def usuario(tmp_db: Any) -> int:
    return create_user(email="admin@example.com", password_hash="x")  # pragma: allowlist secret


@pytest.fixture()
def nuevo(cliente: str, usuario: int) -> Callable[..., None]:
    def _guardar(token: str, kind: str = "access", **extra: Any) -> None:
        params: dict[str, Any] = {
            "kind": kind,
            "client_id": cliente,
            "user_id": usuario,
            "family_id": None,
            "scopes": ["mcp:read"],
            "datos": None,
            "expires_at": now_utc() + timedelta(hours=1),
        }
        params.update(extra)
        guardar_token(token, **params)

    return _guardar


def _todas_las_filas(tabla: str) -> list[tuple[Any, ...]]:
    with connect_read() as c:
        return [tuple(f) for f in c.execute(f"SELECT * FROM {tabla}").fetchall()]  # noqa: S608


def test_hash_token_es_sha256_hex() -> None:
    assert (
        hash_token("abc")
        == (
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"  # pragma: allowlist secret
        )
    )


def test_cliente_upsert_idempotente(tmp_db: Any) -> None:
    guardar_cliente("c", "Uno", ["https://a.example/cb"], {"k": 1})
    guardar_cliente("c", "Dos", ["https://b.example/cb"], {"k": 2})
    fila = obtener_cliente("c")
    assert fila is not None
    assert fila["client_name"] == "Dos"
    assert fila["redirect_uris"] == ["https://b.example/cb"]
    assert fila["datos"] == {"k": 2}
    assert len(_todas_las_filas("mcp_oauth_clients")) == 1
    assert obtener_cliente("no-existe") is None


def test_token_se_guarda_hasheado(cliente: str, nuevo: Callable[..., None]) -> None:
    nuevo("secreto-en-claro", kind="access")
    filas = _todas_las_filas("mcp_oauth_tokens")
    assert len(filas) == 1
    assert "secreto-en-claro" not in json.dumps(filas, default=str)
    assert hash_token("secreto-en-claro") in json.dumps(filas, default=str)


def test_obtener_token_devuelve_la_fila_y_respeta_el_tipo(nuevo: Callable[..., None]) -> None:
    nuevo("t1", kind="access", family_id="fam", datos={"resource": "https://mcp.example/mcp"})
    fila = obtener_token("t1", "access")
    assert fila is not None
    assert fila["scopes"] == ["mcp:read"]
    assert fila["family_id"] == "fam"
    assert fila["datos"] == {"resource": "https://mcp.example/mcp"}
    assert "token_hash" in fila
    assert obtener_token("t1", "refresh") is None
    assert obtener_token("otro", "access") is None


def test_pendiente_admite_usuario_nulo(nuevo: Callable[..., None]) -> None:
    nuevo("p1", kind="pendiente", user_id=None, datos={"state": "s"})
    fila = obtener_token("p1", "pendiente")
    assert fila is not None and fila["user_id"] is None


def test_pendiente_se_consume_una_sola_vez(nuevo: Callable[..., None]) -> None:
    nuevo("p1", kind="pendiente", user_id=None)
    fila, reutilizado = consumir_token("p1", "pendiente")
    assert fila is not None and not reutilizado
    assert consumir_token("p1", "pendiente") == (None, True)
    assert consumir_token("nada", "pendiente") == (None, False)
    nuevo("a1", kind="access")
    assert consumir_token("a1", "pendiente") == (None, False)  # otro tipo


def _emitidos(cliente: str, usuario: int, sufijo: str) -> list[TokenNuevo]:
    futuro = now_utc() + timedelta(hours=1)
    return [
        TokenNuevo(f"a-{sufijo}", "access", cliente, usuario, ["mcp:read"], futuro),
        TokenNuevo(f"r-{sufijo}", "refresh", cliente, usuario, ["mcp:read"], futuro),
    ]


def test_consumir_codigo_emite_y_registra_la_familia(
    cliente: str, usuario: int, nuevo: Callable[..., None]
) -> None:
    nuevo("c1", kind="code")
    fila, reutilizado = consumir_y_emitir("c1", "code", _emitidos(cliente, usuario, "1"))
    assert fila is not None and not reutilizado
    assert fila["revoked_at"] is not None
    familia = fila["family_id"]
    assert familia  # el código consumido recuerda la familia de lo que emitió
    pares: list[tuple[str, TipoToken]] = [("a-1", "access"), ("r-1", "refresh")]
    for token, kind in pares:
        emitido = obtener_token(token, kind)
        assert emitido is not None and emitido["family_id"] == familia
    assert obtener_token("c1", "code") is None


def test_reutilizar_un_codigo_revoca_lo_emitido(
    cliente: str, usuario: int, nuevo: Callable[..., None]
) -> None:
    nuevo("c1", kind="code")
    consumir_y_emitir("c1", "code", _emitidos(cliente, usuario, "1"))
    assert obtener_token("a-1", "access") is not None
    fila, reutilizado = consumir_y_emitir("c1", "code", _emitidos(cliente, usuario, "2"))
    assert reutilizado and fila is not None and fila["kind"] == "code"
    assert obtener_token("a-1", "access") is None
    assert obtener_token("r-1", "refresh") is None
    # El segundo intento no emitió nada.
    assert obtener_token("a-2", "access") is None and buscar_token("a-2", "access") is None


def test_rotar_refresh_hereda_la_familia(
    cliente: str, usuario: int, nuevo: Callable[..., None]
) -> None:
    nuevo("r0", kind="refresh", family_id="fam")
    fila, reutilizado = consumir_y_emitir("r0", "refresh", _emitidos(cliente, usuario, "1"))
    assert fila is not None and not reutilizado and fila["family_id"] == "fam"
    nuevo_refresh = obtener_token("r-1", "refresh")
    assert nuevo_refresh is not None and nuevo_refresh["family_id"] == "fam"


def test_family_id_explicito_solo_para_un_codigo(
    cliente: str, usuario: int, nuevo: Callable[..., None]
) -> None:
    """R10 (b): un refresh nunca cambia de familia; un código sí puede recibirla."""
    nuevo("r0", kind="refresh", family_id="fam")
    with pytest.raises(ValueError, match="code"):
        consumir_y_emitir("r0", "refresh", _emitidos(cliente, usuario, "1"), family_id="otra")
    assert obtener_token("r0", "refresh") is not None  # nada se consumió
    assert buscar_token("a-1", "access") is None
    assert not hasattr(TokenNuevo, "family_id")

    nuevo("c1", kind="code")
    fila, reutilizado = consumir_y_emitir(
        "c1", "code", _emitidos(cliente, usuario, "2"), family_id="elegida"
    )
    assert fila is not None and not reutilizado and fila["family_id"] == "elegida"
    emitido = obtener_token("r-2", "refresh")
    assert emitido is not None and emitido["family_id"] == "elegida"


def test_reutilizar_revoca_lo_que_otra_rotacion_emite_a_la_vez(
    cliente: str, usuario: int, nuevo: Callable[..., None], monkeypatch: pytest.MonkeyPatch
) -> None:
    """R10 (a): la revocación por reutilización alcanza lo que emite otra rotación simultánea.

    Familia ``fam``: ``r0`` ya se canjeó (lo emitido entonces fue ``r1``, vivo).
    El hilo legítimo rota ``r1`` y, entre consumirlo y emitir ``r2``, se detiene
    hasta que el hilo atacante, que reutiliza ``r0``, queda **bloqueado por él**
    (``pg_blocking_pids``, sin dormir). Sin el cerrojo de familia, el ``UPDATE``
    de la revocación esperaba la fila de ``r1``, la volvía a evaluar ya
    consumida y no veía ``r2``, insertada por la transacción a la que esperaba:
    ``r2`` quedaba vivo en una familia revocada.
    """
    import db.mcp_oauth as modulo

    nuevo("r0", kind="refresh", family_id="fam")
    consumir_y_emitir("r0", "refresh", _emitidos(cliente, usuario, "1"))  # emite r-1
    consumido = threading.Event()

    def _pausa(c: Any) -> None:
        pid = c.execute("SELECT pg_backend_pid()").fetchone()[0]
        consumido.set()
        limite = time.monotonic() + 10
        while time.monotonic() < limite:
            with connect_read() as otra:
                bloqueados = otra.execute(
                    "SELECT count(*) FROM pg_stat_activity WHERE %s = ANY(pg_blocking_pids(pid))",
                    (pid,),
                ).fetchone()[0]
            if bloqueados:
                return
            time.sleep(0.01)
        raise AssertionError("el hilo que reutiliza r0 nunca llegó a esperar al que rota r1")

    monkeypatch.setattr(modulo, "_antes_de_emitir", _pausa)

    def _rotar() -> tuple[dict[str, Any] | None, bool]:
        return consumir_y_emitir("r-1", "refresh", _emitidos(cliente, usuario, "2"))

    def _reutilizar() -> tuple[dict[str, Any] | None, bool]:
        assert consumido.wait(timeout=10)
        return consumir_y_emitir("r0", "refresh", _emitidos(cliente, usuario, "3"))

    with ThreadPoolExecutor(2) as ex:
        rotacion = ex.submit(_rotar)
        reutilizacion = ex.submit(_reutilizar)
        fila_rot, reu_rot = rotacion.result(timeout=30)
        fila_reu, reu_reu = reutilizacion.result(timeout=30)
    assert fila_rot is not None and not reu_rot  # la rotación ganó y emitió r-2
    assert fila_reu is not None and reu_reu
    assert buscar_token("r-2", "refresh") is not None
    assert obtener_token("r-2", "refresh") is None  # …y la reutilización la alcanzó
    assert obtener_token("a-2", "access") is None


def test_reutilizar_refresh_revoca_la_familia(
    cliente: str, usuario: int, nuevo: Callable[..., None]
) -> None:
    nuevo("r0", kind="refresh", family_id="fam")
    consumir_y_emitir("r0", "refresh", _emitidos(cliente, usuario, "1"))
    fila, reutilizado = consumir_y_emitir("r0", "refresh", _emitidos(cliente, usuario, "2"))
    assert reutilizado and fila is not None and fila["family_id"] == "fam"
    assert obtener_token("a-1", "access") is None
    assert obtener_token("r-1", "refresh") is None
    assert buscar_token("a-2", "access") is None


def test_desconocido_otro_tipo_o_caducado_no_cambian_nada(
    cliente: str, usuario: int, nuevo: Callable[..., None]
) -> None:
    assert consumir_y_emitir("nada", "refresh", _emitidos(cliente, usuario, "1")) == (None, False)
    # Existe, pero es un access: no se puede presentar como refresh (ni como code).
    nuevo("a0", kind="access", family_id="fam")
    assert consumir_y_emitir("a0", "refresh", _emitidos(cliente, usuario, "2")) == (None, False)
    assert consumir_y_emitir("a0", "code", _emitidos(cliente, usuario, "2")) == (None, False)
    assert obtener_token("a0", "access") is not None  # ni consumido ni su familia revocada
    nuevo("viejo", kind="code", expires_at=now_utc() - timedelta(seconds=1))
    assert consumir_y_emitir("viejo", "code", _emitidos(cliente, usuario, "3")) == (None, False)
    assert buscar_token("a-1", "access") is None
    assert buscar_token("a-2", "access") is None
    assert buscar_token("a-3", "access") is None


def test_si_falla_la_emision_no_se_consume(
    cliente: str, usuario: int, nuevo: Callable[..., None]
) -> None:
    nuevo("r0", kind="refresh", family_id="fam")
    futuro = now_utc() + timedelta(hours=1)
    malo = TokenNuevo("x", "access", "cliente-que-no-existe", usuario, [], futuro)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        consumir_y_emitir("r0", "refresh", [*_emitidos(cliente, usuario, "1"), malo])
    assert obtener_token("r0", "refresh") is not None
    assert buscar_token("a-1", "access") is None  # tampoco quedó el primero


def test_buscar_token_ve_revocados_y_caducados(nuevo: Callable[..., None]) -> None:
    nuevo("vivo", kind="refresh")
    nuevo("rev", kind="refresh", family_id="f")
    nuevo("viejo", kind="refresh", expires_at=now_utc() - timedelta(minutes=1))
    revocar_token("rev")
    assert buscar_token("vivo", "refresh") is not None
    revocado = buscar_token("rev", "refresh")
    assert revocado is not None and revocado["revoked_at"] is not None
    assert revocado["family_id"] == "f"
    assert buscar_token("viejo", "refresh") is not None
    assert obtener_token("viejo", "refresh") is None
    assert buscar_token("desconocido", "refresh") is None
    assert buscar_token("vivo", "access") is None  # otro tipo


def test_consumo_concurrente_solo_gana_uno_y_la_familia_queda_revocada(
    cliente: str, usuario: int, nuevo: Callable[..., None]
) -> None:
    """Review Focus 4: el perdedor revoca la familia y alcanza los tokens del ganador."""
    nuevo("r1", kind="refresh", family_id="fam")
    salida = threading.Barrier(2)

    def _consumir(i: int) -> tuple[dict[str, Any] | None, bool]:
        salida.wait(timeout=10)  # los dos hilos arrancan a la vez
        return consumir_y_emitir("r1", "refresh", _emitidos(cliente, usuario, str(i)))

    with ThreadPoolExecutor(2) as ex:
        res = list(ex.map(_consumir, range(2)))
    assert sum(fila is not None and not reu for fila, reu in res) == 1
    assert sum(reu for _, reu in res) == 1
    ganador = next(i for i, (_, reu) in enumerate(res) if not reu)
    assert buscar_token(f"a-{ganador}", "access") is not None  # el ganador sí emitió
    assert buscar_token(f"a-{1 - ganador}", "access") is None  # el perdedor no
    familia: list[tuple[str, TipoToken]] = [
        ("r1", "refresh"),
        (f"a-{ganador}", "access"),
        (f"r-{ganador}", "refresh"),
    ]
    for token, kind in familia:
        assert obtener_token(token, kind) is None


def test_expires_at_ingenuo_se_rechaza(cliente: str, usuario: int) -> None:
    ingenuo = datetime(2030, 1, 1)
    with pytest.raises(ValueError, match="zona horaria"):
        guardar_token(
            "x",
            kind="access",
            client_id=cliente,
            user_id=usuario,
            family_id=None,
            scopes=[],
            datos=None,
            expires_at=ingenuo,
        )
    with pytest.raises(ValueError, match="zona horaria"):
        TokenNuevo("x", "access", cliente, usuario, [], ingenuo)
    assert _todas_las_filas("mcp_oauth_tokens") == []


def test_token_caducado_no_se_obtiene(nuevo: Callable[..., None]) -> None:
    nuevo("caduca", kind="access", expires_at=now_utc() - timedelta(minutes=1))
    assert obtener_token("caduca", "access") is None


def test_token_revocado_no_se_obtiene(nuevo: Callable[..., None]) -> None:
    nuevo("r", kind="access")
    revocar_token("r")
    assert obtener_token("r", "access") is None
    revocar_token("no-existe")  # no falla


def test_revocar_familia_y_usuario(cliente: str, usuario: int, nuevo: Callable[..., None]) -> None:
    otro = create_user(email="otro@example.com", password_hash="x")  # pragma: allowlist secret
    nuevo("a1", kind="access", family_id="f1")
    nuevo("r1", kind="refresh", family_id="f1")
    nuevo("r2", kind="refresh", family_id="f2")
    nuevo("o1", kind="refresh", family_id="f3", user_id=otro)

    assert revocar_familia("f1") == 2
    assert revocar_familia("f1") == 0  # ya revocadas: no se cuentan de nuevo
    assert obtener_token("a1", "access") is None
    assert obtener_token("r1", "refresh") is None
    assert obtener_token("r2", "refresh") is not None

    assert revocar_de_usuario(usuario) == 1
    assert obtener_token("r2", "refresh") is None
    assert obtener_token("o1", "refresh") is not None


def test_borrar_usuario_borra_sus_tokens(usuario: int, nuevo: Callable[..., None]) -> None:
    nuevo("u1", kind="refresh")
    nuevo("p", kind="pendiente", user_id=None)
    with connect() as c:
        c.execute("DELETE FROM users WHERE id = %s", (usuario,))
    filas = _todas_las_filas("mcp_oauth_tokens")
    assert len(filas) == 1  # solo queda la pendiente, que no era de nadie


def test_borrar_cliente_borra_sus_tokens(cliente: str, nuevo: Callable[..., None]) -> None:
    nuevo("u1", kind="refresh")
    with connect() as c:
        c.execute("DELETE FROM mcp_oauth_clients WHERE client_id = %s", (cliente,))
    assert _todas_las_filas("mcp_oauth_tokens") == []


def test_kind_invalido_lo_rechaza_la_base(cliente: str, usuario: int) -> None:
    with pytest.raises(psycopg.errors.CheckViolation), connect() as c:
        c.execute(
            "INSERT INTO mcp_oauth_tokens (token_hash, kind, client_id, user_id, expires_at) "
            "VALUES ('h', 'otro', %s, %s, now())",
            (cliente, usuario),
        )


@pytest.mark.parametrize("kind", ["code", "access", "refresh"])
def test_solo_la_pendiente_puede_no_tener_usuario(cliente: str, kind: str) -> None:
    with pytest.raises(psycopg.errors.CheckViolation), connect() as c:
        c.execute(
            "INSERT INTO mcp_oauth_tokens (token_hash, kind, client_id, user_id, expires_at) "
            "VALUES ('h', %s, %s, NULL, now())",
            (kind, cliente),
        )


def test_las_tablas_nacen_con_rls_sin_force(tmp_db: Any) -> None:
    with connect_read() as c:
        filas = c.execute(
            "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
            "FROM pg_class c WHERE c.relname IN ('mcp_oauth_clients', 'mcp_oauth_tokens') "
            "AND c.relnamespace = current_schema()::regnamespace ORDER BY 1"
        ).fetchall()
    assert [(f[0], f[1], f[2]) for f in filas] == [
        ("mcp_oauth_clients", True, False),
        ("mcp_oauth_tokens", True, False),
    ]
