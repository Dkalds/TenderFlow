"""Dashboard Streamlit — Licitaciones SAP del Sector Público."""

from __future__ import annotations

import json

import streamlit as st

from dashboard.auth import check_password, current_user_is_admin
from dashboard.components.layout import render_export_popover, render_notification_bell, render_sidebar_brand, render_topbar
from dashboard.components.onboarding import render_onboarding_tour
from dashboard.components.navigation import active_filters_chips, back_button, breadcrumb, sub_nav, top_nav
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
    NAV_CUR_PAGE,
    NAV_PREV_PAGE,
    NAV_PREV_SECTION,
    QP_LOADED,
)
from dashboard.theme import (
    COMPACT_DENSITY_CSS,
    TOKENS,
    build_css,
    get_color_sequence,
    register_plotly_template,
)
from observability.logging import bind_session_context, configure_logging

# ── Logging estructurado: activar antes de cualquier otra llamada ────────
configure_logging()

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

# ── M13: Accessibility — skip link + ARIA live region ─────────────────────
st.markdown(
    '<a href="#main-content" class="skip-link">Saltar al contenido</a>'
    '<div id="main-content" role="main" aria-live="polite"></div>',
    unsafe_allow_html=True,
)

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
    # Deep-link a licitación individual: ?lic=ID_EXTERNO
    if init_filters.lic_id:
        st.session_state["_lic_focus"] = init_filters.lic_id
        st.session_state["nav_section"] = "Vista General"
        st.session_state["nav_page_Vista General"] = 2  # index de "Detalle" en SECTIONS
    st.session_state[QP_LOADED] = True
# ── Sidebar: filtros (la navegación principal vive en el top-nav) ────────
with st.sidebar:
    render_sidebar_brand()
    filters: FiltersState = render_sidebar_filters(df_full)
    st.divider()
    compact = st.toggle("Modo compacto", key="density_compact", value=False)

# ── Top-nav: secciones principales ───────────────────────────────────────
_all_sections = list(SECTIONS.keys())
_visible_sections = (
    _all_sections if current_user_is_admin() else [s for s in _all_sections if s != "Ops"]
)

# Consume pending nav from back_button (must happen before widget instantiation)
_pending_nav = st.session_state.pop("_pending_nav_section", None)
if _pending_nav:
    st.session_state["nav_section"] = _pending_nav

section = top_nav(
    _visible_sections,
    icons=SECTION_ICONS,
    key="nav_section",
)

# ── Inyectar override de densidad compacta ────────────────────────────────
if compact:
    st.markdown(COMPACT_DENSITY_CSS, unsafe_allow_html=True)
# ── Aplicar filtros ─────────────────────────────────────────────────────
df = apply_filters(df_full, filters)
# ── Exportación global en topbar ────────────────────────────────────────
render_export_popover(df)
# ── Campana de notificaciones ────────────────────────────────────────────
import hashlib as _hashlib
import os as _os
from config import settings as _settings
_notif_seed = _settings.DASHBOARD_PASSWORD or _os.environ.get("COMPUTERNAME", "default")
_notif_user_key = _hashlib.sha256(_notif_seed.encode()).hexdigest()[:16]
render_notification_bell(df_full, _notif_user_key)
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

# ── Historial de navegación para botón '← Volver' ────────────────────────
_cur_tracked = st.session_state.get(NAV_CUR_PAGE)
if _cur_tracked is not None and _cur_tracked != page:
    # El usuario cambió de página: guardar la anterior como destino de vuelta
    st.session_state[NAV_PREV_PAGE] = _cur_tracked
    st.session_state[NAV_PREV_SECTION] = section
elif _cur_tracked == page:
    # Misma página: no tocar el historial (puede haber venido de otra sección)
    pass
st.session_state[NAV_CUR_PAGE] = page

breadcrumb(section, page, description=PAGE_DESCRIPTIONS.get(page))
back_button()
active_filters_chips(filters)
st.markdown("")

# ── Scroll-to-top cuando cambia la página ────────────────────────────────
st.markdown(
    "<script>window.parent.document.querySelector('[data-testid=\"stAppViewContainer\"]')"
    "?.scrollTo({top:0,behavior:'smooth'});</script>",
    unsafe_allow_html=True,
)

# ── Atajos de teclado globales ────────────────────────────────────────────
# /          → enfocar el input de búsqueda en el sidebar
# 1-5        → seleccionar la sección del top-nav correspondiente
# ?          → mostrar ayuda de atajos
_SECTION_LIST = _visible_sections
_section_list_js = json.dumps(_SECTION_LIST)
st.markdown(
    f"""
    <script>
    (function() {{
      var SECTIONS = {_section_list_js};
      var _helpVisible = false;

      function getSearchInput() {{
        var inputs = document.querySelectorAll(
          '[data-testid="stSidebarContent"] input[type="text"]'
        );
        for (var i = 0; i < inputs.length; i++) {{
          if ((inputs[i].getAttribute('placeholder') || '').indexOf('CPV') !== -1)
            return inputs[i];
        }}
        return null;
      }}

      function clickTopNavOption(idx) {{
        var radios = document.querySelectorAll(
          '[data-testid="stMainBlockContainer"] [role="radiogroup"] label'
        );
        if (radios[idx]) radios[idx].click();
      }}

      function showHelp() {{
        var existing = document.getElementById('kb-help-overlay');
        if (existing) {{ existing.remove(); _helpVisible = false; return; }}
        _helpVisible = true;
        var overlay = document.createElement('div');
        overlay.id = 'kb-help-overlay';
        overlay.style.cssText = [
          'position:fixed','top:50%','left:50%',
          'transform:translate(-50%,-50%)',
          'background:rgba(20,20,30,0.97)',
          'border:1px solid rgba(255,255,255,0.12)',
          'border-radius:12px','padding:24px 32px',
          'z-index:99999','min-width:280px',
          'font-size:0.88rem','color:#e8e8e8',
          'box-shadow:0 8px 32px rgba(0,0,0,0.6)',
          'line-height:2',
        ].join(';');
        overlay.innerHTML = [
          '<b style="font-size:1rem">Atajos de teclado</b><hr style="margin:8px 0;opacity:0.2">',
          '<kbd>/</kbd> &nbsp; Enfocar búsqueda',
          '<br><kbd>1</kbd>–<kbd>' + Math.min(SECTIONS.length, 5) + '</kbd> &nbsp; Cambiar sección',
          '<br><kbd>?</kbd> &nbsp; Mostrar/ocultar esta ayuda',
          '<br><kbd>Esc</kbd> &nbsp; Cerrar',
          '<br><br><span style="opacity:0.5;font-size:0.78rem">Haz clic fuera para cerrar</span>',
        ].join('');
        document.body.appendChild(overlay);
        overlay.addEventListener('click', function(e) {{ e.stopPropagation(); }});
        document.addEventListener('click', function closeHelp() {{
          overlay.remove(); _helpVisible = false;
          document.removeEventListener('click', closeHelp);
        }});
      }}

      document.addEventListener('keydown', function(e) {{
        var tag = (document.activeElement || {{}}).tagName || '';
        var isInput = ['INPUT','TEXTAREA','SELECT'].indexOf(tag) !== -1;

        if (e.key === 'Escape') {{
          var h = document.getElementById('kb-help-overlay');
          if (h) {{ h.remove(); _helpVisible = false; }}
          return;
        }}
        if (isInput) return;  // No interferir cuando el usuario está escribiendo

        if (e.key === '/') {{
          e.preventDefault();
          var inp = getSearchInput();
          if (inp) inp.focus();
          return;
        }}

        if (e.key === '?') {{
          showHelp();
          return;
        }}

        var n = parseInt(e.key, 10);
        if (!isNaN(n) && n >= 1 && n <= SECTIONS.length) {{
          clickTopNavOption(n - 1);
          return;
        }}
      }});
    }})();
    </script>
    """,
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

# ── Tour de onboarding (primera visita) ──────────────────────────────────
render_onboarding_tour()

# ── Footer ─────────────────────────────────────────────────────────────
