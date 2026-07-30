"""Tests de escenarios descriptivos de precio (sin probabilidad inventada)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from services.ml.pricing_scenarios import (
    PriceScenariosResult,
    get_price_scenarios,
)


class _FakePricingRepository:
    def __init__(self, history: list[dict[str, Any]]) -> None:
        self.history = history

    def get_target(self, licitacion_id: str) -> dict[str, Any] | None:
        if licitacion_id == "MISSING":
            return None
        return {
            "id_externo": licitacion_id,
            "titulo": "Migración ERP",
            "organo_contratacion": "Órgano A",
            "cpv": "72000000",
            "importe": 100_000.0,
        }

    def load_history(self, *, limit: int = 10_000) -> list[dict[str, Any]]:
        return self.history[:limit]


def _history(n: int, *, organ: str = "Órgano A", cpv: str = "72000000") -> list[dict[str, Any]]:
    rows = []
    for index in range(n):
        discount = 0.10 + index * 0.01
        rows.append(
            {
                "licitacion_id": f"H-{index}",
                "organo_contratacion": organ,
                "cpv": cpv,
                "importe_licitacion": 100_000.0,
                "importe_adjudicado": 100_000.0 * (1.0 - discount),
                "n_ofertas_recibidas": 3,
            }
        )
    return rows


def test_price_scenarios_expose_n_quantiles_and_non_causal_copy() -> None:
    result = get_price_scenarios(
        "TARGET",
        expected_competition=3,
        repository=_FakePricingRepository(_history(40)),
    )

    assert result is not None
    assert result.sample_quality == "robusta"
    assert result.cohort == ["organo", "cpv4", "importe", "competencia"]
    assert result.distribution is not None
    assert result.distribution.n == 40
    assert result.distribution.p10_discount < result.distribution.p50_discount
    assert result.distribution.p50_discount < result.distribution.p90_discount
    assert [scenario.name for scenario in result.scenarios] == [
        "defensivo",
        "central",
        "competitivo",
    ]
    assert result.scenarios[0].price_eur > result.scenarios[-1].price_eur
    assert "NO son una P(ganar) causal" in result.disclaimer


def test_price_scenarios_relax_cohort_and_flag_small_sample() -> None:
    history = _history(3, organ="Otro órgano")
    result = get_price_scenarios(
        "TARGET",
        expected_competition=3,
        repository=_FakePricingRepository(history),
    )

    assert result is not None
    assert result.sample_quality == "insuficiente"
    assert result.cohort == ["cpv4", "importe", "competencia"]
    assert result.distribution is not None
    assert result.distribution.n == 3
    payload = result.model_dump()
    assert payload["win_probability_gate"]["available"] is False
    assert "win_probability" not in payload
    assert all("probability" not in scenario for scenario in payload["scenarios"])


def test_price_scenarios_missing_tender_returns_none() -> None:
    result = get_price_scenarios(
        "MISSING",
        repository=_FakePricingRepository([]),
    )
    assert result is None


def test_price_scenarios_api_contract(client, auth) -> None:
    payload = PriceScenariosResult(
        licitacion_id="TARGET",
        tender_amount_eur=100_000.0,
        expected_competition=3,
        cohort=["cpv4", "importe"],
        sample_quality="indicativa",
    )
    with patch("api.routes.predicciones.get_price_scenarios", return_value=payload):
        response = client.get(
            "/api/v1/licitaciones/TARGET/escenarios-precio?competencia_esperada=3",
            headers=auth,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["sample_quality"] == "indicativa"
    assert "P(ganar)" in body["disclaimer"]
