"""Tests unitarios para services/organ_company_graph.

`build_bipartite_graph` es una función pura sobre DataFrame; sin BD ni mocks.
"""

from __future__ import annotations

import pandas as pd

from services.organ_company_graph import build_bipartite_graph


def _adj_df(*, con_fechas: bool = True) -> pd.DataFrame:
    rows = [
        # ORG A ↔ EMP1: 2 contratos (2023 y 2025 → span 2 años)
        {
            "organo_contratacion": "ORG A",
            "empresa_key": "emp1",
            "nombre_canonico": "EMPRESA UNO",
            "importe_adjudicado": 100_000.0,
            "fecha_adjudicacion": "2023-01-01",
        },
        {
            "organo_contratacion": "ORG A",
            "empresa_key": "emp1",
            "nombre_canonico": "EMPRESA UNO",
            "importe_adjudicado": 200_000.0,
            "fecha_adjudicacion": "2025-01-01",
        },
        # ORG A ↔ EMP2: 1 contrato
        {
            "organo_contratacion": "ORG A",
            "empresa_key": "emp2",
            "nombre_canonico": "EMPRESA DOS",
            "importe_adjudicado": 50_000.0,
            "fecha_adjudicacion": "2024-06-01",
        },
        # ORG B ↔ EMP2: 1 contrato (el de mayor importe)
        {
            "organo_contratacion": "ORG B",
            "empresa_key": "emp2",
            "nombre_canonico": "EMPRESA DOS",
            "importe_adjudicado": 500_000.0,
            "fecha_adjudicacion": "2024-01-01",
        },
    ]
    df = pd.DataFrame(rows)
    if con_fechas:
        df["fecha_adjudicacion"] = pd.to_datetime(df["fecha_adjudicacion"])
    else:
        df = df.drop(columns=["fecha_adjudicacion"])
    return df


def test_grafo_basico_nodes_y_edges():
    result = build_bipartite_graph(_adj_df())

    organos = {n["name"]: n for n in result["nodes"] if n["type"] == "organo"}
    empresas = {n["name"]: n for n in result["nodes"] if n["type"] == "empresa"}

    assert set(organos) == {"ORG A", "ORG B"}
    assert set(empresas) == {"EMPRESA UNO", "EMPRESA DOS"}
    # ORG A conecta con 2 empresas; su importe agrega ambas aristas
    assert organos["ORG A"]["degree"] == 2
    assert organos["ORG A"]["importe_total"] == 350_000.0
    # EMPRESA DOS trabaja con 2 órganos
    assert empresas["EMPRESA DOS"]["degree"] == 2
    assert empresas["EMPRESA DOS"]["key"] == "emp2"

    edges = {(e["organo"], e["empresa"]): e for e in result["edges"]}
    assert len(edges) == 3
    arista = edges[("ORG A", "EMPRESA UNO")]
    assert arista["contratos"] == 2
    assert arista["importe_total"] == 300_000.0


def test_frecuencia_anual_con_fechas():
    """2 contratos en un span de 2 años → ~1 contrato/año."""
    result = build_bipartite_graph(_adj_df())
    edges = {(e["organo"], e["empresa"]): e for e in result["edges"]}
    assert edges[("ORG A", "EMPRESA UNO")]["frecuencia_anual"] == 1.0
    # Arista de contrato único: span clip a 1 año → frecuencia 1.0
    assert edges[("ORG B", "EMPRESA DOS")]["frecuencia_anual"] == 1.0


def test_frecuencia_anual_sin_columna_fecha():
    """Sin fecha_adjudicacion la frecuencia degrada al nº de contratos."""
    result = build_bipartite_graph(_adj_df(con_fechas=False))
    edges = {(e["organo"], e["empresa"]): e for e in result["edges"]}
    assert edges[("ORG A", "EMPRESA UNO")]["frecuencia_anual"] == 2.0


def test_filtro_min_contratos():
    result = build_bipartite_graph(_adj_df(), min_contratos=2)
    # Solo sobrevive ORG A ↔ EMP1 (2 contratos)
    assert len(result["edges"]) == 1
    assert result["edges"][0]["contratos"] == 2
    nombres = {n["name"] for n in result["nodes"]}
    assert nombres == {"ORG A", "EMPRESA UNO"}


def test_recorte_top_n_organos():
    """top_organos=1 se queda con el órgano de mayor importe (ORG B, 500k)."""
    result = build_bipartite_graph(_adj_df(), top_organos=1)
    organos = {n["name"] for n in result["nodes"] if n["type"] == "organo"}
    assert organos == {"ORG B"}
    assert [(e["organo"], e["empresa"]) for e in result["edges"]] == [("ORG B", "EMPRESA DOS")]


def test_min_contratos_sin_supervivientes():
    result = build_bipartite_graph(_adj_df(), min_contratos=99)
    assert result == {"nodes": [], "edges": []}


def test_dataframe_vacio():
    assert build_bipartite_graph(pd.DataFrame()) == {"nodes": [], "edges": []}


def test_faltan_columnas_requeridas():
    df = pd.DataFrame([{"organo_contratacion": "ORG A"}])
    assert build_bipartite_graph(df) == {"nodes": [], "edges": []}


def test_filas_con_nulos_se_descartan():
    df = _adj_df()
    df.loc[len(df)] = {
        "organo_contratacion": None,
        "empresa_key": "emp3",
        "nombre_canonico": "EMPRESA TRES",
        "importe_adjudicado": 1_000.0,
        "fecha_adjudicacion": pd.Timestamp("2024-01-01"),
    }
    result = build_bipartite_graph(df)
    empresas = {n["name"] for n in result["nodes"] if n["type"] == "empresa"}
    assert "EMPRESA TRES" not in empresas
