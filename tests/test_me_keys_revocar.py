"""Revocar una clave propia, y lo que el listado necesita para decidirlo.

Ajustes › Claves solo creaba y listaba: no había forma de retirar una clave
desde el producto. La única salida era borrar la cuenta entera (que revoca
todas) o esperar a que caducara. Y para decidir cuál retirar el listado no
decía cuándo se usó cada una por última vez.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.escenarios import abrir_sesion


def _crear(sesion, nombre: str = "Integración") -> tuple[int, str]:
    creada = sesion.post("/me/keys", json={"name": nombre})
    assert creada.status_code == 201, creada.text
    return int(creada.json()["id"]), str(creada.json()["api_key"])


def _maquina() -> TestClient:
    from api.app import app

    return TestClient(app, raise_server_exceptions=True)


def test_revocar_una_clave_la_apaga_y_el_listado_lo_dice(client, api_db):
    sesion = abrir_sesion("revoca@example.com", client)
    key_id, token = _crear(sesion)
    maquina = _maquina()
    assert maquina.get("/api/v1/licitaciones", headers={"X-API-Key": token}).status_code == 200

    revocada = sesion.delete(f"/me/keys/{key_id}")

    assert revocada.status_code == 204, revocada.text
    assert maquina.get("/api/v1/licitaciones", headers={"X-API-Key": token}).status_code == 401
    (fila,) = sesion.get("/me/keys").json()["items"]
    assert fila["id"] == key_id
    assert fila["is_active"] is False


def test_revocar_dos_veces_no_falla(client, api_db):
    """Pulsar dos veces o desde dos pestañas no es un error: ya está revocada."""
    sesion = abrir_sesion("dos-veces@example.com", client)
    key_id, _ = _crear(sesion)

    assert sesion.delete(f"/me/keys/{key_id}").status_code == 204
    assert sesion.delete(f"/me/keys/{key_id}").status_code == 204


def test_la_clave_de_otro_no_se_puede_revocar(client, api_db):
    """404 y no 403: distinguirlos diría si el id existe."""
    duena = abrir_sesion("duena-clave@example.com", client)
    key_id, token = _crear(duena)
    otra = abrir_sesion("otra-persona@example.com")

    assert otra.delete(f"/me/keys/{key_id}").status_code == 404
    assert otra.delete("/me/keys/999999").status_code == 404
    assert _maquina().get("/api/v1/licitaciones", headers={"X-API-Key": token}).status_code == 200


def test_una_clave_no_revoca_claves(client, api_db):
    """Con una clave filtrada no se puede tumbar la integración buena."""
    sesion = abrir_sesion("sin-sesion@example.com", client)
    buena, _ = _crear(sesion, "Buena")
    _, filtrada = _crear(sesion, "Filtrada")

    resp = _maquina().delete(f"/api/v1/me/keys/{buena}", headers={"X-API-Key": filtrada})

    assert resp.status_code in (401, 403), resp.text
    assert all(c["is_active"] for c in sesion.get("/me/keys").json()["items"])


def test_el_listado_dice_cuando_se_uso_cada_clave(client, api_db):
    sesion = abrir_sesion("ultimo-uso@example.com", client)
    usada, token = _crear(sesion, "Usada")
    quieta, _ = _crear(sesion, "Quieta")
    assert _maquina().get("/api/v1/licitaciones", headers={"X-API-Key": token}).status_code == 200

    filas = {c["id"]: c for c in sesion.get("/me/keys").json()["items"]}

    assert filas[usada]["last_used"]
    assert filas[quieta]["last_used"] is None


def test_rotar_nombra_la_nueva_en_castellano_y_sin_acumular(client, api_db):
    sesion = abrir_sesion("rota@example.com", client)
    key_id, _ = _crear(sesion, "CRM")

    assert sesion.post("/me/keys/rotate", params={"key_id": key_id}).status_code == 201
    nueva = next(c for c in sesion.get("/me/keys").json()["items"] if c["id"] != key_id)
    assert nueva["name"] == "CRM (rotada)"

    assert sesion.post("/me/keys/rotate", params={"key_id": nueva["id"]}).status_code == 201
    nombres = sorted(c["name"] for c in sesion.get("/me/keys").json()["items"])
    assert nombres == ["CRM", "CRM (rotada)", "CRM (rotada)"]
