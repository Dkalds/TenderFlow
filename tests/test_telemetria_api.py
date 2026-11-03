"""``POST /api/v1/telemetria/eventos`` por HTTP: autenticación y contrato.

La lógica (catálogo, filtrado, techo) está en ``tests/test_unit_eventos_producto.py``;
aquí, que la ruta exige sesión o clave y responde 204 sin cuerpo.
"""

from __future__ import annotations

_RUTA = "/api/v1/telemetria/eventos"


def test_sin_autenticacion_no_cuenta(client):
    respuesta = client.post(_RUTA, json={"evento": "espacio_abierto"})
    assert respuesta.status_code == 401


def test_con_clave_cuenta_y_no_devuelve_cuerpo(client, api_key):
    respuesta = client.post(
        _RUTA,
        json={"evento": "espacio_abierto", "propiedades": {"espacio": "radar"}},
        headers={"X-API-Key": api_key},
    )
    assert respuesta.status_code == 204
    assert respuesta.content == b""


def test_un_evento_inventado_es_422(client, api_key):
    respuesta = client.post(_RUTA, json={"evento": "inventado"}, headers={"X-API-Key": api_key})
    assert respuesta.status_code == 422
