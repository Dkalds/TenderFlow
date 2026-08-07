"""Entradas malformadas devuelven 4xx, no 5xx.

Las tres operaciones que cubre este módulo estaban congeladas en ``KNOWN_5XX``
(``scripts/fuzz_api_contract.py``): bastaba un carácter enviado por cualquier
cliente para provocar un 500.

- ``\\x00`` en una cadena viajaba hasta Postgres, que no lo admite en columnas
  de texto, y su ``DataError`` salía como 500 (``POST /licitaciones/bulk-get``
  y ``PUT /feature-flags``).
- Bytes que no son UTF-8 válido en el path (``%ff``) reventaban al construir la
  respuesta de error (``DELETE /watchlist/items/{id_externo}``).

El saneo del cuerpo vive en el contrato (``shared.dto.SafeStr``) y no en cada
endpoint: es una decisión de diseño, no un parche por ruta.

Sobre el caso del path: el diagnóstico original ("rompe la decodificación antes
de que la ruta se ejecute") era falso. La ruta corría y respondía 404; lo que
reventaba era el propio manejador de errores, que metía ``str(request.url)`` —con
los bytes crudos del cliente— en un **header** llamado ``instance``. El fuzzer lo
destapó el 2026-08-07: ``.response(instance=...)`` convertía en header cualquier
kwarg, así que el campo nunca llegaba al body y sí a la cabecera.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def api_key(api_db):
    """Key de un usuario admin: `PUT /feature-flags` exige ese rol.

    Sin él la ruta responde 403 antes de validar el cuerpo, y el test pasaría
    sin llegar a ejercitar el saneo que quiere fijar.
    """
    from api.auth import create_api_key
    from db.users import create_user, set_admin

    user_id = create_user(email="malformed-input@example.test", password_hash="test-hash")
    set_admin(user_id, True)
    return create_api_key("test-key", scopes="*", user_id=user_id)


def _auth(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def test_nul_byte_en_bulk_get_devuelve_422(client, api_key):
    response = client.post(
        "/api/v1/licitaciones/bulk-get",
        json={"ids": ["EXP-2024-001\x00"]},
        headers=_auth(api_key),
    )
    assert response.status_code == 422
    assert response.status_code < 500


def test_bulk_get_sigue_aceptando_ids_normales(client, api_key):
    """El validador no puede romper el camino feliz."""
    response = client.post(
        "/api/v1/licitaciones/bulk-get",
        json={"ids": ["EXP-2024-001"]},
        headers=_auth(api_key),
    )
    assert response.status_code == 200


def test_nul_byte_en_feature_flags_devuelve_422(client, api_key):
    response = client.put(
        "/api/v1/feature-flags",
        json={"flags": [{"flag": "mi\x00flag", "enabled": True}]},
        headers=_auth(api_key),
    )
    assert response.status_code == 422
    assert response.status_code < 500


def test_byte_no_utf8_en_el_path_no_es_5xx(client, api_key):
    """``%ff`` en el path no puede reventar antes de llegar a la ruta."""
    response = client.delete("/api/v1/watchlist/items/%ff", headers=_auth(api_key))
    assert response.status_code < 500


@pytest.mark.parametrize(
    "path",
    [
        # Bytes crudos tal y como los entrega ASGI (decodificados latin-1). El
        # test anterior mandaba `%ff`, que `unquote` sustituye por U+FFFD sin
        # avisar: pasaba en verde sin llegar a reproducir el fallo.
        "/api/v1/watchlist/items/Ký\xc7\x8dl",
        "/api/v1/licitaciones/h\x97\x04\xceVn\x04/escenarios-precio",
        "/api/v1/watchlist/items/\udcfd",  # surrogate suelto
    ],
)
def test_ningun_header_de_respuesta_lleva_bytes_no_ascii(api_db, api_key, path):
    """Un header con bytes crudos del cliente rompe el transporte, no el cliente.

    Se llama a la app ASGI a mano porque los clientes HTTP normalizan el path
    antes de enviarlo y el fallo no se reproduce a través de ellos.
    """
    import anyio

    from api.app import app

    mensajes: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        mensajes.append(message)

    async def run() -> None:
        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.3"},
                "http_version": "1.1",
                "method": "DELETE",
                "scheme": "http",
                "path": path,
                "raw_path": path.encode("latin-1", "replace"),
                "query_string": b"",
                "root_path": "",
                "headers": [(b"host", b"test"), (b"x-api-key", api_key.encode())],
                "client": ("127.0.0.1", 1234),
                "server": ("test", 80),
            },
            receive,
            send,
        )

    anyio.run(run)

    inicio = next(m for m in mensajes if m["type"] == "http.response.start")
    assert inicio["status"] < 500
    for nombre, valor in inicio["headers"]:
        # `decode()` es utf-8: es lo que hacen los transportes reales al leer
        # la respuesta, y lo que reventaba con estos bytes.
        valor.decode("utf-8")
        assert valor.isascii(), f"header {nombre!r} lleva bytes no-ASCII: {valor!r}"


def test_pasar_un_campo_del_modelo_como_header_es_un_error():
    """`.response(instance=...)` era silencioso: creaba el header y perdía el campo."""
    from api.errors import problem_500

    with pytest.raises(TypeError, match="no headers"):
        problem_500().response(instance="http://x/y")


def test_el_instance_llega_al_body_y_no_a_los_headers(client, api_key):
    """RFC 7807: `instance` identifica la petición y va en el cuerpo."""
    response = client.post(
        "/api/v1/licitaciones/bulk-get",
        json={"ids": ["EXP-2024-001\x00"]},
        headers=_auth(api_key),
    )
    assert response.status_code == 422
    assert "instance" not in response.headers
    assert response.json()["instance"].endswith("/api/v1/licitaciones/bulk-get")
