"""Cobertura de GET/PUT/DELETE ``/api/v1/me/profile``.

Ningún test mencionaba estos endpoints pese a gobernar el perfil de scoring
personalizado del usuario. Se añaden aquí porque los tres se reescribieron en
esta rama para sacar su acceso a BD del event loop (``run_db``), y sin una
prueba end-to-end ese cambio no quedaba ejercitado.
"""

from __future__ import annotations

import pytest

_EMAIL = "perfil@example.com"
_PASSWORD = "Perfil-2026-Seguro"  # pragma: allowlist secret


@pytest.fixture()
def session_client(client, api_db):
    """TestClient con sesión activa y su token CSRF."""
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": _EMAIL, "password": _PASSWORD},
    )
    assert reg.status_code == 201, reg.text
    login = client.post(
        "/api/v1/auth/login",
        json={"email": _EMAIL, "password": _PASSWORD},
    )
    assert login.status_code == 200, login.text
    return client, login.cookies["csrf_token"]


def test_get_profile_sin_perfil_devuelve_objeto_vacio(session_client):
    """Un usuario recién creado no tiene perfil: el contrato es un objeto vacío."""
    client, _ = session_client

    resp = client.get("/api/v1/me/profile")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["weights"] is None
    assert body["visibility"] == "private"


def test_put_y_get_profile_persisten_los_pesos(session_client):
    client, csrf = session_client

    put = client.put(
        "/api/v1/me/profile",
        json={
            "weights": {"afinidad": 50, "importe": 30, "plazo": 20},
            "afinidad_keywords": ["sap", "s/4hana"],
            "importe_min": 50000,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert put.status_code == 200, put.text

    got = client.get("/api/v1/me/profile")
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["weights"] == {"afinidad": 50, "importe": 30, "plazo": 20}
    assert body["afinidad_keywords"] == ["sap", "s/4hana"]
    assert body["importe_min"] == 50000


def test_put_profile_rechaza_pesos_que_no_suman_100(session_client):
    """La validación de pesos vive en el DTO, antes de tocar la BD."""
    client, csrf = session_client

    resp = client.put(
        "/api/v1/me/profile",
        json={"weights": {"afinidad": 10, "importe": 10, "plazo": 10}},
        headers={"X-CSRF-Token": csrf},
    )

    assert resp.status_code in (400, 422), resp.text


def test_delete_profile_vuelve_a_los_defaults(session_client):
    """Borrar el perfil devuelve el scoring a los settings globales."""
    client, csrf = session_client

    client.put(
        "/api/v1/me/profile",
        json={"weights": {"afinidad": 50, "importe": 30, "plazo": 20}},
        headers={"X-CSRF-Token": csrf},
    )

    delete = client.delete("/api/v1/me/profile", headers={"X-CSRF-Token": csrf})
    assert delete.status_code == 200, delete.text

    got = client.get("/api/v1/me/profile")
    assert got.status_code == 200
    assert got.json()["weights"] is None


def test_profile_exige_autenticacion(client, api_db):
    """Sin sesión no se llega al cuerpo del handler."""
    assert client.get("/api/v1/me/profile").status_code in (401, 403)


# ── Vista previa: POST /me/profile/preview ───────────────────────────────────


@pytest.fixture()
def radar_vivo(api_db):
    """Cuatro licitaciones vivas; dos hablan de consultoría y dos no."""
    from db.database import connect

    filas = [
        ("PRV-1", "Servicio de consultoría SAP", 100_000),
        ("PRV-2", "Suministro de mobiliario de oficina", 900_000),
        ("PRV-3", "Consultoría de implantación", 200_000),
        ("PRV-4", "Obras de reforma del edificio", 800_000),
    ]
    with connect() as c:
        for id_externo, titulo, importe in filas:
            c.execute(
                "INSERT INTO licitaciones (id_externo, titulo, estado, fecha_extraccion, "
                "importe, cpv, fecha_limite) "
                "VALUES (%s, %s, 'PUB', '2026-09-01', %s, '72000000', '2999-01-01')",
                (id_externo, titulo, importe),
            )


# Casi todo el peso en afinidad: con cuatro filas los percentiles de importe
# salen del propio lote, y un reparto 70/30 dejaría el orden a merced de ellos.
_PERFIL_DE_PRUEBA = {
    "weights": {"afinidad": 99, "importe": 1},
    "afinidad_keywords": ["consultoría"],
}


def test_preview_puntua_con_el_perfil_del_cuerpo(session_client, radar_vivo):
    client, csrf = session_client

    resp = client.post(
        "/api/v1/me/profile/preview",
        json=_PERFIL_DE_PRUEBA,
        headers={"X-CSRF-Token": csrf},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_scored"] == 4
    assert body["afinidad_origen"] == "perfil"
    primeras = body["opportunities"]
    assert [o["posicion"] for o in primeras] == [1, 2, 3, 4]
    # Con el peso en afinidad, las dos de consultoría pasan delante.
    assert {o["id_externo"] for o in primeras[:2]} == {"PRV-1", "PRV-3"}
    for oportunidad in primeras:
        assert {"score", "band", "score_actual", "posicion_actual"} <= oportunidad.keys()


def test_preview_no_guarda_el_perfil(session_client, radar_vivo):
    """Es una pregunta, no una escritura: tras probar, el perfil sigue vacío."""
    client, csrf = session_client

    resp = client.post(
        "/api/v1/me/profile/preview",
        json=_PERFIL_DE_PRUEBA,
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 200, resp.text

    perfil = client.get("/api/v1/me/profile").json()
    assert perfil["weights"] is None
    assert perfil["afinidad_keywords"] is None


def test_preview_sin_cambios_respecto_al_guardado_no_mueve_nada(session_client, radar_vivo):
    client, csrf = session_client
    guardar = client.put(
        "/api/v1/me/profile", json=_PERFIL_DE_PRUEBA, headers={"X-CSRF-Token": csrf}
    )
    assert guardar.status_code == 200, guardar.text

    resp = client.post(
        "/api/v1/me/profile/preview",
        json=_PERFIL_DE_PRUEBA,
        headers={"X-CSRF-Token": csrf},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["salen"] == []
    assert all(o["posicion"] == o["posicion_actual"] for o in body["opportunities"])
    assert all(o["score"] == o["score_actual"] for o in body["opportunities"])


def test_preview_respeta_el_limite(session_client, radar_vivo):
    client, csrf = session_client

    resp = client.post(
        "/api/v1/me/profile/preview?limit=2",
        json=_PERFIL_DE_PRUEBA,
        headers={"X-CSRF-Token": csrf},
    )

    assert resp.status_code == 200, resp.text
    assert len(resp.json()["opportunities"]) == 2


def test_preview_rechaza_pesos_que_no_suman_100(session_client):
    """La misma validación que el guardado: lo que no se podría guardar no se prueba."""
    client, csrf = session_client

    resp = client.post(
        "/api/v1/me/profile/preview",
        json={"weights": {"afinidad": 10, "importe": 10, "plazo": 10}},
        headers={"X-CSRF-Token": csrf},
    )

    assert resp.status_code == 422, resp.text


def test_preview_sin_universo_devuelve_listas_vacias(session_client):
    client, csrf = session_client

    resp = client.post("/api/v1/me/profile/preview", json={}, headers={"X-CSRF-Token": csrf})

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "opportunities": [],
        "salen": [],
        "total_scored": 0,
        "afinidad_origen": "ninguno",
    }


def test_preview_exige_autenticacion(client, api_db):
    resp = client.post("/api/v1/me/profile/preview", json={})

    assert resp.status_code in (401, 403)
