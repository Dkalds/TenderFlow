"""Cambiar la contraseña: desde Ajustes con la actual, o con el enlace del correo.

Backlog «Recuperación de contraseña», puntos 3, 4 y 5:

- (3) ``POST /auth/password/change`` pide la contraseña actual, deja viva la
  sesión que hace el cambio y cierra las demás.
- (4) Las dos formas de cambiarla desactivan las claves de API de la cuenta: una
  creada por quien tuviera la cuenta no puede sobrevivir a que el titular la
  recupere.
- (5) Las dos avisan al titular por correo, sin ningún token en el aviso.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.app import app
from tests.escenarios import PASSWORD, abrir_sesion

_CHANGE = "/api/v1/auth/password/change"
_CONFIRM = "/api/v1/auth/password-reset/confirm"
_LOGIN = "/api/v1/auth/login"
_NUEVA = "OtraClave-2026-Segura"  # pragma: allowlist secret # gitleaks:allow
_CUALQUIERA = "Cualquiera-2026"  # pragma: allowlist secret # gitleaks:allow
_TOKEN = "tok_-" + "x" * 38
_ORIGEN = "https://app.example"


@pytest.fixture()
def origen_frontend(monkeypatch: pytest.MonkeyPatch) -> str:
    from services import app_urls

    monkeypatch.setattr(app_urls.settings, "CORS_ALLOWED_ORIGINS", _ORIGEN, raising=False)
    monkeypatch.setattr(app_urls.settings, "OAUTH_REDIRECT_URI", "", raising=False)
    return _ORIGEN


def _claves_activas(user_id: int) -> int:
    from db.database import connect

    with connect() as c:
        fila = c.execute(
            "SELECT count(*) FROM api_keys WHERE user_id = %s AND is_active = 1", (user_id,)
        ).fetchone()
    return int(fila[0])


def _cambiar(sesion: Any, actual: str, nueva: str) -> Any:
    return sesion.post(
        "/auth/password/change", json={"current_password": actual, "new_password": nueva}
    )


# ---------------------------------------------------------------------------
# Contra el SQL real
# ---------------------------------------------------------------------------


def test_el_reset_desactiva_las_claves_de_api(tmp_db):
    from api.auth import create_api_key
    from db.password_reset import consume_reset_token, create_reset_token_for_email
    from db.users import create_user
    from services.password_reset import token_hash

    email = "claves@example.test"
    user_id = create_user(email=email, password_hash="hash-anterior")  # pragma: allowlist secret
    create_api_key("integración", user_id=user_id)
    create_api_key("otra", user_id=user_id)
    ajeno = create_user(
        email="ajeno@example.test",
        password_hash="hash-ajeno",  # pragma: allowlist secret
    )  # pragma: allowlist secret
    create_api_key("del vecino", user_id=ajeno)
    digest = token_hash("token-claves-" + "x" * 32)
    assert create_reset_token_for_email(email, digest, "2999-01-01T00:00:00+00:00") is True

    assert consume_reset_token(digest, "hash-nuevo") == user_id  # pragma: allowlist secret

    assert _claves_activas(user_id) == 0
    assert _claves_activas(ajeno) == 1


def test_el_cambio_deja_la_sesion_actual_y_revoca_lo_demas(tmp_db):
    from api.auth import create_api_key
    from db.database import connect
    from db.password_reset import change_password, create_reset_token_for_email
    from db.sessions import create_session, validate_session_principal
    from db.users import create_user
    from services.password_reset import token_hash

    email = "cambio@example.test"
    user_id = create_user(email=email, password_hash="hash-anterior")  # pragma: allowlist secret
    actual = create_session(user_id)
    otra = create_session(user_id)
    create_api_key("integración", user_id=user_id)
    digest = token_hash("token-pendiente-" + "x" * 32)
    assert create_reset_token_for_email(email, digest, "2999-01-01T00:00:00+00:00") is True

    assert (
        change_password(user_id, "hash-nuevo", sesion_actual=actual) == 1
    )  # pragma: allowlist secret

    assert validate_session_principal(actual) is not None
    assert validate_session_principal(otra) is None
    assert _claves_activas(user_id) == 0
    with connect() as c:
        (hash_guardado,) = c.execute(
            "SELECT password_hash FROM users WHERE id = %s", (user_id,)
        ).fetchone()
        (usado,) = c.execute(
            "SELECT used_at FROM password_reset_tokens WHERE token_hash = %s", (digest,)
        ).fetchone()
    assert hash_guardado == "hash-nuevo"  # pragma: allowlist secret
    # Un enlace pedido antes del cambio ya no sirve para deshacerlo.
    assert usado is not None


def test_el_cambio_no_toca_una_cuenta_desactivada(tmp_db):
    from db.password_reset import change_password
    from db.sessions import create_session
    from db.users import create_user, deactivate_user

    user_id = create_user(
        email="baja@example.test",
        password_hash="hash-anterior",  # pragma: allowlist secret
    )  # pragma: allowlist secret
    sesion = create_session(user_id)
    deactivate_user(user_id)

    assert (
        change_password(user_id, "hash-nuevo", sesion_actual=sesion) is None
    )  # pragma: allowlist secret


# ---------------------------------------------------------------------------
# Por HTTP
# ---------------------------------------------------------------------------


def test_cambio_por_http_cierra_lo_demas_y_avisa(client, origen_frontend):
    sesion = abrir_sesion("cambiar@example.com", client)
    otro_equipo = TestClient(app)
    assert (
        otro_equipo.post(_LOGIN, json={"email": sesion.email, "password": PASSWORD}).status_code
        == 200
    )
    clave = sesion.post("/me/keys", json={"name": "Integración"}).json()["api_key"]

    with patch("services.password_reset.enviar_email_transaccional", return_value=True) as enviar:
        cambio = _cambiar(sesion, PASSWORD, _NUEVA)

    assert cambio.status_code == 200, cambio.text
    # La sesión que cambia sigue; la del otro equipo y la clave, no.
    assert sesion.get("/auth/me").status_code == 200
    assert otro_equipo.get("/api/v1/auth/me").status_code == 401
    maquina = TestClient(app)
    assert maquina.get("/api/v1/licitaciones", headers={"X-API-Key": clave}).status_code == 401
    # La contraseña vieja ya no entra; la nueva, sí.
    assert (
        maquina.post(_LOGIN, json={"email": sesion.email, "password": PASSWORD}).status_code == 401
    )
    assert maquina.post(_LOGIN, json={"email": sesion.email, "password": _NUEVA}).status_code == 200

    # El aviso al titular, sin token y con la pantalla para pedir uno.
    enviar.assert_called_once()
    campos = enviar.call_args.kwargs
    assert campos["to_addr"] == sesion.email
    assert campos["subject"] == "Tu contraseña de TenderFlow ha cambiado"
    assert f"{_ORIGEN}/restablecer-contrasena" in campos["texto"]
    assert "token" not in campos["texto"] + campos["html"]

    from db.database import connect

    with connect() as c:
        fila = c.execute(
            "SELECT user_id, detail FROM audit_log WHERE action = 'auth.password_changed'"
        ).fetchone()
    assert fila is not None
    assert int(fila[0]) == sesion.user_id
    assert _NUEVA not in str(fila[1])


def test_la_contrasena_actual_equivocada_no_cambia_nada(client):
    sesion = abrir_sesion("equivocada@example.com", client)

    with patch("services.password_reset.enviar_email_transaccional") as enviar:
        respuesta = _cambiar(sesion, "No-Es-La-2026", _NUEVA)

    assert respuesta.status_code == 400
    assert respuesta.json()["detail"] == "La contraseña actual no es correcta."
    enviar.assert_not_called()
    assert (
        client.post(_LOGIN, json={"email": sesion.email, "password": PASSWORD}).status_code == 200
    )


def test_la_nueva_pasa_por_la_politica_del_alta(client):
    sesion = abrir_sesion("politica@example.com", client)

    respuesta = _cambiar(sesion, PASSWORD, "sinmayusculas2026")

    assert respuesta.status_code == 400
    assert "contraseña" in respuesta.json()["detail"]


def test_cinco_fallos_bloquean_aunque_la_sexta_sea_buena(client, monkeypatch):
    from services.rate_limiting import DbRateLimiter

    monkeypatch.setattr("services.rate_limiting.get_rate_limiter", lambda: DbRateLimiter())
    sesion = abrir_sesion("bloqueo@example.com", client)

    for _ in range(5):
        assert _cambiar(sesion, "No-Es-La-2026", _NUEVA).status_code == 400
    bloqueado = _cambiar(sesion, PASSWORD, _NUEVA)

    assert bloqueado.status_code == 429
    assert int(bloqueado.headers["Retry-After"]) >= 1


def test_sin_csrf_no_se_cambia(client):
    sesion = abrir_sesion("csrf@example.com", client)

    respuesta = client.post(_CHANGE, json={"current_password": PASSWORD, "new_password": _NUEVA})

    assert respuesta.status_code == 403
    assert (
        client.post(_LOGIN, json={"email": sesion.email, "password": PASSWORD}).status_code == 200
    )


def test_sin_sesion_no_se_cambia():
    respuesta = TestClient(app).post(
        _CHANGE, json={"current_password": PASSWORD, "new_password": _NUEVA}
    )

    assert respuesta.status_code == 401


def test_una_cuenta_sin_contrasena_recibe_409(client):
    from api.routes.auth import _csrf_for_session
    from db.sessions import create_session
    from db.users import get_or_create_oauth_user

    user_id = get_or_create_oauth_user(
        email="solo-google@example.com", oauth_provider="google", oauth_sub="sub-solo-google"
    )
    token = create_session(user_id)
    client.cookies.set("session", token)

    respuesta = client.post(
        _CHANGE,
        json={"current_password": _CUALQUIERA, "new_password": _NUEVA},
        headers={"X-CSRF-Token": _csrf_for_session(token)},
    )

    assert respuesta.status_code == 409
    assert "Crear cuenta" in respuesta.json()["detail"]


# ---------------------------------------------------------------------------
# El reset también avisa
# ---------------------------------------------------------------------------


def test_el_reset_encola_el_aviso_al_titular():
    with (
        patch("api.routes.auth._password_reset_rate_allowed", new=AsyncMock(return_value=True)),
        patch("db.password_reset.reset_token_vigente", return_value=True),
        patch("db.password_reset.consume_reset_token", MagicMock(return_value=7)),
        patch("api.routes.auth.log_event"),
        patch("services.password_reset.notify_password_changed") as avisar,
    ):
        respuesta = TestClient(app).post(_CONFIRM, json={"token": _TOKEN, "password": _NUEVA})

    assert respuesta.status_code == 200, respuesta.text
    avisar.assert_called_once_with(7)


def test_un_reset_fallido_no_avisa():
    with (
        patch("api.routes.auth._password_reset_rate_allowed", new=AsyncMock(return_value=True)),
        patch("db.password_reset.reset_token_vigente", return_value=True),
        patch("db.password_reset.consume_reset_token", MagicMock(return_value=None)),
        patch("services.password_reset.notify_password_changed") as avisar,
    ):
        respuesta = TestClient(app).post(_CONFIRM, json={"token": _TOKEN, "password": _NUEVA})

    assert respuesta.status_code == 400
    avisar.assert_not_called()


def test_el_aviso_nunca_lanza_y_no_deja_el_correo_en_el_log(capsys):
    from observability.logging import configure_logging, get_logger
    from services import password_reset as servicio

    configure_logging(level="INFO", json_logs=True)
    with (
        patch.object(servicio, "log", get_logger("tests.cambio_contrasena")),
        patch("db.users.get_user_by_id", return_value={"email": "ana@example.com"}),
        patch.object(
            servicio, "enviar_email_transaccional", side_effect=RuntimeError("ana@example.com")
        ),
    ):
        servicio.notify_password_changed(7)

    salida = capsys.readouterr()
    assert "password_changed_email_failed" in salida.err + salida.out
    assert "ana@example.com" not in salida.err + salida.out


def test_el_aviso_sin_url_del_frontend_sale_igual_sin_enlace(monkeypatch):
    from services import app_urls
    from services import password_reset as servicio

    monkeypatch.setattr(app_urls.settings, "CORS_ALLOWED_ORIGINS", "", raising=False)
    monkeypatch.setattr(app_urls.settings, "OAUTH_REDIRECT_URI", "", raising=False)
    with patch.object(servicio, "enviar_email_transaccional", return_value=True) as enviar:
        assert servicio.send_password_changed_email("ana@example.com") is True

    # Un aviso sin enlace sigue sirviendo: le dice al titular que algo cambió.
    assert "se cambió el" in enviar.call_args.kwargs["texto"]
