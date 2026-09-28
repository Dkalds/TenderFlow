"""La taxonomía que el formulario de revisión de /ops ofrece (spec §3.3).

«El formulario pide `es_ti`, familias y fabricantes»: el único selector de
familias salía de las puntuaciones del ``TechnologyClassifier``, que en
producción no está publicado, así que nadie podía elegir una familia. La web no
lleva la taxonomía escrita a mano (invariante de ``web/AGENTS.md``): se la pide
a esta ruta, que la sirve entera desde ``config/keywords.py`` con su etiqueta
legible y su nivel.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from config.keywords import TECH_CATEGORIAS, TECH_LABEL_TIPO, TECH_LABELS

RUTA = "/api/v1/feedback/taxonomia"


@pytest.fixture
def client() -> Iterator[TestClient]:
    from api.app import app
    from api.routes.dual_auth import require_any_auth

    app.dependency_overrides[require_any_auth] = lambda: {"user_id": 1, "is_admin": True}
    try:
        yield TestClient(app, raise_server_exceptions=True)
    finally:
        app.dependency_overrides.clear()


def test_sirve_cada_codigo_con_su_etiqueta_y_su_nivel(client: TestClient) -> None:
    etiquetas = client.get(RUTA).json()["etiquetas"]

    assert [e["codigo"] for e in etiquetas] == TECH_LABELS
    for etiqueta in etiquetas:
        assert etiqueta["etiqueta"] == TECH_CATEGORIAS[etiqueta["codigo"]]
        assert etiqueta["tipo"] == TECH_LABEL_TIPO[etiqueta["codigo"]]
    por_codigo = {e["codigo"]: e for e in etiquetas}
    assert por_codigo["CLOUD_INFRA"] == {
        "codigo": "CLOUD_INFRA",
        "etiqueta": "Infraestructura, cloud y redes",
        "tipo": "categoria",
    }
    assert por_codigo["SAP"]["tipo"] == "fabricante"


def test_sin_credenciales_no_se_sirve() -> None:
    from api.app import app

    assert TestClient(app).get(RUTA).status_code == 401
