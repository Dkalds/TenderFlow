"""Tests unitarios para services/organ_concentration.

`build_organ_concentration` es una función pura sobre DataFrame; sin BD ni mocks.
"""

from __future__ import annotations

import pandas as pd

from services.organ_concentration import build_organ_concentration


def _adj_df() -> pd.DataFrame:
    rows: list[dict] = []
    # ORG CERRADO: 1 proveedor con 5 contratos → HHI 10000, apertura Cerrado.
    for _ in range(5):
        rows.append(
            {
                "organo_contratacion": "ORG CERRADO",
                "empresa_key": "solo",
                "nombre_canonico": "SOLO SA",
                "importe_adjudicado": 1000.0,
            }
        )
    # ORG ABIERTO: 10 proveedores con importe igual → HHI 1000, apertura Abierto.
    for i in range(10):
        rows.append(
            {
                "organo_contratacion": "ORG ABIERTO",
                "empresa_key": f"emp{i}",
                "nombre_canonico": f"EMPRESA {i}",
                "importe_adjudicado": 100.0,
            }
        )
    # ORG RUIDO: solo 2 contratos → descartado por min_contratos=5.
    for _ in range(2):
        rows.append(
            {
                "organo_contratacion": "ORG RUIDO",
                "empresa_key": "ruido",
                "nombre_canonico": "RUIDO SL",
                "importe_adjudicado": 10.0,
            }
        )
    return pd.DataFrame(rows)


def test_organo_cerrado_hhi_maximo():
    res = build_organ_concentration(_adj_df())
    cerrado = next(o for o in res["organos"] if o["organo"] == "ORG CERRADO")
    assert cerrado["n_empresas"] == 1
    assert cerrado["hhi"] == 10000.0
    assert cerrado["cuota_top1"] == 100.0
    assert cerrado["apertura"] == "Cerrado"
    assert cerrado["top_empresa"] == "SOLO SA"


def test_organo_abierto_baja_concentracion():
    res = build_organ_concentration(_adj_df())
    abierto = next(o for o in res["organos"] if o["organo"] == "ORG ABIERTO")
    assert abierto["n_empresas"] == 10
    assert abierto["hhi"] == 1000.0
    assert abierto["cuota_top1"] == 10.0
    assert abierto["cuota_top3"] == 30.0
    assert abierto["apertura"] == "Abierto"


def test_min_contratos_descarta_organos_pequenos():
    res = build_organ_concentration(_adj_df(), min_contratos=5)
    organos = {o["organo"] for o in res["organos"]}
    assert "ORG RUIDO" not in organos
    # total_organos cuenta TODOS los distintos (incluido el ruido descartado).
    assert res["total_organos"] == 3


def test_orden_cerrados_primero():
    res = build_organ_concentration(_adj_df())
    # El coto más cerrado (HHI mayor) va primero.
    assert res["organos"][0]["organo"] == "ORG CERRADO"


def test_fallback_a_contratos_si_importe_cero():
    """Si el órgano no tiene importe, las cuotas se calculan por nº de contratos."""
    rows = [
        {
            "organo_contratacion": "ORG SIN IMPORTE",
            "empresa_key": f"emp{i}",
            "nombre_canonico": f"EMPRESA {i}",
            "importe_adjudicado": 0.0,
        }
        for i in range(5)
    ]
    res = build_organ_concentration(pd.DataFrame(rows), min_contratos=5)
    org = res["organos"][0]
    # 5 empresas equirepartidas por contratos → 20% cada una → HHI 2000.
    assert org["hhi"] == 2000.0
    assert org["apertura"] == "Moderado"


def test_dataframe_vacio():
    assert build_organ_concentration(pd.DataFrame()) == {"organos": [], "total_organos": 0}


def test_faltan_columnas_requeridas():
    df = pd.DataFrame([{"organo_contratacion": "ORG A"}])
    assert build_organ_concentration(df) == {"organos": [], "total_organos": 0}


def test_top_n_recorta_resultado():
    res = build_organ_concentration(_adj_df(), top_n=1)
    assert len(res["organos"]) == 1
