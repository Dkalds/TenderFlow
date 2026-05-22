"""Página Admin — Active Learning.

Revisión humana de licitaciones en zona de incertidumbre del clasificador
ML. Permite al experto etiquetar manualmente las más valiosas (mayor
importe ponderado por incertidumbre) para mejorar el modelo en el
siguiente reentrenamiento.

Acceso: sólo administradores.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from config.settings import settings
from dashboard.auth import require_admin
from dashboard.components.states import guarded_render
from dashboard.pages._base import PageContext
from db.repositories.feedback import FeedbackRepository
from observability.logging import get_logger
from services.licitaciones import load_uncertainty_zone as svc_load_uncertainty

log = get_logger(__name__)
_repo = FeedbackRepository()

_SESSION_LABELED_KEY = "al_labeled_expedientes"


@st.cache_resource(show_spinner=False)
def _load_multilabel_clf():
    """Carga TechnologyClassifier si está disponible; devuelve None si no."""
    try:
        from scraper.tech_classifier import TechnologyClassifier

        if TechnologyClassifier.is_available():
            return TechnologyClassifier.load()
    except Exception as exc:
        log.warning("active_learning.multilabel_load_failed", error=str(exc))
    return None


def _ml_label_probas(clf, titulo: str, descripcion: str) -> dict[str, float]:
    """Devuelve {tech_key: prob} para los labels del TechnologyClassifier."""
    if clf is None:
        return {}
    try:
        text = f"{titulo} {descripcion or ''}".strip()
        result = clf.predict_one(text)
        return result.get("scores", {})
    except Exception:
        return {}


def _load_uncertainty_zone(lo: float, hi: float, limit: int) -> pd.DataFrame:
    """Carga licitaciones con ml_proba en zona de incertidumbre, ordenadas por importe DESC."""
    rows = svc_load_uncertainty(lo, hi, limit)
    return pd.DataFrame(rows)


def _render_model_card() -> None:
    """Muestra una tarjeta con las métricas del TechnologyClassifier entrenado."""
    clf = _load_multilabel_clf()
    if clf is None or not clf.metadata:
        st.info("No hay histórico de entrenamientos todavía.")
        return

    meta = clf.metadata
    st.subheader("📊 Métricas del modelo multi-tecnología")
    cols = st.columns(4)
    cols[0].metric("Macro F1 (ML)", f"{meta.get('macro_f1_ml_ready', 0):.3f}")
    cols[1].metric("Modelos ML", str(meta.get("n_models", "?")))
    cols[2].metric("Rules fallback", str(meta.get("n_rules_fallback", "?")))
    cols[3].metric("Tecnologías", str(len(meta.get("labels", []))))

    cols2 = st.columns(4)
    cols2[0].metric("n_train", str(meta.get("n_train", "?")))
    cols2[1].metric("n_test", str(meta.get("n_test", "?")))
    cols2[2].metric("Total muestras", str(meta.get("n_samples", "?")))
    cols2[3].metric("", "")

    trained_at = meta.get("trained_at", "?")
    st.caption(f"Entrenado: {trained_at}")

    # Tabla de umbrales y tiers por tecnología
    tier_data = meta.get("tier", {})
    thr_data = meta.get("thresholds", {})
    if tier_data:
        with st.expander("🔬 Detalle por tecnología", expanded=False):
            rows_tech = [
                {
                    "Tecnología": lbl,
                    "Tier": tier_data.get(lbl, "?"),
                    "Threshold": f"{thr_data.get(lbl, 0):.3f}",
                }
                for lbl in meta.get("labels", [])
            ]
            st.dataframe(pd.DataFrame(rows_tech), hide_index=True)


#: Tipos de tecnología disponibles para etiquetar. Clave = valor guardado en BD, valor = etiqueta UI.
_TECH_LABELS: dict[str, str] = {
    "SAP": "🟦 SAP",
    "SALESFORCE": "☁️ Salesforce",
    "ORACLE": "🔶 Oracle",
    "MICROSOFT": "🪟 Microsoft",
    "SERVICENOW": "🟢 ServiceNow",
    "WORKDAY": "💼 Workday",
    "IBM": "🔵 IBM",
    "OPENTEXT": "📄 OpenText",
    "UNIT4": "🔷 Unit4",
    "META4": "🟣 Meta4",
    "SOPRA": "🟠 Sopra",
    "SAGE": "🟡 Sage",
    "INFOR": "⚙️ Infor",
    "Ninguna": "❌ Ninguna",
}


def _save_label(expediente: str, tech_type: str) -> None:
    """Persiste etiqueta humana vía FeedbackRepository.

    ``relevante=True`` sólo cuando la tecnología es SAP (compatible con el
    clasificador binario existente). El tipo exacto se almacena en ``nota``
    para que el clasificador multi-label pueda aprovecharlo en reentrenamiento.
    """
    relevante = tech_type == "SAP"
    nota = f"active_learning_dashboard:{tech_type}"
    _repo.insert(expediente=expediente, relevante=relevante, nota=nota)
    log.info("active_learning.label_saved", expediente=expediente, tech_type=tech_type)


@guarded_render
def render(ctx: PageContext) -> None:
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

    if _SESSION_LABELED_KEY not in st.session_state:
        st.session_state[_SESSION_LABELED_KEY] = set()

    # Recuperar expedientes ya etiquetados en BD + sesión actual
    already_labeled = _repo.labeled_expedientes() | st.session_state[_SESSION_LABELED_KEY]

    df = _load_uncertainty_zone(lo, hi, int(limit))
    if df.empty:
        st.info("No hay licitaciones en la zona de incertidumbre seleccionada.")
        return

    # Ocultar los ya etiquetados (persistidos en BD o esta sesión)
    df = df[~df["id_externo"].astype(str).isin(already_labeled)]
    if df.empty:
        st.success("¡Has etiquetado todas las licitaciones de esta cola! 🎉")
        return

    st.write(f"**{len(df)}** licitaciones en zona [{lo:.2f}, {hi:.2f}] ordenadas por importe.")

    clf = _load_multilabel_clf()

    # ── Listado con botones de etiquetado ─────────────────────────────────
    for _, row in df.head(20).iterrows():
        expediente = str(row["id_externo"])
        proba = float(row["ml_proba"]) if pd.notna(row["ml_proba"]) else 0.5
        importe = row.get("importe")
        importe_str = f"{importe:,.0f} €" if pd.notna(importe) else "—"
        titulo = str(row.get("titulo") or "")
        descripcion = str(row.get("descripcion") or "")

        # Probabilidades ML por categoría (si el multi-label clf está disponible)
        ml_probas = _ml_label_probas(clf, titulo, descripcion)

        with st.container(border=True):
            top_cols = st.columns([5, 1])
            top_cols[0].markdown(f"**{titulo}**")
            top_cols[1].markdown(f"`P(SAP)={proba:.2f}`")

            meta_cols = st.columns(4)
            meta_cols[0].caption(f"📁 {expediente}")
            meta_cols[1].caption(f"🏛 {row.get('organo_contratacion') or '—'}")
            meta_cols[2].caption(f"💰 {importe_str}")
            meta_cols[3].caption(f"🗓 {row.get('fecha_publicacion') or '—'}")

            st.caption("¿Qué tipo de tecnología es?")
            # Renderizar en filas de 7 botones para evitar desbordamiento
            _COLS_PER_ROW = 7
            items = list(_TECH_LABELS.items())
            for row_start in range(0, len(items), _COLS_PER_ROW):
                row_items = items[row_start : row_start + _COLS_PER_ROW]
                btn_cols = st.columns(len(row_items))
                for col, (tech_key, tech_label) in zip(btn_cols, row_items, strict=False):
                    # Añadir probabilidad ML al label del botón si está disponible
                    p = ml_probas.get(tech_key)
                    btn_text = f"{tech_label} {p:.0%}" if p is not None else tech_label
                    if col.button(btn_text, key=f"{tech_key.lower()}_{expediente}"):
                        _save_label(expediente, tech_type=tech_key)
                        st.session_state[_SESSION_LABELED_KEY].add(expediente)
                        st.toast(f"Etiquetado como **{tech_label}**", icon="✅")
                        st.rerun()
