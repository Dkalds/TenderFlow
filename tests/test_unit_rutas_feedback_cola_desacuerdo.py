"""La cola por desacuerdo, por su ruta (plan de tres niveles, F1).

La cola por incertidumbre ordena por un modelo que dice «sí» a casi todo; la
de desacuerdo pone delante lo que reglas, LLM y modelo no ven igual, que es
donde una etiqueta humana informa. Aquí se prueba la ruta sin BD: qué
estrategia llama a qué y qué forma tiene cada ítem.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

_CANDIDATO: dict[str, Any] = {
    "id_externo": "EXP-9",
    "titulo": "Manteniment del gestor documental",
    "descripcion": "",
    "cpv": "72267000-4",
    "importe": 1000.0,
    "organo_contratacion": "Ajuntament",
    "ccaa": "Cataluña",
    "fecha_publicacion": "2026-09-20",
    "url": None,
    "tecnologia": "GESTION_DOCUMENTAL",
    "ml_tecnologias": None,
    "ml_proba_max": None,
    "ml_tech_principal": None,
    "ml_proba": 0.97,
    "motivo": "llm_no_reglas_si",
    "llm_es_ti": False,
    "llm_confianza_es_ti": 0.7,
    "llm_familias": [],
}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    import api.routes.feedback as rutas
    import db.repositories.revision_ti as revision
    from api.app import app
    from api.routes.dual_auth import require_any_auth

    monkeypatch.setattr(revision, "candidatos_desacuerdo", lambda limit: [dict(_CANDIDATO)])
    monkeypatch.setattr(rutas, "_cargar_tech_classifier", lambda: None)
    app.dependency_overrides[require_any_auth] = lambda: {"user_id": 1, "is_admin": True}
    try:
        yield TestClient(app, raise_server_exceptions=True)
    finally:
        app.dependency_overrides.clear()


def test_la_cola_por_desacuerdo_trae_el_motivo_y_la_propuesta_del_llm(client: TestClient) -> None:
    cuerpo = client.get("/api/v1/feedback/queue?strategy=desacuerdo&limit=5").json()
    assert cuerpo["strategy"] == "desacuerdo"
    item = cuerpo["items"][0]
    assert item["motivo"] == "llm_no_reglas_si"
    assert item["llm"] == {"es_ti": False, "confianza_es_ti": 0.7, "familias": []}
    assert item["confidence"] == pytest.approx(0.97)
    assert item["sin_confianza"] is False


def test_sin_ml_proba_la_cola_no_inventa_confianza(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un modelo que no puntuó la licitación no tiene confianza que enseñar.
    ``confidence`` es obligatorio y ``float`` en el contrato (cambiarle el tipo
    lo rompería), así que lleva un 0,5 de relleno y ``sin_confianza`` avisa de
    que no es un dato."""
    import db.repositories.revision_ti as revision

    monkeypatch.setattr(
        revision, "candidatos_desacuerdo", lambda limit: [{**_CANDIDATO, "ml_proba": None}]
    )

    item = client.get("/api/v1/feedback/queue?strategy=desacuerdo&limit=5").json()["items"][0]

    assert item["sin_confianza"] is True
    assert item["confidence"] == pytest.approx(0.5)
    assert item["uncertainty"] == pytest.approx(0.0)
