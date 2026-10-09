"""Tests para api/routes/search.py — POST /api/v1/search/semantic (B12).

Cubre:
- Autenticación (401 sin key)
- Validación de parámetros (q vacío → 422, top_k fuera de rango → 422)
- Respuesta correcta (200 con schema SemanticSearchResponse)
- Degradación a LIKE cuando FAISS+FTS5 no devuelven resultados
- Error 503 cuando el motor falla
- Campos obligatorios en la respuesta
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def search_client(api_db, api_key):
    """TestClient con API key válida."""
    from api.app import app

    c = TestClient(app, raise_server_exceptions=False)
    c.headers.update({"X-API-Key": api_key})
    return c


# ── Helpers ───────────────────────────────────────────────────────────────────


def _patch_empty_search():
    """Parchea el motor para devolver resultados vacíos (fuerza LIKE path)."""
    return patch(
        "api.routes.search.run_ml",
        return_value=([], "LIKE"),
    )


def _patch_one_hit():
    """Parchea el motor con un único resultado."""
    hit = {
        "id_externo": "LIC-001",
        "titulo": "SAP S/4HANA implantacion",
        "organo_contratacion": "AEAT",
        "importe": 120000.0,
        "descripcion": "Proyecto SAP.",
        "url": "https://example.com/lic/001",
        "fecha_publicacion": "2026-01-01",
        "ccaa": "Madrid",
        "estado": "PUB",
        "score": 0.95,
        "fecha_limite": None,
        "tecnologia": "SAP",
        "coincide_en": ["anuncio"],
        "terminos_ausentes": [],
        "titulo_tramos": [],
        "extracto": [],
        "pasaje": None,
    }
    return patch("api.routes.search.run_ml", return_value=([hit], "FTS5"))


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestSearchAuth:
    def test_search_requires_api_key(self, client):
        """Sin API key → 401."""
        resp = client.post("/api/v1/search/semantic", json={"q": "SAP"})
        assert resp.status_code == 401

    def test_search_wrong_key_returns_401(self, client):
        resp = client.post(
            "/api/v1/search/semantic",
            json={"q": "SAP"},
            headers={"X-API-Key": "wrong"},
        )
        assert resp.status_code == 401


class TestSearchValidation:
    def test_search_missing_q_returns_422(self, search_client):
        """q es requerido → 422."""
        resp = search_client.post("/api/v1/search/semantic", json={})
        assert resp.status_code == 422

    def test_search_top_k_above_max_returns_422(self, search_client):
        resp = search_client.post("/api/v1/search/semantic", json={"q": "SAP", "top_k": 9999})
        assert resp.status_code == 422

    def test_search_alpha_out_of_range_returns_422(self, search_client):
        """alpha > 1.0 → 422."""
        resp = search_client.post("/api/v1/search/semantic", json={"q": "SAP", "alpha": 1.5})
        assert resp.status_code == 422


class TestSearchResponse:
    def test_search_empty_results_returns_200(self, search_client):
        """Sin resultados devuelve 200 con lista vacía."""
        with _patch_empty_search():
            resp = search_client.post(
                "/api/v1/search/semantic", json={"q": "término muy raro xyzzy"}
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["hits"] == []
        assert "source" in data
        assert "elapsed_ms" in data

    def test_search_response_schema(self, search_client):
        """Respuesta cumple el schema SemanticSearchResponse."""
        with _patch_one_hit():
            resp = search_client.post("/api/v1/search/semantic", json={"q": "SAP S/4HANA"})
        assert resp.status_code == 200
        data = resp.json()
        assert "q" in data
        assert "top_k" in data
        assert "source" in data
        assert "hits" in data
        assert "elapsed_ms" in data
        assert isinstance(data["hits"], list)

    def test_search_hit_has_score(self, search_client):
        """Cada hit tiene campo score."""
        with _patch_one_hit():
            resp = search_client.post("/api/v1/search/semantic", json={"q": "SAP"})
        hits = resp.json()["hits"]
        assert len(hits) == 1
        assert "score" in hits[0]
        assert 0.0 <= hits[0]["score"] <= 1.0

    def test_search_engine_error_returns_503(self, search_client):
        """Si el motor lanza excepción → 503."""
        with patch("api.routes.search.run_ml", side_effect=RuntimeError("FAISS crashed")):
            resp = search_client.post("/api/v1/search/semantic", json={"q": "SAP"})
        assert resp.status_code == 503


class TestSearchFilters:
    """Los filtros se aplican en backend, en la propia consulta: ni se fingen en
    el cliente ni se aplican después contra un conjunto de ids con tope (lo que
    hacía ``allowed_ids`` hasta 2026-10). El motor corre de verdad."""

    @staticmethod
    def _seed():
        from db.upsert import Licitacion, upsert_licitaciones

        upsert_licitaciones(
            [
                Licitacion(
                    id_externo="L1", titulo="Soporte SAP sede", ccaa="Madrid", tecnologia="SAP"
                ),
                Licitacion(
                    id_externo="L2", titulo="Soporte SAP puerto", ccaa="Cataluña", tecnologia="SAP"
                ),
                Licitacion(
                    id_externo="L3", titulo="Soporte SAP hospital", ccaa="Galicia", tecnologia="SAP"
                ),
            ]
        )

    def test_filters_restrict_to_scope(self, search_client):
        self._seed()
        resp = search_client.post(
            "/api/v1/search/semantic",
            json={"q": "soporte sap", "ccaa": ["Madrid", "Cataluña"]},
        )
        assert resp.status_code == 200
        ids = {h["id_externo"] for h in resp.json()["hits"]}
        assert ids == {"L1", "L2"}  # Galicia (L3) excluida por el filtro

    def test_no_filters_returns_all_candidates(self, search_client):
        self._seed()
        resp = search_client.post("/api/v1/search/semantic", json={"q": "soporte sap"})
        assert resp.status_code == 200
        ids = {h["id_externo"] for h in resp.json()["hits"]}
        assert ids == {"L1", "L2", "L3"}

    def test_tecnologia_filter_excludes_others(self, search_client):
        from db.upsert import Licitacion, upsert_licitaciones

        upsert_licitaciones(
            [
                Licitacion(
                    id_externo="T1", titulo="Soporte ERP", ccaa="Madrid", tecnologia="ERP,SAP"
                ),
                Licitacion(
                    id_externo="T2", titulo="Soporte ERP", ccaa="Madrid", tecnologia="ORACLE"
                ),
            ]
        )
        resp = search_client.post(
            "/api/v1/search/semantic",
            json={"q": "soporte erp", "tecnologia": ["ORACLE"]},
        )
        assert {h["id_externo"] for h in resp.json()["hits"]} == {"T2"}
        # El código se busca en el CSV de la fila: «ERP,SAP» también es SAP.
        resp = search_client.post(
            "/api/v1/search/semantic",
            json={"q": "soporte erp", "tecnologia": ["SAP"]},
        )
        assert {h["id_externo"] for h in resp.json()["hits"]} == {"T1"}

    def test_the_scope_is_applied_before_top_k(self, search_client):
        """El ámbito acota antes de recortar: con ``top_k=1`` sale el único
        expediente del ámbito aunque otros dos casen igual de bien fuera de él."""
        self._seed()
        resp = search_client.post(
            "/api/v1/search/semantic",
            json={"q": "soporte sap", "ccaa": ["Galicia"], "top_k": 1},
        )
        assert [h["id_externo"] for h in resp.json()["hits"]] == ["L3"]
