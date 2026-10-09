"""Recuperación de contraseña: no enumeración, un solo uso y revocación."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient

from api.app import app

_REQUEST = "/api/v1/auth/password-reset/request"
_CONFIRM = "/api/v1/auth/password-reset/confirm"
_REGISTER = "/api/v1/auth/register"
_LOGIN = "/api/v1/auth/login"
_NEW_PASSWORD = "NuevaClave-2026-Segura"  # pragma: allowlist secret # gitleaks:allow
# Cumple la política del alta y no lleva carácter especial: es la que la
# confirmación rechazaba con un token válido.
_SIN_ESPECIAL = "NuevaClave2026Segura"  # pragma: allowlist secret # gitleaks:allow
_OLD_PASSWORD = "Anterior-2026-Segura"  # pragma: allowlist secret # gitleaks:allow
# Fuera de política (sin mayúsculas), pero con la longitud que exige el DTO.
_FLOJA = "sinmayusculas2026"  # pragma: allowlist secret
# Un hash que ningún test debe llegar a ver escrito: sirve para los consumos
# que tienen que fallar, sin pagar un argon2 por cada uno.
_HASH_QUE_NO_SE_ESCRIBE = "hash-que-no-debe-escribirse"  # pragma: allowlist secret
_TOKEN = "tok_-" + "x" * 38
_FUTURO = "2999-01-01T00:00:00+00:00"
_ORIGEN = "https://app.example"


def test_request_response_does_not_enumerate_accounts():
    client = TestClient(app)
    with (
        patch("api.routes.auth._password_reset_rate_allowed", new=AsyncMock(return_value=True)),
        patch("services.password_reset.issue_password_reset", return_value=(False, None)),
    ):
        missing = client.post(_REQUEST, json={"email": "missing@example.com"})
    with (
        patch("api.routes.auth._password_reset_rate_allowed", new=AsyncMock(return_value=True)),
        patch("services.password_reset.issue_password_reset", return_value=(True, "x" * 43)),
        patch("services.password_reset.send_password_reset_email", return_value=True),
    ):
        existing = client.post(_REQUEST, json={"email": "existing@example.com"})

    assert missing.status_code == existing.status_code == 202, (missing.text, existing.text)
    assert missing.json() == existing.json()


def test_request_rate_limit_keeps_generic_response():
    client = TestClient(app)
    with (
        patch("api.routes.auth._password_reset_rate_allowed", new=AsyncMock(return_value=False)),
        patch("services.password_reset.issue_password_reset") as issue,
    ):
        response = client.post(_REQUEST, json={"email": "someone@example.com"})

    assert response.status_code == 202, response.text
    issue.assert_not_called()


def test_confirm_rejects_invalid_or_expired_token():
    client = TestClient(app)
    with (
        patch("api.routes.auth._password_reset_rate_allowed", new=AsyncMock(return_value=True)),
        patch("db.password_reset.consume_reset_token", return_value=None),
    ):
        response = client.post(
            _CONFIRM,
            json={"token": "x" * 43, "password": _NEW_PASSWORD},
        )

    assert response.status_code == 400
    assert "caducado" in response.json()["detail"]


def test_token_is_single_use_and_revokes_sessions(tmp_db):
    from db.database import connect
    from db.password_reset import consume_reset_token, create_reset_token_for_email
    from db.sessions import create_session, validate_session
    from db.users import create_user, get_user_by_email
    from services.password_reset import token_hash
    from shared.auth_core import hash_password, verify_password

    email = "reset@example.test"
    user_id = create_user(email=email, password_hash=hash_password("Anterior-2026-Segura"))
    session = create_session(user_id)
    raw_token = "token-reset-seguro-" + "x" * 32
    digest = token_hash(raw_token)

    assert create_reset_token_for_email(email, digest, "2999-01-01T00:00:00+00:00") is True
    assert consume_reset_token(digest, hash_password(_NEW_PASSWORD)) == user_id
    assert consume_reset_token(digest, hash_password("OtraClave-2026-Segura")) is None
    assert validate_session(session) is None

    user = get_user_by_email(email)
    assert user is not None
    assert verify_password(_NEW_PASSWORD, str(user["password_hash"])) is True
    with connect() as connection:
        stored = connection.execute(
            "SELECT token_hash FROM password_reset_tokens WHERE user_id = %s",
            (user_id,),
        ).fetchone()
    assert stored is not None
    assert stored[0] == digest
    assert raw_token not in str(stored[0])


# ---------------------------------------------------------------------------
# La política de confirm es la del alta
# ---------------------------------------------------------------------------


def _alta(client: TestClient, password: str):
    """``POST /auth/register`` con la persistencia simulada: solo importa la política."""
    from api.routes import auth as auth_mod

    with (
        patch.object(auth_mod.settings, "ALLOW_SELF_REGISTRATION", True),
        patch("api.routes.auth.get_user_by_email", return_value=None),
        patch("api.routes.auth.create_user", return_value=7),
        patch("api.routes.auth._activar_invitaciones"),
        patch("api.routes.auth._set_session_cookie"),
        patch("api.routes.auth.log_access"),
    ):
        return client.post(_REGISTER, json={"email": "alta@example.com", "password": password})


def _confirmar(client: TestClient, password: str, *, consume: MagicMock | None = None):
    """``POST /auth/password-reset/confirm`` con un token que el repositorio da por bueno."""
    with (
        patch("api.routes.auth._password_reset_rate_allowed", new=AsyncMock(return_value=True)),
        patch("db.password_reset.consume_reset_token", consume or MagicMock(return_value=7)),
        patch("api.routes.auth.log_event"),
    ):
        return client.post(_CONFIRM, json={"token": _TOKEN, "password": password})


def test_alta_y_confirm_aceptan_la_misma_contrasena_sin_caracter_especial():
    """El defecto: con un token válido, confirm devolvía 400 «carácter especial»."""
    client = TestClient(app)

    alta = _alta(client, _SIN_ESPECIAL)
    confirm = _confirmar(client, _SIN_ESPECIAL)

    assert alta.status_code == 201, alta.text
    assert confirm.status_code == 200, confirm.text


@pytest.mark.parametrize("password", [_FLOJA, "SinNingunDigito", "MiPassword2026"])
def test_alta_y_confirm_rechazan_lo_mismo_con_el_mismo_mensaje(password: str):
    client = TestClient(app)

    alta = _alta(client, password)
    confirm = _confirmar(client, password)

    assert alta.status_code == confirm.status_code == 400, (alta.text, confirm.text)
    assert alta.json()["detail"] == confirm.json()["detail"]
    assert "contraseña" in confirm.json()["detail"]


def test_alta_y_confirm_pasan_por_la_misma_funcion_de_politica():
    """Si una ruta vuelve a llamar a la política con sus propios argumentos, esto falla."""
    from shared.password_policy import PasswordCheckResult

    veredicto = PasswordCheckResult(is_strong=False, issues=("veredicto de la única política",))
    client = TestClient(app)
    with patch("api.routes.auth.check_account_password", return_value=veredicto) as politica:
        alta = _alta(client, _SIN_ESPECIAL)
        confirm = _confirmar(client, _SIN_ESPECIAL)

    assert politica.call_count == 2
    assert alta.status_code == confirm.status_code == 400
    assert alta.json()["detail"] == confirm.json()["detail"] == "veredicto de la única política"


def test_confirm_rechaza_por_politica_sin_tocar_el_token():
    """Una contraseña floja no puede costarle el enlace a quien lo pidió."""
    consume = MagicMock(return_value=7)

    response = _confirmar(TestClient(app), _FLOJA, consume=consume)

    assert response.status_code == 400
    consume.assert_not_called()


# ---------------------------------------------------------------------------
# El límite de confirm
# ---------------------------------------------------------------------------


def test_confirm_limitado_responde_429_con_retry_after_y_no_consume():
    client = TestClient(app)
    with (
        patch("api.routes.auth._password_reset_rate_allowed", new=AsyncMock(return_value=False)),
        patch("db.password_reset.consume_reset_token") as consume,
    ):
        response = client.post(_CONFIRM, json={"token": _TOKEN, "password": _NEW_PASSWORD})

    assert response.status_code == 429
    # La ventana entera, como el 429 del middleware: el limitador no dice
    # cuánto falta, y de más es el lado seguro.
    assert response.headers["Retry-After"] == "900"
    consume.assert_not_called()


# ---------------------------------------------------------------------------
# Lo que depende de la cuenta ocurre después de responder
# ---------------------------------------------------------------------------


def test_request_no_hace_en_linea_nada_que_dependa_de_la_cuenta():
    """Con cuenta, la respuesta esperaba a dos escrituras más: se distinguía por tiempo."""
    from api.routes import auth as auth_mod

    tareas = BackgroundTasks()
    with (
        patch("api.routes.auth._password_reset_rate_allowed", new=AsyncMock(return_value=True)),
        patch("services.password_reset.issue_password_reset", return_value=(True, _TOKEN)) as issue,
        patch("services.password_reset.send_password_reset_email", return_value=True) as send,
        patch("services.password_reset.log_event") as audit,
    ):
        respuesta = asyncio.run(
            auth_mod.request_password_reset(
                auth_mod.PasswordResetRequest(email="Existe@Example.com"),
                MagicMock(),
                tareas,
            )
        )
        # Ya hay respuesta y todavía no se ha mirado si la cuenta existe.
        issue.assert_not_called()
        audit.assert_not_called()
        send.assert_not_called()
        assert len(tareas.tasks) == 1

        asyncio.run(tareas())
        issue.assert_called_once_with("existe@example.com")
        audit.assert_called_once()
        send.assert_called_once_with("existe@example.com", _TOKEN)

    assert respuesta.detail == auth_mod._RESET_REQUEST_RESPONSE


def test_la_respuesta_sale_entera_antes_de_empezar_el_trabajo_aplazado():
    """Con toda la pila de middlewares: ninguno retiene el cuerpo hasta que acabe la tarea.

    Se llama a la app por ASGI, sin ``TestClient``, que espera a las tareas
    aplazadas antes de devolver y no deja ver el orden.
    """
    cuerpo = json.dumps({"email": "existe@example.com"}).encode()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": _REQUEST,
        "raw_path": _REQUEST.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(cuerpo)).encode()),
        ],
        "client": ("203.0.113.9", 50000),
        "server": ("testserver", 80),
    }
    enviados: list[dict[str, object]] = []
    respuesta_completa_al_empezar: list[bool] = []

    def _aplazado(_email: str) -> None:
        respuesta_completa_al_empezar.append(
            any(
                mensaje["type"] == "http.response.body" and not mensaje.get("more_body", False)
                for mensaje in enviados
            )
        )

    async def _llamar() -> None:
        pendiente = [{"type": "http.request", "body": cuerpo, "more_body": False}]

        async def receive() -> dict[str, object]:
            if pendiente:
                return pendiente.pop()
            # Cliente que sigue conectado: no hay más mensajes que entregar.
            await asyncio.Event().wait()
            raise AssertionError("inalcanzable")

        async def send(mensaje: dict[str, object]) -> None:
            enviados.append(mensaje)

        await app(scope, receive, send)

    with (
        patch("api.routes.auth._password_reset_rate_allowed", new=AsyncMock(return_value=True)),
        patch("services.password_reset.process_password_reset_request", side_effect=_aplazado),
    ):
        asyncio.run(_llamar())

    inicio = next(mensaje for mensaje in enviados if mensaje["type"] == "http.response.start")
    assert inicio["status"] == 202
    assert respuesta_completa_al_empezar == [True]


@pytest.mark.parametrize(("created", "token"), [(True, _TOKEN), (False, None)])
def test_el_trabajo_aplazado_deja_rastro_y_solo_escribe_a_quien_tiene_cuenta(
    created: bool, token: str | None
):
    from services import password_reset as servicio

    with (
        patch.object(servicio, "issue_password_reset", return_value=(created, token)),
        patch.object(servicio, "send_password_reset_email", return_value=True) as send,
        patch.object(servicio, "log_event") as audit,
    ):
        servicio.process_password_reset_request("alguien@example.com")

    audit.assert_called_once_with(
        event_type="auth.password_reset_requested",
        outcome="success" if created else "failure",
        detail={"issued": created},
    )
    assert send.call_count == (1 if created else 0)
    # El rastro dice si se emitió, no para quién ni con qué.
    assert "alguien@example.com" not in str(audit.call_args)
    assert _TOKEN not in str(audit.call_args)


def test_un_fallo_del_trabajo_aplazado_no_se_propaga_ni_deja_rastro_a_medias():
    from services import password_reset as servicio

    with (
        patch.object(servicio, "issue_password_reset", side_effect=RuntimeError("bd caída")),
        patch.object(servicio, "send_password_reset_email") as send,
        patch.object(servicio, "log_event") as audit,
        patch.object(servicio, "log") as log,
    ):
        servicio.process_password_reset_request("alguien@example.com")

    send.assert_not_called()
    audit.assert_not_called()
    log.error.assert_called_once_with("password_reset_request_failed", exc_info=True)
    # `log.exception` entrega además la traza a `logging`, que la imprime sin
    # pasar por el redactor.
    log.exception.assert_not_called()


def test_el_fallo_aplazado_se_registra_sin_el_token_ni_el_correo(capsys):
    """El peor caso: la excepción trae en su mensaje la dirección y el enlace entero."""
    from observability.logging import configure_logging, get_logger
    from services import password_reset as servicio

    email = "alguien@example.com"
    fallo = RuntimeError(f"no se pudo entregar a {email}: {_ORIGEN}/x#token={_TOKEN}")
    configure_logging(level="INFO", json_logs=True)
    with (
        patch.object(servicio, "log", get_logger("tests.password_reset")),
        patch.object(servicio, "issue_password_reset", return_value=(True, _TOKEN)),
        patch.object(servicio, "log_event"),
        patch.object(servicio, "send_password_reset_email", side_effect=fallo),
    ):
        servicio.process_password_reset_request(email)

    capturado = capsys.readouterr()
    salida = capturado.err + capturado.out
    assert "password_reset_request_failed" in salida
    assert email not in salida
    assert _TOKEN not in salida


def test_request_responde_igual_aunque_el_trabajo_aplazado_falle():
    # `TestClient` relanza lo que escape de la app, tareas aplazadas incluidas:
    # si el fallo se propagara, este `post` no devolvería.
    client = TestClient(app)
    with (
        patch("api.routes.auth._password_reset_rate_allowed", new=AsyncMock(return_value=True)),
        patch("services.password_reset.issue_password_reset", side_effect=RuntimeError("bd")),
    ):
        fallido = client.post(_REQUEST, json={"email": "existing@example.com"})
    with patch("api.routes.auth._password_reset_rate_allowed", new=AsyncMock(return_value=False)):
        limitado = client.post(_REQUEST, json={"email": "existing@example.com"})

    assert fallido.status_code == limitado.status_code == 202
    assert fallido.json() == limitado.json()


# ---------------------------------------------------------------------------
# El correo: forma del enlace y lo que queda en el log
# ---------------------------------------------------------------------------


@pytest.fixture()
def origen_frontend(monkeypatch: pytest.MonkeyPatch) -> str:
    """Fija el origen del frontend del que sale el enlace del correo."""
    from services import app_urls

    monkeypatch.setattr(app_urls.settings, "CORS_ALLOWED_ORIGINS", _ORIGEN, raising=False)
    monkeypatch.setattr(app_urls.settings, "OAUTH_REDIRECT_URI", "", raising=False)
    return _ORIGEN


def test_el_correo_lleva_el_enlace_con_el_token_en_el_fragmento(origen_frontend: str):
    from services import password_reset as servicio

    with patch.object(servicio, "enviar_email_transaccional", return_value=True) as enviar:
        assert servicio.send_password_reset_email("ana@example.com", _TOKEN) is True

    campos = enviar.call_args.kwargs
    enlace = f"{origen_frontend}/restablecer-contrasena#token={_TOKEN}"
    assert campos["to_addr"] == "ana@example.com"
    assert enlace in campos["texto"]
    assert f'href="{enlace}"' in campos["html"]
    # En el fragmento y no en la query: el navegador no se lo manda al servidor.
    assert "?token=" not in campos["texto"] + campos["html"]


@pytest.mark.parametrize("sent", [True, False])
def test_el_registro_del_envio_no_lleva_el_token_ni_la_direccion(origen_frontend: str, sent: bool):
    from services import password_reset as servicio

    with (
        patch.object(servicio, "enviar_email_transaccional", return_value=sent),
        patch.object(servicio, "log") as log,
    ):
        assert servicio.send_password_reset_email("ana@example.com", _TOKEN) is sent

    registrado = str(log.method_calls)
    assert "ana@example.com" not in registrado
    assert _TOKEN not in registrado
    # Un correo que no sale es el fallo que nadie ve: quien lo pidió ya leyó
    # «te llegará un enlace». No puede quedarse en `info`.
    esperado, otro = (log.info, log.warning) if sent else (log.warning, log.info)
    esperado.assert_called_once_with("password_reset_email", sent=sent, domain="example.com")
    otro.assert_not_called()


def test_sin_url_del_frontend_no_se_envia_y_queda_como_error(monkeypatch: pytest.MonkeyPatch):
    from services import app_urls
    from services import password_reset as servicio

    monkeypatch.setattr(app_urls.settings, "CORS_ALLOWED_ORIGINS", "", raising=False)
    monkeypatch.setattr(app_urls.settings, "OAUTH_REDIRECT_URI", "", raising=False)
    with (
        patch.object(servicio, "enviar_email_transaccional") as enviar,
        patch.object(servicio, "log") as log,
    ):
        assert servicio.send_password_reset_email("ana@example.com", _TOKEN) is False

    enviar.assert_not_called()
    log.error.assert_called_once_with("password_reset_frontend_url_unavailable")
    assert "ana@example.com" not in str(log.method_calls)
    assert _TOKEN not in str(log.method_calls)


def test_la_url_del_enlace_no_sale_de_la_cabecera_host(origen_frontend: str):
    """Quien pide el enlace no decide a qué dominio apunta el correo de otro."""
    client = TestClient(app)
    with (
        patch("api.routes.auth._password_reset_rate_allowed", new=AsyncMock(return_value=True)),
        patch("services.password_reset.create_reset_token_for_email", return_value=True),
        patch("services.password_reset.log_event"),
        patch("services.password_reset.enviar_email_transaccional", return_value=True) as enviar,
    ):
        response = client.post(
            _REQUEST,
            json={"email": "ana@example.com"},
            headers={"Host": "atacante.example", "X-Forwarded-Host": "atacante.example"},
        )

    assert response.status_code == 202, response.text
    campos = enviar.call_args.kwargs
    assert f"{origen_frontend}/restablecer-contrasena#token=" in campos["texto"]
    assert "atacante.example" not in campos["texto"] + campos["html"]


# ---------------------------------------------------------------------------
# Contra el SQL real
# ---------------------------------------------------------------------------


def _crear_cuenta(email: str, password: str = _OLD_PASSWORD) -> int:
    from db.users import create_user
    from shared.auth_core import hash_password

    return create_user(email=email, password_hash=hash_password(password))


def _insertar_token(user_id: int, raw: str, *, expires_at: str = _FUTURO) -> str:
    """Deja un token vivo sin pasar por la emisión, que invalidaría los anteriores."""
    from db.database import connect
    from services.password_reset import token_hash

    digest = token_hash(raw)
    with connect() as connection:
        connection.execute(
            "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) "
            "VALUES (%s, %s, %s)",
            (user_id, digest, expires_at),
        )
    return digest


def _conserva_la_contrasena(user_id: int, password: str = _OLD_PASSWORD) -> bool:
    from db.users import get_user_by_id
    from shared.auth_core import verify_password

    user = get_user_by_id(user_id, include_deactivated=True)
    assert user is not None
    return verify_password(password, str(user["password_hash"]))


def test_un_token_caducado_no_cambia_nada(tmp_db):
    from db.database import connect
    from db.password_reset import consume_reset_token, create_reset_token_for_email
    from db.sessions import create_session, validate_session_principal
    from services.password_reset import token_hash

    email = "caducado@example.test"
    user_id = _crear_cuenta(email)
    sesion = create_session(user_id)
    digest = token_hash("token-caducado-" + "x" * 32)
    hace_un_minuto = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()

    assert create_reset_token_for_email(email, digest, hace_un_minuto) is True
    assert consume_reset_token(digest, _HASH_QUE_NO_SE_ESCRIBE) is None

    assert _conserva_la_contrasena(user_id)
    assert validate_session_principal(sesion) is not None
    with connect() as connection:
        fila = connection.execute(
            "SELECT used_at FROM password_reset_tokens WHERE token_hash = %s", (digest,)
        ).fetchone()
    assert fila is not None
    assert fila[0] is None


def test_pedir_un_enlace_nuevo_invalida_el_anterior(tmp_db):
    from db.password_reset import consume_reset_token, create_reset_token_for_email
    from services.password_reset import token_hash
    from shared.auth_core import hash_password

    email = "dosveces@example.test"
    user_id = _crear_cuenta(email)
    primero = token_hash("primer-enlace-" + "a" * 32)
    segundo = token_hash("segundo-enlace-" + "b" * 32)

    assert create_reset_token_for_email(email, primero, _FUTURO) is True
    assert create_reset_token_for_email(email, segundo, _FUTURO) is True

    assert consume_reset_token(primero, _HASH_QUE_NO_SE_ESCRIBE) is None
    assert _conserva_la_contrasena(user_id)
    assert consume_reset_token(segundo, hash_password(_NEW_PASSWORD)) == user_id
    assert _conserva_la_contrasena(user_id, _NEW_PASSWORD)


def test_consumir_un_enlace_invalida_los_demas_pendientes_del_usuario(tmp_db):
    """Dos solicitudes simultáneas pueden dejar dos enlaces vivos: tras el cambio no vale ninguno."""
    from db.password_reset import consume_reset_token
    from shared.auth_core import hash_password

    user_id = _crear_cuenta("dosvivos@example.test")
    otra_cuenta = _crear_cuenta("otra@example.test")
    usado = _insertar_token(user_id, "enlace-usado-" + "a" * 32)
    hermano = _insertar_token(user_id, "enlace-hermano-" + "b" * 32)
    ajeno = _insertar_token(otra_cuenta, "enlace-ajeno-" + "c" * 32)

    assert consume_reset_token(usado, hash_password(_NEW_PASSWORD)) == user_id

    assert consume_reset_token(hermano, _HASH_QUE_NO_SE_ESCRIBE) is None
    assert _conserva_la_contrasena(user_id, _NEW_PASSWORD)
    # Solo los del usuario que cambió la contraseña: el de otra cuenta sigue vivo.
    assert consume_reset_token(ajeno, hash_password(_SIN_ESPECIAL)) == otra_cuenta


def test_una_cuenta_solo_oauth_no_recibe_enlace_ni_puede_consumirlo(tmp_db):
    from db.database import connect
    from db.password_reset import consume_reset_token
    from db.users import get_or_create_oauth_user, get_user_by_id
    from services.password_reset import issue_password_reset

    email = "solo-oauth@example.test"
    user_id = get_or_create_oauth_user(email=email, oauth_provider="google", oauth_sub="sub-243")

    assert issue_password_reset(email) == (False, None)
    with connect() as connection:
        fila = connection.execute(
            "SELECT COUNT(*) FROM password_reset_tokens WHERE user_id = %s", (user_id,)
        ).fetchone()
    assert fila is not None
    assert fila[0] == 0

    # Ni aunque el token existiera: una cuenta sin contraseña no estrena una por aquí.
    digest = _insertar_token(user_id, "enlace-imposible-" + "x" * 32)
    assert consume_reset_token(digest, _HASH_QUE_NO_SE_ESCRIBE) is None
    user = get_user_by_id(user_id)
    assert user is not None
    assert user["password_hash"] is None


@pytest.mark.parametrize("baja", ["deactivate_user", "anonymize_user"])
def test_una_cuenta_de_baja_no_recibe_enlace_ni_consume_el_que_tenia(tmp_db, baja: str):
    import db.users as users
    from db.password_reset import consume_reset_token, create_reset_token_for_email
    from services.password_reset import issue_password_reset, token_hash

    email = "baja@example.test"
    user_id = _crear_cuenta(email)
    previo = token_hash("enlace-previo-" + "x" * 32)
    assert create_reset_token_for_email(email, previo, _FUTURO) is True

    getattr(users, baja)(user_id)

    assert issue_password_reset(email) == (False, None)
    assert consume_reset_token(previo, _HASH_QUE_NO_SE_ESCRIBE) is None
    assert _conserva_la_contrasena(user_id)


def test_la_revocacion_escribe_revoked_at_como_el_resto_del_codigo(tmp_db):
    """``sessions.revoked_at`` es TEXT: ISO 8601, como lo escribe ``db/sessions.py``."""
    from db.database import connect
    from db.password_reset import consume_reset_token
    from db.sessions import create_session

    user_id = _crear_cuenta("formato@example.test")
    create_session(user_id)
    digest = _insertar_token(user_id, "enlace-formato-" + "x" * 32)

    assert consume_reset_token(digest, "hash-irrelevante") == user_id

    with connect() as connection:
        fila = connection.execute(
            "SELECT revoked, revoked_at FROM sessions WHERE user_id = %s", (user_id,)
        ).fetchone()
    assert fila is not None
    revoked, revoked_at = fila
    assert revoked == 1
    instante = datetime.fromisoformat(revoked_at)
    assert instante.tzinfo is not None
    assert revoked_at == instante.isoformat()


def test_recorrido_completo_por_http(client, monkeypatch: pytest.MonkeyPatch):
    """Pedir, confirmar y volver a entrar; la sesión de antes y la contraseña vieja caen."""
    from db.sessions import validate_session_principal
    from services import app_urls
    from services.rate_limiting import DbRateLimiter

    monkeypatch.setattr(app_urls.settings, "CORS_ALLOWED_ORIGINS", _ORIGEN, raising=False)
    monkeypatch.setattr("services.rate_limiting.get_rate_limiter", lambda: DbRateLimiter())
    # `.com` y no `.test`: por HTTP el correo pasa por `EmailStr`, que rechaza
    # los dominios de uso reservado con un 422.
    email = "recorrido@example.com"
    _crear_cuenta(email)

    login = client.post(_LOGIN, json={"email": email, "password": _OLD_PASSWORD})
    assert login.status_code == 200, login.text
    sesion_previa = login.cookies["session"]
    assert validate_session_principal(sesion_previa) is not None

    with patch("services.password_reset.enviar_email_transaccional", return_value=True) as enviar:
        pedido = client.post(_REQUEST, json={"email": email})
    assert pedido.status_code == 202, pedido.text
    enlace = re.search(
        re.escape(f"{_ORIGEN}/restablecer-contrasena#token=") + r"(\S+)",
        enviar.call_args.kwargs["texto"],
    )
    assert enlace is not None
    token = enlace.group(1)

    # Una contraseña fuera de política se rechaza sin quemar el enlace…
    rechazo = client.post(_CONFIRM, json={"token": token, "password": _FLOJA})
    assert rechazo.status_code == 400, rechazo.text
    # …y la que el alta admite, sin carácter especial, lo consume.
    confirm = client.post(_CONFIRM, json={"token": token, "password": _SIN_ESPECIAL})
    assert confirm.status_code == 200, confirm.text

    # La sesión de antes deja de valer por el camino que recorre el SPA.
    assert validate_session_principal(sesion_previa) is None
    assert client.get("/api/v1/auth/me").status_code == 401
    # La contraseña vieja ya no entra; la nueva, sí.
    assert client.post(_LOGIN, json={"email": email, "password": _OLD_PASSWORD}).status_code == 401
    nuevo = client.post(_LOGIN, json={"email": email, "password": _SIN_ESPECIAL})
    assert nuevo.status_code == 200, nuevo.text
    # Y el enlace no sirve una segunda vez.
    repetido = client.post(_CONFIRM, json={"token": token, "password": _NEW_PASSWORD})
    assert repetido.status_code == 400, repetido.text
