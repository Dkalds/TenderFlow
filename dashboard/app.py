"""Dashboard Streamlit — Licitaciones SAP del Sector Público."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the repo root is on sys.path so that `dashboard`, `db`, `config`, etc.
# are importable regardless of the working directory (e.g. Streamlit Cloud).
_REPO_ROOT = str(Path(__file__).parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import streamlit as st

from dashboard.auth import check_password
from dashboard.components.layout import render_sidebar_brand, render_topbar
from dashboard.components.navigation import active_filters_chips, breadcrumb, sub_nav, top_nav
from dashboard.components.states import empty_state
from dashboard.data_loader import load_dataframe, load_extracciones
from dashboard.filters import FiltersState, apply_filters, render_sidebar_filters
from dashboard.kpi_bar import render_kpi_bar
from dashboard.pages import PAGE_REGISTRY
from dashboard.pages._base import PageContext
from dashboard.router import PAGE_DESCRIPTIONS, PAGE_ICONS, SECTION_ICONS, SECTIONS
from dashboard.session_keys import (
    FS_CCAAS,
    FS_ESTADOS,
    FS_IMP_MIN,
    FS_ORGANOS,
    FS_Q,
    FS_RANGO,
    FS_TIPOS,
    QP_LOADED,
)
from dashboard.theme import (
    COMPACT_DENSITY_CSS,
    TOKENS,
    build_css,
    get_color_sequence,
    register_plotly_template,
)
from observability.logging import bind_session_context

# ── Config & estilo ──────────────────────────────────────────────────────
st.set_page_config(
    page_title="Licitaciones SAP · Sector Público",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Anti-flash: ocultar chrome nativo antes de que se renderice nada
st.markdown(
    "<style>"
    '#MainMenu,footer,[data-testid="stSidebarNav"],[data-testid="stSidebarNavSeparator"],'
    '[data-testid="stAppDeployButton"],[data-testid="stMainMenu"],'
    '[data-testid="stDecoration"],[data-testid="stStatusWidget"]'
    "{display:none!important;visibility:hidden!important}"
    '[data-testid="stToolbar"]{visibility:hidden!important}'
    '[data-testid="stExpandSidebarButton"]{visibility:visible!important;display:block!important}'
    "</style>",
    unsafe_allow_html=True,
)

st.markdown(build_css(TOKENS), unsafe_allow_html=True)
st.markdown(
    '<a class="skip-link" href="#main">Saltar al contenido</a>',
    unsafe_allow_html=True,
)

# ── Autenticación ────────────────────────────────────────────────────────
check_password()

# ── Correlation ID de sesión (para correlacionar logs UI↔backend) ─────────
bind_session_context()

# ── Plotly premium template ─────────────────────────────────────────────
PLOTLY_TEMPLATE = register_plotly_template(TOKENS)
COLOR_SEQUENCE = get_color_sequence(TOKENS)

# ── Carga de datos (necesaria antes del topbar para 'última actualización') ──
df_full = load_dataframe()

# ── Topbar premium (logo + meta pill + theme toggle + refresh) ───────────
_ext = load_extracciones()
last_updated = _ext["fecha"].max() if not _ext.empty else None
light_mode = render_topbar(last_updated=last_updated)

# Aplicar atributo data-theme al <html> para activar la paleta clara.
if light_mode:
    st.markdown(
        '<script>document.documentElement.setAttribute("data-theme","light");</script>'
        "<style>html{color-scheme:light}</style>",
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        '<script>document.documentElement.removeAttribute("data-theme");</script>',
        unsafe_allow_html=True,
    )

if df_full.empty:
    empty_state(
        "inbox",
        "Sin datos en la base de datos",
        "Ejecuta el pipeline para importar licitaciones.",
        cta_label="Ver comando de carga",
        cta_cb=lambda: (st.code("python -m scheduler.run_update --backfill 2024 1"), None)[1],
    )
    st.stop()
# ── Inicializar filtros desde URL params (sólo en la primera carga) ──────────────
if QP_LOADED not in st.session_state:
    init_filters = FiltersState.from_query_params(dict(st.query_params))
    if init_filters.q:
        st.session_state[FS_Q] = init_filters.q
    if init_filters.estados:
        valid_estados = set(df_full["estado_desc"].dropna().unique())
        st.session_state[FS_ESTADOS] = [e for e in init_filters.estados if e in valid_estados]
    if init_filters.ccaas:
        valid_ccaas = set(df_full["ccaa"].dropna().unique())
        st.session_state[FS_CCAAS] = [c for c in init_filters.ccaas if c in valid_ccaas]
    if init_filters.organos:
        valid_organos = set(df_full["organo_contratacion"].dropna().unique())
        st.session_state[FS_ORGANOS] = [o for o in init_filters.organos if o in valid_organos]
    if init_filters.tipos_proy:
        valid_tipos = set(df_full["tipo_proyecto"].dropna().unique())
        st.session_state[FS_TIPOS] = [t for t in init_filters.tipos_proy if t in valid_tipos]
    if init_filters.importe_min > 0:
        st.session_state[FS_IMP_MIN] = init_filters.importe_min
    if init_filters.rango:
        st.session_state[FS_RANGO] = init_filters.rango
    st.session_state[QP_LOADED] = True
# ── Sidebar: filtros (la navegación principal vive en el top-nav) ────────
with st.sidebar:
    render_sidebar_brand()
    filters: FiltersState = render_sidebar_filters(df_full)
    st.divider()
    compact = st.toggle("Modo compacto", key="density_compact", value=False)

# ── Top-nav: secciones principales ───────────────────────────────────────
section = top_nav(
    list(SECTIONS.keys()),
    icons=SECTION_ICONS,
    key="nav_section",
)

# ── Inyectar override de densidad compacta ────────────────────────────────
if compact:
    st.markdown(COMPACT_DENSITY_CSS, unsafe_allow_html=True)
# ── Aplicar filtros ─────────────────────────────────────────────────────
df = apply_filters(df_full, filters)
# ── Sincronizar filtros activos → URL (compartible) ────────────────────────
new_qp = filters.to_query_params()
cur_qp = dict(st.query_params)
if cur_qp != new_qp:
    for key in list(cur_qp):
        if key not in new_qp:
            del st.query_params[key]
    st.query_params.update(new_qp)
# ── KPI cards ───────────────────────────────────────────────────────────
render_kpi_bar(df)

st.markdown("")

# ── Sub-nav + breadcrumb ───────────────────────────────────────────────────
_pages = SECTIONS[section]
page = sub_nav(_pages, key=f"nav_page_{section}", icons=PAGE_ICONS)
breadcrumb(section, page, description=PAGE_DESCRIPTIONS.get(page))
active_filters_chips(filters)
st.markdown("")

# ── Scroll-to-top cuando cambia la página ────────────────────────────────
st.markdown(
    "<script>window.parent.document.querySelector('[data-testid=\"stAppViewContainer\"]')"
    "?.scrollTo({top:0,behavior:'smooth'});</script>",
    unsafe_allow_html=True,
)

# ── Page router ────────────────────────────────────────────────────────────
ctx = PageContext(
    df=df,
    df_full=df_full,
    filters=filters,
    tokens=TOKENS,
    plotly_template=PLOTLY_TEMPLATE,
    color_sequence=COLOR_SEQUENCE,
)


@st.fragment
def _render_page(ctx: PageContext, page: str) -> None:
    """Fragment wrapper — widget interactions inside a page don't trigger a full app rerun."""
    PAGE_REGISTRY[page](ctx)


_render_page(ctx, page)

# ── Footer ─────────────────────────────────────────────────────────────
