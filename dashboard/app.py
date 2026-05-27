"""Dashboard Streamlit â€” TenderFlow."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Streamlit Cloud puede ejecutar este archivo como script (`dashboard/app.py`).
# En ese modo, `sys.path[0]` puede quedar apuntando a `.../dashboard`, y los
# imports absolutos `from dashboard...` fallan o resuelven paquetes externos
# homÃ³nimos. Forzamos el root del repo al frente del path.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dashboard.auth import current_user_is_admin
from dashboard.bootstrap import bootstrap
from dashboard.components.keyboard_shortcuts import render_keyboard_shortcuts
from dashboard.components.layout import (
    render_export_popover,
    render_notification_bell,
    render_sidebar_brand,
    render_topbar,
)
from dashboard.components.navigation import (
    active_filters_chips,
    back_button,
    breadcrumb,
    sub_nav,
    top_nav,
)
from dashboard.components.onboarding import render_onboarding_tour
from dashboard.components.states import empty_state
from dashboard.data_loader import load_dataframe, load_extracciones
from dashboard.filters import FiltersState, apply_filters, render_sidebar_filters
from dashboard.kpi_bar import render_kpi_bar
from dashboard.pages import PAGE_REGISTRY
from dashboard.pages._base import PageContext
from dashboard.router import PAGE_DESCRIPTIONS, PAGE_ICONS, SECTION_ICONS, SECTIONS
from dashboard.routing.url_params import init_from_query_params, sync_to_query_params
from dashboard.session_keys import (
    NAV_CUR_PAGE,
    NAV_PREV_PAGE,
    NAV_PREV_SECTION,
    NAV_SECTION,
    PENDING_NAV_PAGE,
    PENDING_NAV_SECTION,
)
from dashboard.theme import (
    COMPACT_DENSITY_CSS,
    TOKENS,
    current_plotly_template,
)
from observability.histograms import timed_render

# â”€â”€ Logging estructurado: activar antes de cualquier otra llamada â”€â”€â”€â”€â”€â”€â”€â”€
configure_logging()

# â”€â”€ Config & estilo â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
st.set_page_config(
    page_title="TenderFlow Â· Sector PÃºblico",
    page_icon="ðŸ“Š",
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

# â”€â”€ AutenticaciÃ³n â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
check_password()

# â”€â”€ Correlation ID de sesiÃ³n (para correlacionar logs UIâ†”backend) â”€â”€â”€â”€â”€â”€â”€â”€â”€
bind_session_context()

# â”€â”€ Plotly premium template â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
PLOTLY_TEMPLATE = register_plotly_template(TOKENS)
COLOR_SEQUENCE = get_color_sequence(TOKENS)

# â”€â”€ Carga de datos (necesaria antes del topbar para 'Ãºltima actualizaciÃ³n') â”€â”€
with st.status("â³ Cargando datosâ€¦", expanded=False) as _load_status:
    df_full = load_dataframe()
    _load_status.update(label="Datos listos", state="complete", expanded=False)

# â”€â”€ M13: Accessibility â€” ARIA live region â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
st.markdown(
    '<div id="main-content" role="main" aria-live="polite"></div>',
    unsafe_allow_html=True,
)

# â”€â”€ Topbar premium (logo + meta pill + refresh) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_ext = load_extracciones()
last_updated = _ext["fecha"].max() if not _ext.empty else None
render_topbar(last_updated=last_updated)

if df_full.empty:
    empty_state(
        "inbox",
        "Sin datos en la base de datos",
        "Ejecuta el pipeline para importar licitaciones.",
        cta_label="Ver comando de carga",
        cta_cb=lambda: (st.code("python -m scheduler.run_update --backfill 2024 1"), None)[1],
    )
    st.stop()
# â”€â”€ Inicializar filtros desde URL params (sÃ³lo en la primera carga) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
init_from_query_params(df_full)


# â”€â”€ Sidebar: filtros (la navegaciÃ³n principal vive en el top-nav) â”€â”€â”€â”€â”€â”€â”€â”€
with st.sidebar:
    render_sidebar_brand()
    filters: FiltersState = render_sidebar_filters(df_full)
    st.divider()
    compact = st.toggle("Modo compacto", key="density_compact", value=False)

# â”€â”€ Top-nav: secciones principales â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_all_sections = list(SECTIONS.keys())
# Secciones restringidas a administradores â€” se ocultan del menÃº para usuarios normales
_ADMIN_ONLY_SECTIONS = {"Ops", "Admin"}
_visible_sections = (
    _all_sections
    if current_user_is_admin()
    else [s for s in _all_sections if s not in _ADMIN_ONLY_SECTIONS]
)

# Consume pending nav from back_button (must happen before widget instantiation)
_pending_nav = st.session_state.pop(PENDING_NAV_SECTION, None)
if _pending_nav:
    st.session_state[NAV_SECTION] = _pending_nav

# Consume pending sub-page navigation (same pattern: before sub_nav widget)
_pending_page = st.session_state.pop(PENDING_NAV_PAGE, None)
if _pending_page:
    st.session_state[_pending_page["key"]] = _pending_page["index"]

section = top_nav(
    _visible_sections,
    icons=SECTION_ICONS,
    key=NAV_SECTION,
)

# â”€â”€ Inyectar override de densidad compacta â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if compact:
    st.markdown(COMPACT_DENSITY_CSS, unsafe_allow_html=True)
# â”€â”€ Aplicar filtros â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
df = apply_filters(df_full, filters)
# â”€â”€ ExportaciÃ³n global en topbar â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
render_export_popover(df)
# â”€â”€ Campana de notificaciones â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
import hashlib as _hashlib
import os as _os

from config import settings as _settings

_notif_seed = _settings.DASHBOARD_PASSWORD.get_secret_value() or _os.environ.get(
    "COMPUTERNAME", "default"
)
_notif_user_key = _hashlib.sha256(_notif_seed.encode()).hexdigest()[:16]
render_notification_bell(df_full, _notif_user_key)
# â”€â”€ Sincronizar filtros activos â†’ URL (compartible) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
sync_to_query_params(filters)
# â”€â”€ KPI cards â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
render_kpi_bar(df)

st.markdown("")

# â”€â”€ Sub-nav + breadcrumb â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_pages = SECTIONS[section]
page = sub_nav(_pages, key=f"nav_page_{section}", icons=PAGE_ICONS)

# â”€â”€ Historial de navegaciÃ³n para botÃ³n 'â† Volver' â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_cur_tracked = st.session_state.get(NAV_CUR_PAGE)
if _cur_tracked is not None and _cur_tracked != page:
    # El usuario cambiÃ³ de pÃ¡gina: guardar la anterior como destino de vuelta
    st.session_state[NAV_PREV_PAGE] = _cur_tracked
    st.session_state[NAV_PREV_SECTION] = section
elif _cur_tracked == page:
    # Misma pÃ¡gina: no tocar el historial (puede haber venido de otra secciÃ³n)
    pass
st.session_state[NAV_CUR_PAGE] = page

breadcrumb(section, page, description=PAGE_DESCRIPTIONS.get(page))
back_button()
active_filters_chips(filters)
st.markdown("")

# â”€â”€ Scroll-to-top cuando cambia la pÃ¡gina â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
st.markdown(
    "<script>window.parent.document.querySelector('[data-testid=\"stAppViewContainer\"]')"
    "?.scrollTo({top:0,behavior:'smooth'});</script>",
    unsafe_allow_html=True,
)

# â”€â”€ Atajos de teclado globales (/, 1-5, ?, Esc) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
render_keyboard_shortcuts(_visible_sections)

# â”€â”€ Page router â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
ctx = PageContext(
    df=df,
    df_full=df_full,
    filters=filters,
    tokens=TOKENS,
    plotly_template=current_plotly_template(),
    color_sequence=COLOR_SEQUENCE,
)


@st.fragment
def _render_page(ctx: PageContext, page: str) -> None:
    """Fragment wrapper â€” widget interactions inside a page don't trigger a full app rerun."""
    with timed_render(page):
        PAGE_REGISTRY[page](ctx)


_render_page(ctx, page)

# â”€â”€ Tour de onboarding (primera visita) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
render_onboarding_tour()

# â”€â”€ Footer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
