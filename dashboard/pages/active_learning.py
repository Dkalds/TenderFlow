"""Página Admin — Active Learning.

Revisión humana de licitaciones en zona de incertidumbre del clasificador
ML. Permite al experto etiquetar manualmente las más valiosas (mayor
importe ponderado por incertidumbre) para mejorar el modelo en el
siguiente reentrenamiento.

Acceso: sólo administradores.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from config.settings import settings
from dashboard.auth import require_admin
from dashboard.components.states import guarded_render
from dashboard.pages._base import PageContext
from db.database import connect
from db.repositories.feedback import FeedbackRepository
from observability.logging import get_logger

log = get_logger(__name__)
_repo = FeedbackRepository()


def _load_uncertainty_zone(lo: float, hi: float, limit: int) -> pd.DataFrame:
    """Carga licitaciones con ml_proba en zona de incertidumbre, ordenadas por importe DESC."""
    query = """
        SELECT id_externo, titulo, organo, importe, fecha_publicacion,
               cpv, es_sap, ml_proba
        FROM licitaciones
        WHERE ml_proba IS NOT NULL
          AND ml_proba BETWEEN ? AND ?
        ORDER BY (importe IS NULL), importe DESC, ml_proba
        LIMIT ?
    """
    with connect() as conn:
        cur = conn.execute(query, (lo, hi, limit))
        rows = [dict(r) for r in cur.fetchall()]
    return pd.DataFrame(rows)


def _load_registry() -> list[dict[str, Any]]:
    try:
        from scraper.ml_classifier import read_registry
        return read_registry()
    except Exception as exc:  # pragma: no cover
        log.warning("active_learning.registry_load_failed", error=str(exc))
        return []


def _render_model_card() -> None:
    """Muestra una tarjeta con las métricas del último entrenamiento."""
    registry = _load_registry()
    if not registry:
        st.info("No hay histórico de entrenamientos todavía.")
        return
    latest = registry[-1]
    st.subheader("📊 Métricas del último modelo")
    cols = st.columns(4)
    cols[0].metric("F1", f"{latest.get('f1', 0):.3f}")
    cols[1].metric(
        f"F-β (β={latest.get('beta', 1.0)})",
        f"{latest.get('fbeta', latest.get('f1', 0)):.3f}",
    )
    cols[2].metric("PR-AUC", f"{latest.get('pr_auc', 0):.3f}")
    cols[3].metric("Threshold", f"{latest.get('optimal_threshold', 0):.2f}")

    cols2 = st.columns(4)
    cols2[0].metric("Precision", f"{latest.get('precision', 0):.3f}")
    cols2[1].metric("Recall", f"{latest.get('recall', 0):.3f}")
    cols2[2].metric("Brier", f"{latest.get('brier', 0):.4f}", help="Menor = mejor")
    cols2[3].metric("ECE", f"{latest.get('ece', 0):.4f}", help="Calibration error")

    trained_at = latest.get("trained_at", "?")
    st.caption(f"Entrenado: {trained_at} · n_train={latest.get('n_train', '?')} · n_test={latest.get('n_test', '?')}")

    # Mini-histórico (máx. 10 entrenamientos recientes)
    if len(registry) >= 2:
        with st.expander("📈 Histórico de entrenamientos", expanded=False):
            df_hist = pd.DataFrame(registry[-10:])
            keep = [c for c in ["trained_at", "f1", "fbeta", "pr_auc", "brier", "optimal_threshold", "n_train"] if c in df_hist.columns]
            st.dataframe(df_hist[keep], width="stretch", hide_index=True)


def _save_label(expediente: str, es_sap: bool) -> None:
    """Persiste etiqueta humana vía FeedbackRepository."""
    nota = "active_learning_dashboard"
    _repo.insert(expediente=expediente, relevante=es_sap, nota=nota)
    log.info("active_learning.label_saved", expediente=expediente, es_sap=es_sap)


@guarded_render
def render(ctx: PageContext) -> None:  # noqa: ARG001
    require_admin()
    st.title("🎯 Active Learning")
    st.caption(
        "Etiqueta manualmente las licitaciones donde el modelo está menos seguro. "
        "Tu feedback se usa en el siguiente reentrenamiento para mejorar precision y recall."
    )

    _render_model_card()
    st.divider()

    # ── Controles de zona de incertidumbre ────────────────────────────────
    st.subheader("Cola de revisión")
    col_lo, col_hi, col_lim = st.columns(3)
    lo = col_lo.slider(
        "Umbral inferior",
        min_value=0.05,
        max_value=0.50,
        value=float(settings.ML_UNCERTAINTY_LO),
        step=0.05,
    )
    hi = col_hi.slider(
        "Umbral superior",
        min_value=0.50,
        max_value=0.95,
        value=float(settings.ML_UNCERTAINTY_HI),
        step=0.05,
    )
    limit = col_lim.number_input("Máx. resultados", min_value=10, max_value=200, value=50, step=10)

    df = _load_uncertainty_zone(lo, hi, int(limit))
    if df.empty:
        st.info("No hay licitaciones en la zona de incertidumbre seleccionada.")
        return

    st.write(f"**{len(df)}** licitaciones en zona [{lo:.2f}, {hi:.2f}] ordenadas por importe.")

    # ── Listado con botones de etiquetado ─────────────────────────────────
    for _, row in df.head(20).iterrows():
        expediente = str(row["id_externo"])
        proba = float(row["ml_proba"]) if pd.notna(row["ml_proba"]) else 0.5
        importe = row.get("importe")
        importe_str = f"{importe:,.0f} €" if pd.notna(importe) else "—"

        with st.container(border=True):
            top_cols = st.columns([5, 1])
            top_cols[0].markdown(f"**{row['titulo']}**")
            top_cols[1].markdown(f"`P(SAP)={proba:.2f}`")

            meta_cols = st.columns(4)
            meta_cols[0].caption(f"📁 {expediente}")
            meta_cols[1].caption(f"🏛 {row.get('organo') or '—'}")
            meta_cols[2].caption(f"💰 {importe_str}")
            meta_cols[3].caption(f"🗓 {row.get('fecha_publicacion') or '—'}")

            btn_cols = st.columns([1, 1, 4])
            if btn_cols[0].button("✅ Es SAP", key=f"sap_{expediente}"):
                _save_label(expediente, es_sap=True)
                st.success(f"Etiquetado como SAP: {expediente}")
                st.rerun()
            if btn_cols[1].button("❌ No es SAP", key=f"nosap_{expediente}"):
                _save_label(expediente, es_sap=False)
                st.success(f"Etiquetado como NO-SAP: {expediente}")
                st.rerun()
