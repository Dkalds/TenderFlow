"""Rutas de extracción en background de la ficha (extract-async + estado).

La regresión que fija el 404: Schemathesis encontró que un ``id_externo``
inexistente llegaba hasta el BackgroundTask, cuyo intento de persistir el
estado ``failed`` violaba la FK de ``tender_fact_sheets`` — un 5xx.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def ficha_client(api_db):
    from api.app import app
    from api.auth import create_api_key

    key = create_api_key("ficha-async-key", scopes="*")
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
