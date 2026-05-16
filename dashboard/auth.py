"""Autenticación del dashboard — password y/o Google OAuth."""

from __future__ import annotations

import hashlib
import os
import time
from typing import Any

import streamlit as st

from config import settings
from dashboard.session_keys import LOGIN_PWD
from observability.logging import get_logger
from shared.auth_core import (
    csv_set as _csv_set,
    generate_oauth_state as _generate_oauth_state,
    get_signing_key as _get_signing_key,
    oauth_email_allowed as _oauth_email_allowed,
    oauth_email_is_admin as _oauth_email_is_admin,
    verify_oauth_state as _verify_oauth_state,
    verify_password as _verify_password_core,
)

log = get_logger(__name__)


def _verify_password(candidate: str) -> bool:
    """Delegado a shared.auth_core.verify_password con el hash configurado."""
    return _verify_password_core(candidate, settings.DASHBOARD_PASSWORD_HASH)


# Duración máxima de una sesión autenticada (segundos)
SESSION_TIMEOUT_SECONDS = 28_800  # 8 horas

# Número de intentos fallidos antes de activar el lockout (en session_state)
_MAX_ATTEMPTS_BEFORE_LOCKOUT = 3
# Lockout máximo independientemente del número de intentos (segundos)
_MAX_LOCKOUT_SECONDS = 60

# Rate limiting persistente: máximo de intentos fallidos en 5 minutos por cliente
_DB_MAX_ATTEMPTS = 5
_DB_WINDOW_SECONDS = 300.0

# Tiempo máximo de validez del state OAuth (10 minutos)
_OAUTH_STATE_MAX_AGE_SECONDS = 600
_SEEN_OAUTH_NONCES: dict[str, float] = {}

"""Flujos de autenticación:"""


def _client_key() -> str:
    """Genera una clave de cliente anónima basada en el session_id de Streamlit."""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx and ctx.session_id:
            return hashlib.sha256(ctx.session_id.encode()).hexdigest()[:16]
    except Exception:
        log.debug("session_id_unavailable")
    return "default"


def oauth_configured() -> bool:
    """True si las credenciales de Google OAuth están configuradas."""
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)


def _audit(action: str, detail: str = "") -> None:
    """Registra una acción en el audit log de forma best-effort."""
    try:
        import hashlib

        from db.audit import log_action

        # user_key opaco basado en la contraseña o id de sesión
        seed = settings.DASHBOARD_PASSWORD_HASH or settings.DASHBOARD_PASSWORD or "anonymous"
        user_key = hashlib.sha256(seed.encode()).hexdigest()[:16]
        session_hash = _client_key()
        log_action(user_key, session_hash, action, detail)
    except Exception:
        log.debug("audit_log_unavailable", action=action)


def _get_password() -> str:
    """Lee la contraseña desde st.secrets (Cloud) o config.py (.env / local).

    Cuando se usa ``DASHBOARD_PASSWORD_HASH`` (bcrypt), esta función sigue
    devolviendo el valor plano como referencia para el flujo de fallback.
    La verificación real la hace :func:`_verify_password`.
    """
    try:
        return st.secrets.get("DASHBOARD_PASSWORD", "") or settings.DASHBOARD_PASSWORD
    except FileNotFoundError:
        return settings.DASHBOARD_PASSWORD


def _has_password_configured() -> bool:
    """True si hay un hash bcrypt configurado (DASHBOARD_PASSWORD_HASH)."""
    return bool(settings.DASHBOARD_PASSWORD_HASH)


def _check_lockout() -> None:
    """Si hay lockout activo (session o BD), muestra aviso y detiene la ejecución."""
    from dashboard.session_keys import LOGIN_LOCKOUT_UNTIL

    # 1. Verificar lockout en session_state (fallback rápido, sin BD)
    lockout_until: float = st.session_state.get(LOGIN_LOCKOUT_UNTIL, 0.0)
    remaining_session = lockout_until - time.time()
    if remaining_session > 0:
        st.warning(
            f"Demasiados intentos fallidos. "
            f"Espera {int(remaining_session) + 1} segundos antes de intentarlo de nuevo."
        )
        st.stop()

    # 2. Verificar lockout persistente en BD (sobrevive reinicios)
    try:
        from db.rate_limits import is_login_locked_out

        locked, remaining_db = is_login_locked_out(_client_key(), max_attempts=_DB_MAX_ATTEMPTS)
        if locked:
            st.warning(
                f"Demasiados intentos fallidos desde este cliente. "
                f"Espera {int(remaining_db) + 1} segundos antes de intentarlo de nuevo."
            )
            st.stop()
    except Exception:
        log.warning(
            "rate_limit_check_failed", client_key=_client_key()
        )  # Si la BD no está disponible, continuar con session_state


def _record_failed_attempt() -> None:
    """Incrementa el contador de intentos y calcula el lockout progresivo."""
    from dashboard.session_keys import LOGIN_ATTEMPTS, LOGIN_LOCKOUT_UNTIL

    # Contador en session_state (lockout rápido dentro de la sesión)
    attempts: int = st.session_state.get(LOGIN_ATTEMPTS, 0) + 1
    st.session_state[LOGIN_ATTEMPTS] = attempts
    if attempts >= _MAX_ATTEMPTS_BEFORE_LOCKOUT:
        exponent = attempts - _MAX_ATTEMPTS_BEFORE_LOCKOUT + 1
        delay = min(2**exponent, _MAX_LOCKOUT_SECONDS)
        st.session_state[LOGIN_LOCKOUT_UNTIL] = time.time() + delay

    # Registro persistente en BD (protege frente a reinicios y nuevas sesiones)
    try:
        from db.rate_limits import record_failed_login

        record_failed_login(_client_key())
    except Exception:
        log.warning("record_failed_login_error", client_key=_client_key())


# ---------------------------------------------------------------------------
# OAuth state: delegado a shared.auth_core
# (re-export para mantener compatibilidad con código que llame directamente
#  a las funciones privadas de este módulo)
# ---------------------------------------------------------------------------


def _handle_oauth_callback() -> bool:
    """Procesa el callback de OAuth si hay code en query params.

    Valida el parámetro ``state`` mediante verificación de firma HMAC
    (no depende de ``session_state``, que puede perderse tras el redirect
    a Google) y verifica que el email de Google esté verificado.

    Returns True si el usuario queda autenticado tras el callback.
    """
    params = st.query_params
    code = params.get("code")
    if not code:
        return False

    # ── Validar state anti-CSRF (firma HMAC, sin session_state) ──────
    callback_state = params.get("state", "")
    if not _verify_oauth_state(callback_state):
        import structlog

        structlog.get_logger().warning(
            "oauth_state_invalid",
            received=bool(callback_state),
        )
        st.error("Solicitud de autenticación inválida (state mismatch). Inténtalo de nuevo.")
        st.query_params.clear()
        return False

    import requests

    # Intercambiar code por access token
    try:
        resp = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.OAUTH_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
            timeout=10,
        )
        resp.raise_for_status()
        token_data = resp.json()
    except Exception as exc:
        log.warning("oauth_token_exchange_failed", error=str(exc))
        st.error("Error al autenticar con Google. Inténtalo de nuevo.")
        st.query_params.clear()
        return False

    # Obtener info del usuario
    try:
        userinfo = requests.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
            timeout=10,
        ).json()
    except Exception as exc:
        log.warning("oauth_userinfo_failed", error=str(exc))
        st.error("Error al obtener datos del usuario.")
        st.query_params.clear()
        return False

    # ── Verificar que el email esté verificado por Google ────────────
    if not userinfo.get("email_verified", False):
        st.error("Tu cuenta de Google no tiene el email verificado. Acceso denegado.")
        st.query_params.clear()
        return False

    email = userinfo.get("email", "")
    if not _oauth_email_allowed(email):
        log.warning("oauth_email_not_allowed", email=email)
        st.error("Tu cuenta de Google no estÃ¡ autorizada para acceder a este dashboard.")
        st.query_params.clear()
        return False

    # Crear/vincular usuario en BD
    from db.users import get_or_create_oauth_user, set_admin

    user_id = get_or_create_oauth_user(
        email=email,
        oauth_provider="google",
        oauth_sub=userinfo["sub"],
        display_name=userinfo.get("name"),
    )
    if _oauth_email_is_admin(email):
        set_admin(user_id, True)

    from dashboard.session_keys import AUTH_METHOD, AUTH_TIME, USER_EMAIL, USER_ID, USER_NAME

    st.session_state[AUTH_TIME] = time.time()
    st.session_state[AUTH_METHOD] = "oauth"
    st.session_state[USER_ID] = user_id
    st.session_state[USER_EMAIL] = email
    st.session_state[USER_NAME] = userinfo.get("name", "")

    # No marcar authenticated aquí — check_password decide si falta contraseña
    # (excepto si el usuario es admin — se salta la contraseña)

    # Registrar acceso OAuth (paso 1)
    from db.users import log_access

    log_access(auth_method="oauth", user_id=user_id, email=email)

    # Limpiar code/state de la URL
    st.query_params.clear()
    return True


def _show_oauth_button() -> None:
    """Muestra el botón de inicio de sesión con Google.

    Genera un ``state`` firmado con HMAC que se envía como parámetro en la URL
    de autorización para prevenir CSRF. La firma se verifica en el callback
    sin depender de ``session_state`` (que puede perderse tras el redirect).
    """
    import urllib.parse

    state = _generate_oauth_state()

    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(
        {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": settings.OAUTH_REDIRECT_URI,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
        }
    )
    st.link_button("🔑 Iniciar sesión con Google", auth_url, use_container_width=True)


def get_current_user() -> dict[str, Any] | None:
    """Devuelve info del usuario autenticado o None.

    Claves: user_id, email, name, auth_method.
    """
    from dashboard.session_keys import AUTH_METHOD, AUTHENTICATED, USER_EMAIL, USER_ID, USER_NAME

    if not st.session_state.get(AUTHENTICATED):
        return None
    return {
        "user_id": st.session_state.get(USER_ID),
        "email": st.session_state.get(USER_EMAIL, ""),
        "name": st.session_state.get(USER_NAME, ""),
        "auth_method": st.session_state.get(AUTH_METHOD, "password"),
    }


def check_password() -> bool:
    """Autenticación en dos pasos: Google OAuth → contraseña.

    - Si hay OAuth + password: primero Google, luego pide contraseña.
    - Si solo OAuth: solo Google.
    - Si solo password: solo contraseña.
    - Sin nada: acceso libre.

    Detiene la ejecución con ``st.stop()`` si el usuario no está autenticado.
    """
    has_password = _has_password_configured()
    has_oauth = oauth_configured()

    if not has_password and not has_oauth:
        return True

    # Verificar sesión completamente autenticada y su timeout
    from dashboard.session_keys import (
        AUTH_METHOD,
        AUTH_TIME,
        AUTHENTICATED,
        OAUTH_STEP_DONE,
        USER_EMAIL,
        USER_ID,
        USER_NAME,
    )

    if st.session_state.get(AUTHENTICATED):
        auth_time: float = st.session_state.get(AUTH_TIME, 0.0)
        if time.time() - auth_time < SESSION_TIMEOUT_SECONDS:
            return True
        # Sesión expirada: limpiar estado
        for key in (
            AUTHENTICATED,
            AUTH_TIME,
            AUTH_METHOD,
            USER_ID,
            USER_EMAIL,
            USER_NAME,
            OAUTH_STEP_DONE,
        ):
            st.session_state.pop(key, None)
        st.info("Tu sesión ha expirado. Ingresa de nuevo.")

    # Procesar callback OAuth si hay code en la URL
    if has_oauth and _handle_oauth_callback():
        if has_password:
            # Si el usuario es admin, saltar la contraseña
            from db.users import is_admin as _is_admin

            user_id = st.session_state.get(USER_ID)
            if user_id and _is_admin(user_id):
                st.session_state[AUTHENTICATED] = True
                st.session_state[AUTH_METHOD] = "oauth"
            else:
                # OAuth OK, pero falta contraseña → marcar paso 1 completo
                st.session_state[OAUTH_STEP_DONE] = True
        else:
            # Solo OAuth, sin contraseña → autenticado
            st.session_state[AUTHENTICATED] = True
        st.rerun()

    # Verificar lockout activo por intentos fallidos
    _check_lockout()

    oauth_done = st.session_state.get(OAUTH_STEP_DONE, False)

    # ── Paso 2: Contraseña (tras OAuth) ──────────────────────────────
    if has_oauth and has_password and oauth_done:
        user_name = st.session_state.get(USER_NAME, "")
        greeting = f"Hola, {user_name}. " if user_name else ""
        st.markdown(f"### 🔒 {greeting}Introduce la contraseña")
        pwd = st.text_input("Contraseña", type="password", key="login_pwd")
        if st.button("Entrar", type="primary"):
            if _verify_password(pwd):
                from dashboard.session_keys import LOGIN_ATTEMPTS, LOGIN_LOCKOUT_UNTIL

                st.session_state[AUTHENTICATED] = True
                st.session_state[AUTH_TIME] = time.time()
                st.session_state[AUTH_METHOD] = "oauth+password"
                st.session_state[LOGIN_ATTEMPTS] = 0
                st.session_state.pop(LOGIN_LOCKOUT_UNTIL, None)

                # Limpiar intentos fallidos en BD
                try:
                    from db.rate_limits import clear_login_attempts

                    clear_login_attempts(_client_key())
                except Exception:
                    log.warning("clear_login_attempts_failed", client_key=_client_key())

                from db.users import log_access

                log_access(
                    auth_method="oauth+password",
                    user_id=st.session_state.get(USER_ID),
                    email=st.session_state.get(USER_EMAIL),
                )
                _audit("login", "auth_method=oauth+password")
                st.rerun()
            else:
                _record_failed_attempt()
                _audit("login_failed", "auth_method=oauth+password")
                st.error("Contraseña incorrecta.")
        st.stop()
        return False

    # ── Paso 1: Google OAuth ─────────────────────────────────────────
    if has_oauth and not oauth_done:
        st.markdown("### 🔒 Acceso restringido")
        _show_oauth_button()
        st.stop()
        return False

    # ── Solo contraseña (sin OAuth configurado) ──────────────────────
    if has_password:
        from dashboard.session_keys import LOGIN_ATTEMPTS, LOGIN_LOCKOUT_UNTIL

        st.markdown("### 🔒 Acceso restringido")
        alias = st.text_input(
            "Tu nombre (opcional)",
            value=st.session_state.get(USER_NAME, ""),
            placeholder="Escribe tu nombre o alias",
            key="_login_alias",
            help="Personaliza el saludo — no afecta al acceso.",
        )
        pwd = st.text_input("Contraseña", type="password", key=LOGIN_PWD)
        if st.button("Entrar", type="primary"):
            if _verify_password(pwd):
                st.session_state[AUTHENTICATED] = True
                st.session_state[AUTH_TIME] = time.time()
                st.session_state[AUTH_METHOD] = "password"
                st.session_state[LOGIN_ATTEMPTS] = 0
                st.session_state.pop(LOGIN_LOCKOUT_UNTIL, None)
                # Persistir alias
                if alias.strip():
                    st.session_state[USER_NAME] = alias.strip()

                # Limpiar intentos fallidos en BD
                try:
                    from db.rate_limits import clear_login_attempts

                    clear_login_attempts(_client_key())
                except Exception:
                    log.warning("clear_login_attempts_failed", client_key=_client_key())

                from db.users import log_access

                log_access(auth_method="password")
                _audit("login", "auth_method=password")
                st.rerun()
            else:
                _record_failed_attempt()
                _audit("login_failed", "auth_method=password")
                st.error("Contraseña incorrecta.")

    st.stop()
    return False  # unreachable, but satisfies mypy


# ── Authorization helpers ────────────────────────────────────────────────


def current_user_is_admin() -> bool:
    """Devuelve True si el usuario autenticado tiene flag ``is_admin``.

    Si no hay usuario en sesión (modo solo-password sin OAuth) o el ID no se
    encuentra en la tabla ``users``, devuelve False.
    """
    from dashboard.session_keys import USER_ID

    user_id = st.session_state.get(USER_ID)
    if user_id is None:
        return False
    try:
        from db.users import is_admin

        return is_admin(int(user_id))
    except Exception:  # pragma: no cover — DB errors → no admin
        return False


def require_admin(message: str = "Acción restringida a administradores.") -> bool:
    """Comprueba si el usuario es admin. Si no lo es, muestra info y devuelve False.

    Returns:
        True si admin, False en caso contrario (call site debe abortar la acción).
    """
    if current_user_is_admin():
        return True
    st.info(message, icon="🔒")
    return False
