"""Página Comparador — diff side-by-side de 2-3 licitaciones."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.components.states import empty_state, guarded_render
from dashboard.pages._base import PageContext
from dashboard.utils.format import fmt_eur


_COMPARE_FIELDS = [
    ("id_externo", "Expediente"),
    ("titulo", "Título"),
    ("organo_contratacion", "Órgano contratante"),
    ("importe", "Importe (€)"),
    ("estado_desc", "Estado"),
    ("fecha_publicacion", "Fecha publicación"),
    ("fecha_limite", "Fecha límite"),
    ("ccaa", "CCAA"),
    ("cpv", "CPV"),
    ("tipo_proyecto", "Tipo proyecto"),
    ("tecnologia", "Tecnología"),
    ("descripcion", "Descripción"),
]


def _highlight_diff(val: str, baseline: str | None) -> str:
    """Retorna HTML con fondo amarillo si el valor difiere del baseline."""
    if baseline is None or str(val) == str(baseline):
        return str(val) if pd.notna(val) else "—"
    return f'<span style="background:#ff6b6b22;border-radius:4px;padding:2px 6px">{val if pd.notna(val) else "—"}</span>'


@guarded_render
def render(ctx: PageContext) -> None:
    df = ctx.df

    st.subheader("🔀 Comparador de licitaciones")
    st.caption("Selecciona 2 o 3 expedientes para comparar sus campos en paralelo.")

    if df.empty:
        empty_state("search", "Sin datos disponibles", "Ajusta los filtros activos.")
        return

    options = df["id_externo"].dropna().unique().tolist()
    if len(options) < 2:
        st.info("Se necesitan al menos 2 licitaciones en los filtros activos.")
        return

    sel = st.multiselect(
        "Expedientes a comparar",
        options=options,
        max_selections=3,
        placeholder="Busca por ID de expediente…",
        help="Puedes comparar hasta 3 expedientes simultáneamente.",
    )

    if len(sel) < 2:
        st.info("Selecciona al menos 2 expedientes para activar el comparador.")
        return

    rows = df[df["id_externo"].isin(sel)].set_index("id_externo")

    # ── Build comparison table ──────────────────────────────────────────────
    table_rows: list[dict] = []
    for field_key, field_label in _COMPARE_FIELDS:
        if field_key not in rows.columns:
            continue
        values = {eid: rows.at[eid, field_key] if eid in rows.index else None for eid in sel}
        # Format importe
        if field_key == "importe":
            values = {
                k: fmt_eur(v) if pd.notna(v) and v is not None else "—"
                for k, v in values.items()
            }
        row: dict = {"Campo": field_label}
        baseline_val = list(values.values())[0]
        for eid, val in values.items():
            row[eid] = _highlight_diff(val, baseline_val if eid != sel[0] else None)
        table_rows.append(row)

    cmp_df = pd.DataFrame(table_rows).set_index("Campo")

    st.markdown(
        cmp_df.to_html(escape=False, classes="compare-table"),
        unsafe_allow_html=True,
    )

    # ── Importe bar chart ───────────────────────────────────────────────────
    import_rows = df[df["id_externo"].isin(sel) & df["importe"].notna()][["id_externo", "importe", "titulo"]]
    if not import_rows.empty:
        import plotly.express as px

        import_rows["label"] = import_rows["id_externo"] + " – " + import_rows["titulo"].str[:40]
        fig = px.bar(
            import_rows,
            x="importe",
            y="label",
            orientation="h",
            template=ctx.plotly_template,
            color_discrete_sequence=ctx.color_sequence,
            labels={"importe": "Importe (€)", "label": ""},
            title="Comparativa de importes",
        )
        fig.update_layout(height=250 + 60 * len(sel), margin=dict(l=0, r=20, t=40, b=0))
        st.plotly_chart(fig, use_container_width=True)

    # ── Minimal inline CSS for comparison table ────────────────────────────
    st.markdown(
        """
        <style>
        .compare-table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
        .compare-table th, .compare-table td {
            border: 1px solid rgba(255,255,255,0.08);
            padding: 6px 10px; text-align: left;
        }
        .compare-table th { background: rgba(255,255,255,0.05); font-weight: 600; }
        .compare-table tr:hover td { background: rgba(255,255,255,0.03); }
        </style>
        """,
        unsafe_allow_html=True,
    )
