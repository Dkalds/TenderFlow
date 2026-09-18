"""El interruptor ``COMPETITORS_IDENTITY_SQL`` elige camino, sin BD.

La paridad SQL↔pandas se mide contra Postgres en
``tests/test_analytics_competitors_identity_sql.py``. Aquí solo se fija el
cableado: apagado (el defecto) no toca la BD, y encendido entrega al
repositorio las filas que ya se cargaron, con la política de NIF del servicio
y sin normalizar — la normalización es trabajo del SQL.

No vive en ``tests/test_analytics_competitors.py`` a propósito: el test de
paridad reejecuta cada ``test_*`` de ese fichero con el interruptor encendido,
y estos, que ya lo manipulan, no deben entrar en ese bucle.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from config import settings
from services.analytics import competitors
from services.analytics.competitors import CompetitorFilters, get_competitors

_LOAD = "services.analytics.competitors.load_for_competitors"
_RESOLVER = "db.repositories.competitor_identity.resolve_identity_for_rows"


def _filas() -> list[dict[str, Any]]:
    return [
        {
            "licitacion_id": "L1",
            "nombre": "INDRA SISTEMAS, S.A.",
            "nif": "A-28599033",
            "importe_adjudicado": 30000.0,
        },
        {
            "licitacion_id": "L2",
            "nombre": "MINSAIT BUSINESS CONSULTING, S.L.",
            "nif": "A28599033",
            "empresa_id": 7,
            "empresa_nombre_master": "Minsait",
            "empresa_grupo_id": 3,
            "importe_adjudicado": 50000.0,
        },
        {
            "licitacion_id": "L3",
            "nombre": "Empresa Norte, S.L.",
            "nif": "N/A",
            "importe_adjudicado": 10000.0,
        },
    ]


def test_apagado_por_defecto_no_llama_al_sql() -> None:
    assert settings.COMPETITORS_IDENTITY_SQL is False
    with patch(_LOAD, return_value=_filas()), patch(_RESOLVER) as resolver:
        result = get_competitors(CompetitorFilters())
    resolver.assert_not_called()
    # Indra y Minsait comparten NIF; Norte va sola.
    assert result.total_empresas == 2


def test_encendido_entrega_las_filas_cargadas_sin_normalizar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "COMPETITORS_IDENTITY_SQL", True)
    # El repositorio devuelve la partición: las dos primeras juntas.
    with (
        patch(_LOAD, return_value=_filas()),
        patch(_RESOLVER, return_value=["nif:A28599033", "nif:A28599033", "fila:2"]) as resolver,
    ):
        result = get_competitors(CompetitorFilters())

    resolver.assert_called_once()
    kwargs = resolver.call_args.kwargs
    # El maestro gana al nombre crudo, igual que en pandas; sin normalizar.
    assert kwargs["nombres"] == [
        "INDRA SISTEMAS, S.A.",
        "Minsait",
        "Empresa Norte, S.L.",
    ]
    assert kwargs["nifs"] == ["A-28599033", "A28599033", "N/A"]
    assert kwargs["empresa_ids"] == [None, 7, None]
    assert kwargs["grupo_ids"] == [None, 3, None]
    # La política de negocio viaja como parámetro (db/ no importa services/).
    assert "N/A" in kwargs["placeholder_nifs"]
    assert kwargs["curated_groups"]["B81690471"] == "deloitte"

    assert result.total_empresas == 2
    agrupado = next(c for c in result.competitors if c.count == 2)
    assert agrupado.es_agrupacion is True


def test_la_politica_curada_es_la_del_servicio() -> None:
    """``curated_groups`` se deriva de ``_CURATED_GROUPS_BY_NIF``: una sola copia."""
    esperado = {nif: key for nif, (key, _n) in competitors._CURATED_GROUPS_BY_NIF.items()}
    with patch(_RESOLVER, return_value=["a"]) as resolver:
        competitors._sql_identity_keys(
            pd.DataFrame({"_empresa_id_key": [None]}),
            pd.Series(["X"]),
            pd.Series([None]),
        )
    assert resolver.call_args.kwargs["curated_groups"] == esperado
