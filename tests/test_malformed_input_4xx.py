"""Entradas malformadas devuelven 4xx, no 5xx.

Las tres operaciones que cubre este módulo estaban congeladas en ``KNOWN_5XX``
(``scripts/fuzz_api_contract.py``): bastaba un carácter enviado por cualquier
cliente para provocar un 500.

- ``\\x00`` en una cadena viajaba hasta Postgres, que no lo admite en columnas
  de texto, y su ``DataError`` salía como 500 (``POST /licitaciones/bulk-get``
  y ``PUT /feature-flags``).
- Bytes que no son UTF-8 válido en el path (``%ff``) rompían la decodificación
  antes de que la ruta llegara a ejecutarse
  (``DELETE /watchlist/items/{id_externo}``).

El saneo del cuerpo vive en el contrato (``shared.dto.SafeStr``) y no en cada
endpoint: es una decisión de diseño, no un parche por ruta.
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
