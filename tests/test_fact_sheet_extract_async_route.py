"""Rutas de extracción en background de la ficha (extract-async + estado).

La regresión que fija el 404: Schemathesis encontró que un ``id_externo``
inexistente llegaba hasta el BackgroundTask, cuyo intento de persistir el
estado ``failed`` violaba la FK de ``tender_fact_sheets`` — un 5xx. Desde S5.2
el trabajo ya no es un ``BackgroundTask`` sino una fila de la cola, pero la
guarda sigue siendo necesaria por lo mismo: el worker acabaría escribiendo ese
``failed`` contra una FK que no existe.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def ficha_client(api_db):
    """Cliente con una API key **con propietario**.

    Desde S5.2 la extracción se encola en vez de correr en un
    ``BackgroundTask``, y la fila de la cola pertenece a una organización: las
    dos rutas cuelgan de ``require_organization``, que resuelve la organización
    personal del dueño de la credencial. Una key huérfana —lo que esta fixture
    creaba— no tiene usuario del que resolverla, así que ni siquiera llegaba al
    handler: fallaba antes con un 400. Con dueño se ejercita lo que el test
    quiere fijar (el 404 del expediente inexistente y el estado por defecto).
    """
    from api.app import app
    from api.auth import create_api_key
    from db.users import create_user

    user_id = create_user(email="ficha-async@example.test", password_hash="test-hash")
    key = create_api_key("ficha-async-key", scopes="*", user_id=user_id)
    client = TestClient(app, raise_server_exceptions=False)
    client.headers.update({"X-API-Key": key})
    return client


def test_extract_async_unknown_licitacion_returns_404(ficha_client):
    resp = ficha_client.post("/api/v1/licitaciones/NO-EXISTE/ficha-pliego/extract-async")
    assert resp.status_code == 404


def test_estado_reports_not_running_by_default(ficha_client):
    resp = ficha_client.get("/api/v1/licitaciones/NO-EXISTE/ficha-pliego/estado")
    assert resp.status_code == 200
    assert resp.json()["running"] is False
