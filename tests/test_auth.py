"""Tests para dashboard/auth.py — rate limiting y timeout de sesión.

Nota: streamlit no tiene modo de test nativo; mockeamos st.session_state
con un dict simple y las funciones de UI con mocks no-op.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def mock_streamlit():
    """Reemplaza las llamadas a streamlit con stubs durante los tests."""
    session: dict = {}

    st_mock = MagicMock()
    st_mock.session_state = session
    # stop() debe lanzar una excepción para simular st.stop()
    st_mock.stop.side_effect = SystemExit(0)

    with patch.dict("sys.modules", {"streamlit": st_mock}):
        yield st_mock, session


def _import_auth():
    """Re-importa auth.py para que use el streamlit mockeado."""
    import importlib

    import dashboard.auth as auth_mod

    importlib.reload(auth_mod)
    return auth_mod


class TestCheckPasswordNoAuth:
    def test_sin_contraseña_devuelve_true(self, mock_streamlit):
        _st_mock, _session = mock_streamlit
        with patch("config.DASHBOARD_PASSWORD", ""):
            auth = _import_auth()
            with patch.object(auth, "_get_password", return_value=""):
                with patch.object(auth, "oauth_configured", return_value=False):
                    result = auth.check_password()
        assert result is True


class TestSessionTimeout:
    def test_sesion_reciente_no_expira(self, mock_streamlit):
        _st_mock, session = mock_streamlit
        session["authenticated"] = True
        session["_auth_time"] = time.time()

        auth = _import_auth()
        with patch.object(auth, "_get_password", return_value="secret"):
            with patch.object(auth, "SESSION_TIMEOUT_SECONDS", 3600):
                result = auth.check_password()

        assert result is True

    def test_sesion_expirada_limpia_estado(self, mock_streamlit):
        st_mock, session = mock_streamlit
        session["authenticated"] = True
        session["_auth_time"] = time.time() - 100  # 100 segundos atrás
        # El botón no está pulsado para no entrar en hmac.compare_digest
        st_mock.button.return_value = False

        auth = _import_auth()
        with patch.object(auth, "_get_password", return_value="secret"):
            with patch.object(auth, "SESSION_TIMEOUT_SECONDS", 10):
                with pytest.raises(SystemExit):
                    auth.check_password()

        assert "authenticated" not in session
        assert "_auth_time" not in session


class TestRateLimiting:
    def test_lockout_activo_llama_stop(self, mock_streamlit):
        st_mock, session = mock_streamlit
        # Simular lockout activo (expira en el futuro)
        session["_login_lockout_until"] = time.time() + 60

        auth = _import_auth()
        with patch.object(auth, "_get_password", return_value="secret"):
            with pytest.raises(SystemExit):
                auth.check_password()

        st_mock.stop.assert_called()

    def test_lockout_expirado_no_bloquea(self, mock_streamlit):
        st_mock, session = mock_streamlit
        # Lockout ya expirado
        session["_login_lockout_until"] = time.time() - 5
        # El botón no está pulsado para no entrar en hmac.compare_digest
        st_mock.button.return_value = False

        auth = _import_auth()
        with patch.object(auth, "_get_password", return_value="secret"):
            # st.stop() se llama al final del formulario (comportamiento normal)
            with pytest.raises(SystemExit):
                auth.check_password()

        # El stop NO fue por lockout — no hubo warning de espera
        warning_calls = [str(c) for c in st_mock.warning.call_args_list]
        assert not any("lockout" in c.lower() or "espera" in c.lower() for c in warning_calls)

    def test_record_failed_attempt_incrementa_contador(self, mock_streamlit):
        _st_mock, session = mock_streamlit
        auth = _import_auth()

        auth._record_failed_attempt()
        assert session["_login_attempts"] == 1

        auth._record_failed_attempt()
        assert session["_login_attempts"] == 2

    def test_lockout_activado_tras_umbral(self, mock_streamlit):
        _st_mock, session = mock_streamlit
        auth = _import_auth()

        # Simular MAX_ATTEMPTS_BEFORE_LOCKOUT intentos fallidos
        for _ in range(auth._MAX_ATTEMPTS_BEFORE_LOCKOUT):
            auth._record_failed_attempt()

        # El siguiente intento debe activar el lockout
        assert "_login_lockout_until" in session
        assert session["_login_lockout_until"] > time.time()

    def test_lockout_progresivo_crece(self, mock_streamlit):
        _st_mock, session = mock_streamlit
        auth = _import_auth()

        # Primer lockout
        for _ in range(auth._MAX_ATTEMPTS_BEFORE_LOCKOUT):
            auth._record_failed_attempt()
        lockout1 = session.get("_login_lockout_until", 0)

        # Más intentos — lockout debe ser mayor
        auth._record_failed_attempt()
        lockout2 = session.get("_login_lockout_until", 0)

        assert lockout2 > lockout1

    def test_lockout_maximo_no_supera_limite(self, mock_streamlit):
        _st_mock, session = mock_streamlit
        auth = _import_auth()

        # Simular muchos intentos fallidos
        for _ in range(20):
            auth._record_failed_attempt()

        lockout_until = session.get("_login_lockout_until", 0)
        remaining = lockout_until - time.time()
        assert remaining <= auth._MAX_LOCKOUT_SECONDS + 1  # +1 para tolerancia de tiempo


class TestAdminEnforcement:
    def test_no_user_in_session_no_admin(self, mock_streamlit):
        _st_mock, session = mock_streamlit
        # Sin _user_id en sesión
        auth = _import_auth()
        assert auth.current_user_is_admin() is False

    def test_user_with_admin_flag_is_admin(self, mock_streamlit):
        _st_mock, session = mock_streamlit
        session["_user_id"] = 42
        auth = _import_auth()
        with patch("db.users.is_admin", return_value=True):
            assert auth.current_user_is_admin() is True

    def test_user_without_admin_flag_not_admin(self, mock_streamlit):
        _st_mock, session = mock_streamlit
        session["_user_id"] = 42
        auth = _import_auth()
        with patch("db.users.is_admin", return_value=False):
            assert auth.current_user_is_admin() is False

    def test_db_error_defaults_to_not_admin(self, mock_streamlit):
        """Si la consulta a DB falla, fail-closed (no admin)."""
        _st_mock, session = mock_streamlit
        session["_user_id"] = 42
        auth = _import_auth()
        with patch("db.users.is_admin", side_effect=RuntimeError("db down")):
            assert auth.current_user_is_admin() is False

    def test_require_admin_returns_true_for_admin(self, mock_streamlit):
        _st_mock, session = mock_streamlit
        session["_user_id"] = 1
        auth = _import_auth()
        with patch("db.users.is_admin", return_value=True):
            assert auth.require_admin() is True

    def test_require_admin_shows_info_for_non_admin(self, mock_streamlit):
        st_mock, session = mock_streamlit
        session["_user_id"] = 1
        auth = _import_auth()
        with patch("db.users.is_admin", return_value=False):
            assert auth.require_admin("custom msg") is False
        st_mock.info.assert_called_once()
