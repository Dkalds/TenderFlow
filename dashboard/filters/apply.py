"""Aplica FiltersState a un DataFrame de licitaciones."""

from __future__ import annotations

import pandas as pd

from dashboard.filters.state import FiltersState


def apply_filters(df: pd.DataFrame, state: FiltersState) -> pd.DataFrame:
    result = df.copy()
    if state.q:
        mask = result["titulo"].str.contains(state.q, case=False, na=False) | result[
            "descripcion"
        ].str.contains(state.q, case=False, na=False)
        result = result[mask]
    if state.rango and isinstance(state.rango, tuple) and len(state.rango) == 2:
        result = result[
            (result["fecha_publicacion"].dt.date >= state.rango[0])
            & (result["fecha_publicacion"].dt.date <= state.rango[1])
        ]
    if state.estados:
        result = result[result["estado_desc"].isin(state.estados)]
    if state.ccaas:
        result = result[result["ccaa"].isin(state.ccaas)]
    if state.organos:
        result = result[result["organo_contratacion"].isin(state.organos)]
    if state.tipos_proy:
        result = result[result["tipo_proyecto"].isin(state.tipos_proy)]
    if state.tecnologias and "tecnologia" in result.columns:
        # tecnologia puede ser multi-valor ("SAP,ORACLE"), filtrar si contiene alguna
        mask = result["tecnologia"].fillna("").apply(
            lambda t: any(tech in t.split(",") for tech in state.tecnologias)
        )
        result = result[mask]
    if state.importe_min > 0:
        result = result[result["importe"].fillna(0) >= state.importe_min]
    return result
