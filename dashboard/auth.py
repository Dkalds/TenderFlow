"""Autenticación del dashboard — password y/o Google OAuth."""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

import streamlit as st

from config import DASHBOARD_PASSWORD, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, OAUTH_REDIRECT_URI
from dashboard.session_keys import LOGIN_PWD

# Duración máxima de una sesión autenticada (segundos)
SESSION_TIMEOUT_SECONDS = 28_800  # 8 horas

# Número de intentos fallidos antes de activar el lockout (en session_state)
_MAX_ATTEMPTS_BEFORE_LOCKOUT = 3
# Lockout máximo independientemente del número de intentos (segundos)
_MAX_LOCKOUT_SECONDS = 60

# Rate limiting persistente: máximo de intentos fallidos en 5 minutos por cliente
_DB_MAX_ATTEMPTS = 5
_DB_WINDOW_SECONDS = 300.0


def _client_key() -> str:
    """Genera una clave de cliente anónima basada en el session_id de Streamlit."""
    try:
        from streamlit.runtime import get_instance
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx and ctx.session_id:
            return hashlib.sha256(ctx.session_id.encode()).hexdigest()[:16]
    except Exception:
        pass
    return "default"


def oauth_configured() -> bool:
    """True si las credenciales de Google OAuth están configuradas."""
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def _get_password() -> str:
    """Lee la contraseña desde st.secrets (Cloud) o config.py (.env / local)."""
    try:
        return st.secrets.get("DASHBOARD_PASSWORD", "") or DASHBOARD_PASSWORD
    except FileNotFoundError:
        return DASHBOARD_PASSWORD


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
        pass  # Si la BD no está disponible, continuar con session_state


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
        pass


def _handle_oauth_callback() -> bool:
    """Procesa el callback de OAuth si hay code en query params.

    Returns True si el usuario queda autenticado tras el callback.
    """
    params = st.query_params
    code = params.get("code")
    if not code:
        return False

    import requests

    # Intercambiar code por access token
    try:
        resp = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": OAUTH_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
            timeout=10,
        )
        resp.raise_for_status()
        token_data = resp.json()
    except Exception:
        st.error("Error al autenticar con Google. Inténtalo de nuevo.")
        # Limpiar code de la URL
        st.query_params.clear()
        return False

    # Obtener info del usuario
    try:
        userinfo = requests.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
            timeout=10,
        ).json()
    except Exception:
        st.error("Error al obtener datos del usuario.")
        st.query_params.clear()
        return False

    # Crear/vincular usuario en BD
    from db.users import get_or_create_oauth_user

    user_id = get_or_create_oauth_user(
        email=userinfo.get("email", ""),
        oauth_provider="google",
        oauth_sub=userinfo["sub"],
        display_name=userinfo.get("name"),
    )

    from dashboard.session_keys import AUTH_METHOD, AUTH_TIME, USER_EMAIL, USER_ID, USER_NAME

    st.session_state[AUTH_TIME] = time.time()
    st.session_state[AUTH_METHOD] = "oauth"
    st.session_state[USER_ID] = user_id
    st.session_state[USER_EMAIL] = userinfo.get("email", "")
    st.session_state[USER_NAME] = userinfo.get("name", "")

    # No marcar authenticated aquí — check_password decide si falta contraseña
    # (excepto si el usuario es admin — se salta la contraseña)

    # Registrar acceso OAuth (paso 1)
    from db.users import log_access

    log_access(auth_method="oauth", user_id=user_id, email=userinfo.get("email", ""))

    # Limpiar code/state de la URL
    st.query_params.clear()
    return True


def _show_oauth_button() -> None:
    """Muestra el botón de inicio de sesión con Google."""
    import urllib.parse

    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(
        {
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": OAUTH_REDIRECT_URI,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "offline",
            "prompt": "consent",
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
    password = _get_password()
    has_oauth = oauth_configured()

    if not password and not has_oauth:
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
        if password:
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
    if has_oauth and password and oauth_done:
        user_name = st.session_state.get("_user_name", "")
        greeting = f"Hola, {user_name}. " if user_name else ""
        st.markdown(f"### 🔒 {greeting}Introduce la contraseña")
        pwd = st.text_input("Contraseña", type="password", key="login_pwd")
        if st.button("Entrar", type="primary"):
            if hmac.compare_digest(pwd, password):
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
                    pass

                from db.users import log_access

                log_access(
                    auth_method="oauth+password",
                    user_id=st.session_state.get(USER_ID),
                    email=st.session_state.get(USER_EMAIL),
                )
                st.rerun()
            else:
                _record_failed_attempt()
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
    if password:
        from dashboard.session_keys import LOGIN_ATTEMPTS, LOGIN_LOCKOUT_UNTIL

        st.markdown("### 🔒 Acceso restringido")
        pwd = st.text_input("Contraseña", type="password", key=LOGIN_PWD)
        if st.button("Entrar", type="primary"):
            if hmac.compare_digest(pwd, password):
                st.session_state[AUTHENTICATED] = True
                st.session_state[AUTH_TIME] = time.time()
                st.session_state[AUTH_METHOD] = "password"
                st.session_state[LOGIN_ATTEMPTS] = 0
                st.session_state.pop(LOGIN_LOCKOUT_UNTIL, None)

                # Limpiar intentos fallidos en BD
                try:
                    from db.rate_limits import clear_login_attempts
                    clear_login_attempts(_client_key())
                except Exception:
                    pass

                from db.users import log_access

                log_access(auth_method="password")
                st.rerun()
            else:
                _record_failed_attempt()
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
