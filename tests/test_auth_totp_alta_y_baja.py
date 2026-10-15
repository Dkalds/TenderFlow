"""Alta y baja del segundo factor: lo que la pantalla de Ajustes necesita.

``tests/test_auth_totp_endpoints.py`` fija el camino feliz del alta y el login
con código. Aquí van los bordes que deciden si la pantalla se puede usar:

- Empezar el alta y abandonarla no puede dejar la cuenta encerrada: el
  siguiente intento empieza de cero en vez de responder 409 para siempre.
- Quitar el segundo factor exige un código vigente (o uno de recuperación).
  Hasta ahora bastaba con la sesión, así que quien se sentara delante de un
  navegador abierto podía desactivarlo sin el móvil.
- El emisor que ve la app del móvil es TenderFlow.
"""

from __future__ import annotations

from urllib.parse import unquote

from config import settings
from tests.escenarios import Sesion, abrir_sesion, codigo_totp


def _activar(sesion: Sesion) -> tuple[str, list[str]]:
    """Alta completa: devuelve el URI otpauth y los códigos de recuperación."""
    alta = sesion.post("/auth/totp/setup")
    assert alta.status_code == 200, alta.text
    uri = str(alta.json()["otpauth_uri"])
    confirmada = sesion.post("/auth/totp/confirm", json={"code": codigo_totp(uri)})
    assert confirmada.status_code == 200, confirmada.text
    return uri, list(confirmada.json()["recovery_codes"])


def test_el_alta_abandonada_se_puede_reempezar(client, api_db):
    sesion = abrir_sesion("reempieza@example.com", client)

    primera = sesion.post("/auth/totp/setup")
    assert primera.status_code == 200, primera.text
    segunda = sesion.post("/auth/totp/setup")
    assert segunda.status_code == 200, segunda.text

    uri_vieja, uri_nueva = primera.json()["otpauth_uri"], segunda.json()["otpauth_uri"]
    assert uri_vieja != uri_nueva
    # Lo que vale es el secreto del último intento: el abandonado ya no abre nada.
    vieja = sesion.post("/auth/totp/confirm", json={"code": codigo_totp(uri_vieja)})
    if codigo_totp(uri_vieja) != codigo_totp(uri_nueva):
        assert vieja.status_code == 400
    assert (
        sesion.post("/auth/totp/confirm", json={"code": codigo_totp(uri_nueva)}).status_code == 200
    )
    assert sesion.get("/auth/me").json()["mfa_required"] is True


def test_con_el_segundo_factor_activo_no_se_reempieza(client, api_db):
    sesion = abrir_sesion("activo@example.com", client)
    _activar(sesion)

    assert sesion.post("/auth/totp/setup").status_code == 409


def test_el_emisor_es_tenderflow(client, api_db):
    sesion = abrir_sesion("emisor@example.com", client)

    uri = unquote(sesion.post("/auth/totp/setup").json()["otpauth_uri"])

    assert "issuer=TenderFlow" in uri
    assert uri.startswith("otpauth://totp/TenderFlow:emisor@example.com")


def test_quitarlo_exige_un_codigo(client, api_db):
    sesion = abrir_sesion("sin-codigo@example.com", client)
    _activar(sesion)

    assert sesion.delete("/auth/totp").status_code == 422
    assert sesion.delete("/auth/totp", json={"code": "000000"}).status_code == 400
    # Sigue activo: ni el cuerpo vacío ni el código falso lo quitaron.
    assert sesion.get("/auth/me").json()["mfa_required"] is True


def test_quitarlo_con_un_codigo_vigente(client, api_db):
    sesion = abrir_sesion("con-codigo@example.com", client)
    uri, _ = _activar(sesion)

    quitado = sesion.delete("/auth/totp", json={"code": codigo_totp(uri)})

    assert quitado.status_code == 200, quitado.text
    assert sesion.get("/auth/me").json()["mfa_required"] is False
    # Y se puede volver a activar desde cero.
    assert sesion.post("/auth/totp/setup").status_code == 200


def test_sin_segundo_factor_no_hay_nada_que_quitar(client, api_db):
    sesion = abrir_sesion("nada@example.com", client)

    assert sesion.delete("/auth/totp", json={"code": "123456"}).status_code == 409


def test_quitarlo_con_un_codigo_de_recuperacion(client, api_db):
    """Sin el móvil, un código de recuperación también vale para quitarlo."""
    sesion = abrir_sesion("recupera@example.com", client)
    _, recuperacion = _activar(sesion)

    quitado = sesion.delete("/auth/totp", json={"code": recuperacion[0]})

    assert quitado.status_code == 200, quitado.text
    assert sesion.get("/auth/me").json()["mfa_required"] is False


def test_con_la_sesion_antigua_el_403_dice_que_hay_que_volver_a_entrar(client, api_db, monkeypatch):
    sesion = abrir_sesion("antigua@example.com", client)
    # Toda sesión es «antigua» con un margen de cero segundos.
    monkeypatch.setattr(settings, "SENSITIVE_ACTION_MAX_AGE_SECONDS", -1)

    resp = sesion.post("/auth/totp/setup")

    assert resp.status_code == 403
    assert resp.json()["type"].endswith("/reauthentication-required")
