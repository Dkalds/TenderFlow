"""Constantes centralizadas para claves de ``st.session_state``.

Evita strings mágicos dispersos por el dashboard. Si renombras una clave,
cambia solo aquí y mypy/ruff te ayudan a encontrar usos.

Convenciones de prefijos:
    fs_*    : estado de filtros del sidebar (sincronizado con URL)
    _auth_* : metadatos de la sesión autenticada
    _user_* : datos del usuario logueado vía OAuth
    _login_*: contadores y lockouts del proceso de login
    _qp_*   : flags de sincronización de query params
    _rl_*   : timestamps del rate limiter (gestionado por utils.rate_limit)
"""

from __future__ import annotations

from typing import Final

# ── Filtros (sidebar) ────────────────────────────────────────────────────
FS_Q: Final = "fs_q"
FS_RANGO: Final = "fs_rango"
FS_RANGO_B: Final = "fs_rango_b"
FS_ESTADOS: Final = "fs_estados"
FS_CCAAS: Final = "fs_ccaas"
FS_ORGANOS: Final = "fs_organos"
FS_TIPOS: Final = "fs_tipos"
FS_TECNOLOGIAS: Final = "fs_tecnologias"
FS_IMP_MIN: Final = "fs_imp_min"
FS_COMPARAR: Final = "fs_comparar"

# Tupla agrupada — usada por _clear_filters() en sidebar.py
FILTER_KEYS: Final[tuple[str, ...]] = (
    FS_Q,
    FS_RANGO,
    FS_ESTADOS,
    FS_CCAAS,
    FS_ORGANOS,
    FS_TIPOS,
    FS_TECNOLOGIAS,
    FS_IMP_MIN,
    FS_COMPARAR,
    FS_RANGO_B,
)

# ── Autenticación / sesión ───────────────────────────────────────────────
AUTHENTICATED: Final = "authenticated"
AUTH_TIME: Final = "_auth_time"
AUTH_METHOD: Final = "_auth_method"

# ── Usuario logueado ─────────────────────────────────────────────────────
USER_ID: Final = "_user_id"
USER_EMAIL: Final = "_user_email"
USER_NAME: Final = "_user_name"

# ── Flujo de login ───────────────────────────────────────────────────────
LOGIN_ATTEMPTS: Final = "_login_attempts"
LOGIN_LOCKOUT_UNTIL: Final = "_login_lockout_until"
LOGIN_PWD: Final = "login_pwd"
OAUTH_STEP_DONE: Final = "_oauth_step_done"

# ── Sincronización de query params ───────────────────────────────────────
QP_LOADED: Final = "_qp_loaded"

# ── Navegación contextual ────────────────────────────────────────────────
NAV_PREV_PAGE: Final = "_prev_page"
NAV_PREV_SECTION: Final = "_prev_section"
NAV_CUR_PAGE: Final = "_cur_page"

# ── UI / Tema ────────────────────────────────────────────────────────────
UI_LIGHT_MODE: Final = "ui_light_mode"
UI_PRESENTATION_MODE: Final = "ui_presentation_mode"
UI_THEME_CHOICE: Final = "ui_theme_choice"

# ── Navegación interna ───────────────────────────────────────────────────
NAV_SECTION: Final = "nav_section"
LIC_FOCUS: Final = "_lic_focus"

# ── Notificaciones ───────────────────────────────────────────────────────
BROWSER_NOTIF_SENT: Final = "_browser_notif_sent"

# ── Onboarding ───────────────────────────────────────────────────────────
ONBOARDING_DONE: Final = "_onboarding_done"

# ── Búsquedas recientes (sidebar) ────────────────────────────────────────
RECENT_SEARCHES: Final = "_recent_searches"

# ── Navegación pendiente (back button) ───────────────────────────────────
PENDING_NAV_SECTION: Final = "_pending_nav_section"

# ── Modo Investigador ────────────────────────────────────────────────────
INV_HISTORY: Final = "inv_history"
INV_Q: Final = "inv_q"

# ── Comparador de licitaciones ───────────────────────────────────────────
COMPARE_IDS: Final = "_compare_ids"

# ── Tracking de visita (panel "novedades") ────────────────────────────────
LAST_VISIT_TS: Final = "_last_visit_ts"
