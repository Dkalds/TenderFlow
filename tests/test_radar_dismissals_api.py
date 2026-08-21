"""Rutas /api/v1/radar/dismissals — triaje del Radar persistido por usuario.

El descarte vivía en ``React.useState``: el usuario triaba las 24 señales,
recargaba, y volvían las 24. Estos tests fijan que ahora sobrevive, y que el
aislamiento entre usuarios es real (el repositorio filtra por ``user_key`` en
todas sus queries, no delega la propiedad en la ruta).
"""

from __future__ import annotations

from urllib.parse import quote

import pytest


@pytest.fixture()
def api_key(api_db):
    """Override de conftest: vincula la key a un usuario real.

    ``require_any_auth`` deriva ``user_key`` de la identidad; la key sin
    vincular del fixture compartido usa su propio id como ``user_id`` postizo,
    que no existe en ``users``.
    """
    from api.auth import create_api_key
    from db.users import create_user

    user_id = create_user(email="radar-dismissals@example.test", password_hash="test-hash")
    return create_api_key("test-key", scopes="*", user_id=user_id)


def _auth(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def test_requires_auth(client):
    assert client.get("/api/v1/radar/dismissals").status_code == 401


def test_dismiss_list_restore_roundtrip(client, api_key):
    """Descartar, verlo listado y deshacerlo."""
    assert client.get("/api/v1/radar/dismissals", headers=_auth(api_key)).json()["ids"] == []

    created = client.post(
        "/api/v1/radar/dismissals",
        json={"id_externo": "LIC-1"},
        headers=_auth(api_key),
    )
    assert created.status_code == 201
    assert created.json()["ids"] == ["LIC-1"]

    listed = client.get("/api/v1/radar/dismissals", headers=_auth(api_key))
    assert listed.json()["ids"] == ["LIC-1"]

    removed = client.delete("/api/v1/radar/dismissals/LIC-1", headers=_auth(api_key))
    assert removed.status_code == 204

    assert client.get("/api/v1/radar/dismissals", headers=_auth(api_key)).json()["ids"] == []


def test_roundtrip_id_externo_con_barras(client, api_key):
    """Una señal de PLACSP con '/' se puede descartar y también recuperar.

    El POST recibe el ``id_externo`` en el body y siempre aceptó las barras; el
    DELETE lo recibe por la ruta y con el conversor por defecto (``[^/]+``) no
    casaba, así que devolvía un 404 de enrutado: la señal quedaba descartada
    para siempre. Ver ``tests/test_routing_id_externo_con_barras.py`` para el
    invariante de enrutado completo.
    """
    h = _auth(api_key)
    id_externo = "PA-S 2026/000058"

    creado = client.post("/api/v1/radar/dismissals", json={"id_externo": id_externo}, headers=h)
    assert creado.status_code == 201
    assert creado.json()["ids"] == [id_externo]

    url = f"/api/v1/radar/dismissals/{quote(id_externo, safe='')}"
    assert client.delete(url, headers=h).status_code == 204
    assert client.get("/api/v1/radar/dismissals", headers=h).json()["ids"] == []


def test_dismiss_is_idempotent(client, api_key):
    """Descartar dos veces no duplica: la PK es (user_key, id_externo)."""
    for _ in range(2):
        response = client.post(
            "/api/v1/radar/dismissals",
            json={"id_externo": "LIC-DUP"},
            headers=_auth(api_key),
        )
        assert response.status_code == 201

    assert client.get("/api/v1/radar/dismissals", headers=_auth(api_key)).json()["ids"] == [
        "LIC-DUP"
    ]


def test_restore_inexistente_404(client, api_key):
    response = client.delete("/api/v1/radar/dismissals/NO-EXISTE", headers=_auth(api_key))
    assert response.status_code == 404


def test_el_triaje_sobrevive_entre_peticiones(client, api_key):
    """El descarte persiste: es el P0 que este endpoint vino a cerrar.

    Antes vivía en memoria del navegador; recargar devolvía las 24 señales ya
    triadas. Aquí se comprueba con peticiones independientes.
    """
    client.post(
        "/api/v1/radar/dismissals",
        json={"id_externo": "LIC-PERSISTE"},
        headers=_auth(api_key),
    )
    for _ in range(3):
        listed = client.get("/api/v1/radar/dismissals", headers=_auth(api_key))
        assert listed.json()["ids"] == ["LIC-PERSISTE"]


def test_los_descartes_de_distintos_usuarios_no_se_mezclan(client, api_db):
    """Aislamiento por user_key: el repositorio se defiende solo."""
    from api.auth import create_api_key
    from db.users import create_user

    uno = create_api_key(
        "key-uno",
        scopes="*",
        user_id=create_user(email="radar-uno@example.test", password_hash="h"),
    )
    dos = create_api_key(
        "key-dos",
        scopes="*",
        user_id=create_user(email="radar-dos@example.test", password_hash="h"),
    )

    client.post("/api/v1/radar/dismissals", json={"id_externo": "SOLO-UNO"}, headers=_auth(uno))

    assert client.get("/api/v1/radar/dismissals", headers=_auth(uno)).json()["ids"] == ["SOLO-UNO"]
    assert client.get("/api/v1/radar/dismissals", headers=_auth(dos)).json()["ids"] == []

    # Y el segundo usuario tampoco puede deshacer el descarte del primero.
    assert client.delete("/api/v1/radar/dismissals/SOLO-UNO", headers=_auth(dos)).status_code == 404
    assert client.get("/api/v1/radar/dismissals", headers=_auth(uno)).json()["ids"] == ["SOLO-UNO"]
