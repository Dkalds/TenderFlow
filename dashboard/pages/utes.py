"""Página UTEs — Uniones Temporales de Empresas (apartado propio en Competencia)."""

from __future__ import annotations

from dashboard.components.states import empty_state, guarded_render
from dashboard.data_loader import load_adjudicaciones
from dashboard.pages._base import PageContext
from dashboard.pages.competidores._utes import render_utes_section


@guarded_render
def render(ctx: PageContext) -> None:
    adj = load_adjudicaciones()
    if adj.empty:
        empty_state(
            "🤝",
            "Sin datos de adjudicación",
            "El pipeline aún no ha importado adjudicaciones. "
            "Ejecuta la actualización para obtener el análisis de UTEs.",
        )
        return

    ids_filtradas = set(ctx.df["id_externo"])
    adj_ci = adj[adj["licitacion_id"].isin(ids_filtradas)].copy()

    render_utes_section(ctx, adj_ci)
