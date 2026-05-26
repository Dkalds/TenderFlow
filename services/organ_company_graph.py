"""Grafo bipartito Órganos ↔ Empresas.

Construye un grafo bipartito donde los nodos son órganos contratantes
y empresas adjudicatarias, y las aristas representan relaciones
contractuales con métricas de importe, conteo y frecuencia.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def build_bipartite_graph(
    adj: pd.DataFrame,
    *,
    min_contratos: int = 1,
    top_organos: int = 30,
    top_empresas: int = 30,
) -> dict[str, list[dict[str, Any]]]:
    """Construye grafo bipartito órgano ↔ empresa.

    Nodos = órganos contratantes + empresas adjudicatarias.
    Aristas = relación contractual (órgano → empresa).
    Peso = nº contratos + importe acumulado + frecuencia (contratos/año).

    Returns:
        ``{"nodes": [...], "edges": [...]}``
        Cada nodo tiene: ``name``, ``type`` ("organo"|"empresa"),
        ``degree``, ``importe_total``.
        Cada arista tiene: ``organo``, ``empresa``, ``contratos``,
        ``importe_total``, ``frecuencia_anual``.
    """
    required = {"organo_contratacion", "empresa_key", "nombre_canonico", "importe_adjudicado"}
    if not required.issubset(adj.columns):
        return {"nodes": [], "edges": []}

    dff = adj.dropna(subset=["organo_contratacion", "empresa_key"]).copy()
    if dff.empty:
        return {"nodes": [], "edges": []}

    # --- Edge aggregation ---------------------------------------------------
    has_fecha = "fecha_adjudicacion" in dff.columns
    agg_dict: dict[str, Any] = {
        "contratos": ("empresa_key", "count"),
        "importe_total": ("importe_adjudicado", "sum"),
        "empresa_nombre": ("nombre_canonico", "first"),
    }
    if has_fecha:
        agg_dict["fecha_min"] = ("fecha_adjudicacion", "min")
        agg_dict["fecha_max"] = ("fecha_adjudicacion", "max")

    edges_df = (
        dff.groupby(["organo_contratacion", "empresa_key"], dropna=True)
        .agg(**agg_dict)
        .reset_index()
    )

    # Filter by minimum contratos
    edges_df = edges_df[edges_df["contratos"] >= min_contratos]
    if edges_df.empty:
        return {"nodes": [], "edges": []}

    # Frecuencia anual: contratos / span en años (mín. 1 año)
    if has_fecha:
        span = (edges_df["fecha_max"] - edges_df["fecha_min"]).dt.days / 365.25
        span = span.clip(lower=1.0)
        edges_df["frecuencia_anual"] = (edges_df["contratos"] / span).round(2)
    else:
        edges_df["frecuencia_anual"] = edges_df["contratos"].astype(float)

    # --- Top N selection (by total importe) ---------------------------------
    organo_rank = (
        edges_df.groupby("organo_contratacion")["importe_total"].sum().nlargest(top_organos).index
    )
    empresa_rank = (
        edges_df.groupby("empresa_key")["importe_total"].sum().nlargest(top_empresas).index
    )

    edges_df = edges_df[
        edges_df["organo_contratacion"].isin(organo_rank)
        & edges_df["empresa_key"].isin(empresa_rank)
    ]
    if edges_df.empty:
        return {"nodes": [], "edges": []}

    # --- Build nodes --------------------------------------------------------
    organo_metrics = (
        edges_df.groupby("organo_contratacion")
        .agg(degree=("empresa_key", "nunique"), importe_total=("importe_total", "sum"))
        .reset_index()
    )
    empresa_metrics = (
        edges_df.groupby("empresa_key")
        .agg(
            degree=("organo_contratacion", "nunique"),
            importe_total=("importe_total", "sum"),
            nombre=("empresa_nombre", "first"),
        )
        .reset_index()
    )

    nodes: list[dict[str, Any]] = []
    for _, row in organo_metrics.iterrows():
        nodes.append(
            {
                "name": row["organo_contratacion"],
                "type": "organo",
                "degree": int(row["degree"]),
                "importe_total": float(row["importe_total"]),
            }
        )
    for _, row in empresa_metrics.iterrows():
        nodes.append(
            {
                "name": row["nombre"],
                "type": "empresa",
                "key": row["empresa_key"],
                "degree": int(row["degree"]),
                "importe_total": float(row["importe_total"]),
            }
        )

    # --- Build edges --------------------------------------------------------
    # Map empresa_key → nombre_canonico for display
    key_to_name = dict(zip(empresa_metrics["empresa_key"], empresa_metrics["nombre"], strict=False))

    edges: list[dict[str, Any]] = []
    for _, row in edges_df.iterrows():
        edges.append(
            {
                "organo": row["organo_contratacion"],
                "empresa": key_to_name.get(row["empresa_key"], row["empresa_key"]),
                "contratos": int(row["contratos"]),
                "importe_total": float(row["importe_total"]),
                "frecuencia_anual": float(row["frecuencia_anual"]),
            }
        )

    return {"nodes": nodes, "edges": edges}
