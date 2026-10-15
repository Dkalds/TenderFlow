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
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

import pytest

from db.connection import connect, connect_read, now_utc
from db.mcp_oauth import (
    consumir_token,
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


def test_consumir_codigo_una_sola_vez(nuevo: Callable[..., None]) -> None:
    nuevo("c1", kind="code")
    fila, reutilizado = consumir_token("c1", "code")
    assert fila is not None and not reutilizado
    assert fila["kind"] == "code"
    assert fila["revoked_at"] is not None
    fila, reutilizado = consumir_token("c1", "code")
    assert fila is None and reutilizado
    assert obtener_token("c1", "code") is None


def test_consumir_inexistente_no_cuenta_como_reutilizado(nuevo: Callable[..., None]) -> None:
    assert consumir_token("nada", "code") == (None, False)
    # Existe, pero con otro tipo: tampoco es una reutilización.
    nuevo("c2", kind="access")
    assert consumir_token("c2", "code") == (None, False)


def test_consumir_caducado_no_cuenta_como_reutilizado(nuevo: Callable[..., None]) -> None:
    nuevo("viejo", kind="code", expires_at=now_utc() - timedelta(seconds=1))
    assert consumir_token("viejo", "code") == (None, False)


def test_consumo_concurrente_solo_gana_uno(nuevo: Callable[..., None]) -> None:
    nuevo("r1", kind="refresh", family_id="fam")
    salida = threading.Barrier(2)

    def _consumir(_: int) -> tuple[dict[str, Any] | None, bool]:
        salida.wait(timeout=10)  # los dos hilos arrancan a la vez
        return consumir_token("r1", "refresh")

    with ThreadPoolExecutor(2) as ex:
        res = list(ex.map(_consumir, range(2)))
    assert sum(fila is not None for fila, _ in res) == 1
    assert sum(reutilizado for _, reutilizado in res) == 1


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
    with pytest.raises(Exception, match="mcp_oauth_tokens"), connect() as c:
        c.execute(
            "INSERT INTO mcp_oauth_tokens (token_hash, kind, client_id, user_id, expires_at) "
            "VALUES ('h', 'otro', %s, %s, now())",
            (cliente, usuario),
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
