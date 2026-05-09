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
OAUTH_STATE: Final = "_oauth_state"

# ── Sincronización de query params ───────────────────────────────────────
QP_LOADED: Final = "_qp_loaded"

# ── Widgets internos del dashboard ───────────────────────────────────────
DLQ_PICK: Final = "dlq_pick"
