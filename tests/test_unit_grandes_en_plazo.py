"""El contador `calientes` del Resumen se documenta como «Grandes en plazo».

Cierre del P3 «Unificar la definición de Calientes» (2026-09-18): el Resumen
mantiene su heurística de importe y el nombre del campo se conserva por
contrato. Lo que se fija aquí es que las tres superficies que sirven ese número
lo describen igual en el OpenAPI, para que el cliente generado no lo confunda
con la banda `Caliente` del score.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from api.routes.notifications import HoyCounters
from services.analytics.overview import OverviewResult
from services.analytics.resumen import ResumenHoyResult
from shared.dto import DESCRIPCION_GRANDES_EN_PLAZO


@pytest.mark.parametrize(
    ("modelo", "campo"),
    [
        (ResumenHoyResult, "calientes"),
        (HoyCounters, "calientes"),
        (OverviewResult, "calientes_hoy"),
    ],
)
def test_el_campo_declara_su_definicion(modelo: type[BaseModel], campo: str) -> None:
    info = modelo.model_fields[campo]
    assert info.description == DESCRIPCION_GRANDES_EN_PLAZO
    # El default de antes: documentar no cambia el contrato.
    assert info.default == 0


def test_la_descripcion_distingue_la_banda_del_score() -> None:
    assert "Grandes en plazo" in DESCRIPCION_GRANDES_EN_PLAZO
    assert "P75" in DESCRIPCION_GRANDES_EN_PLAZO
    assert "score" in DESCRIPCION_GRANDES_EN_PLAZO
