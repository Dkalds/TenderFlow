"""Alta cerrada con correo y contraseña (RFC 2026-10-21-alta-con-contrasena-tras-concesion).

Pedir acceso solo apunta en la lista; quien está en ella se da de alta con
correo y contraseña, la cuenta se activa con el enlace que llega a ese buzón, y
cada login con contraseña vuelve a comprobar la concesión.

Los tests fuerzan el **modo cerrado** (el de producción) con
``_registro_abierto`` y dejan la lista estática vacía de verdad
(``oauth_email_allowed`` → ``False``), así que solo cuentan las concesiones de
``access_grants``, como en producción.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any, Literal
from unittest.mock import MagicMock, patch
from urllib.parse import unquote

import pytest

_REGISTER = "/api/v1/auth/register"
_VERIFY = "/api/v1/auth/verify-email"
_LOGIN = "/api/v1/auth/login"
_ME = "/api/v1/auth/me"
_CONFIRM = "/api/v1/auth/password-reset/confirm"
_PASSWORD = "AltaCerrada2026"  # pragma: allowlist secret # gitleaks:allow
_OTRA = "OtraClave2026Segura"  # pragma: allowlist secret # gitleaks:allow
_ORIGEN = "https://app.example"


class _Buzon:
    """Recoge los correos que el servicio intenta enviar."""

    def __init__(self) -> None:
        self.enviados: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> bool:
        self.enviados.append(kwargs)
        return True

    def ultimo_token(self, ruta: str) -> str:
        """El token del último enlace a ``ruta`` (``/verificar-correo``…)."""
        for correo in reversed(self.enviados):
            m = re.search(re.escape(ruta) + r"#token=([^\s\"]+)", correo["texto"])
            if m:
                return unquote(m.group(1))
        raise AssertionError(f"ningún correo con enlace a {ruta}: {self.enviados}")


@pytest.fixture()
def buzon(client) -> Iterator[_Buzon]:
    """Modo cerrado, sin lista estática, con un buzón falso y un origen conocido."""
    from config import settings

    b = _Buzon()
    with (
        patch("api.routes.auth._registro_abierto", return_value=False),
        patch("services.access_grants.oauth_email_allowed", return_value=False),
        patch("services.email_verification.enviar_email_transaccional", new=b),
        patch.object(settings, "CORS_ALLOWED_ORIGINS", _ORIGEN),
    ):
        yield b


def _conceder(kind: Literal["email", "domain"], value: str) -> int:
    from db.access_grants import grant_access

    return grant_access(kind, value, granted_by=None)["id"]


def _alta(client, email: str, password: str = _PASSWORD):
    return client.post(_REGISTER, json={"email": email, "password": password})


def _usuario(email: str) -> dict[str, Any] | None:
    from db.users import get_users_by_email_ci

    filas = get_users_by_email_ci(email, include_deactivated=True)
    return filas[0] if filas else None


# ---------------------------------------------------------------------------
# Alta
# ---------------------------------------------------------------------------


def test_alta_sin_concesion_da_403_y_no_crea_cuenta(client, buzon):
    resp = _alta(client, "nadie@empresa.example")

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "access_not_granted"
    assert _usuario("nadie@empresa.example") is None
    assert buzon.enviados == []


def test_alta_concedida_crea_cuenta_sin_verificar_y_manda_el_enlace(client, buzon):
    _conceder("email", "ana@empresa.example")

    with patch("api.routes.auth._activar_invitaciones") as activar:
        resp = _alta(client, "Ana@Empresa.example")

    assert resp.status_code == 202, resp.text
    user = _usuario("ana@empresa.example")
    assert user is not None
    assert user["email"] == "ana@empresa.example"
    assert user["email_verified_at"] is None
    assert user["password_hash"]
    # Ni sesión ni invitaciones: eso pasa al verificar.
    assert client.get(_ME).status_code == 401
    activar.assert_not_called()
    assert [c["to_addr"] for c in buzon.enviados] == ["ana@empresa.example"]
    assert buzon.ultimo_token("/verificar-correo")


def test_concesion_por_dominio_vale_para_cualquier_direccion_del_dominio(client, buzon):
    _conceder("domain", "empresa.example")

    resp = _alta(client, "cualquiera@empresa.example")

    assert resp.status_code == 202, resp.text
    token = buzon.ultimo_token("/verificar-correo")
    assert client.post(_VERIFY, json={"token": token}).status_code == 200


def test_la_respuesta_del_alta_no_distingue_si_la_cuenta_existia(client, buzon):
    _conceder("domain", "empresa.example")
    from db.users import create_user

    create_user(email="vieja@empresa.example", password_hash="x")

    nueva = _alta(client, "nueva@empresa.example")
    existente = _alta(client, "vieja@empresa.example")

    assert nueva.status_code == existente.status_code == 202
    assert nueva.json() == existente.json()


# ---------------------------------------------------------------------------
# Verificación
# ---------------------------------------------------------------------------


def test_verificar_abre_sesion_activa_invitaciones_y_gasta_el_enlace(client, buzon):
    _conceder("email", "ana@empresa.example")
    _alta(client, "ana@empresa.example")
    token = buzon.ultimo_token("/verificar-correo")

    with patch("api.routes.auth._activar_invitaciones") as activar:
        resp = client.post(_VERIFY, json={"token": token})

    assert resp.status_code == 200, resp.text
    assert resp.json()["email"] == "ana@empresa.example"
    activar.assert_called_once()
    assert client.get(_ME).status_code == 200
    user = _usuario("ana@empresa.example")
    assert user is not None and user["email_verified_at"] is not None

    segunda = client.post(_VERIFY, json={"token": token})
    assert segunda.status_code == 400


def test_verificar_con_la_concesion_revocada_da_403_sin_gastar_el_enlace(client, buzon):
    from db.access_grants import revoke_access

    grant_id = _conceder("email", "ana@empresa.example")
    _alta(client, "ana@empresa.example")
    token = buzon.ultimo_token("/verificar-correo")
    revoke_access(grant_id)

    resp = client.post(_VERIFY, json={"token": token})

    assert resp.status_code == 403
    assert resp.json()["detail"] == "access_not_granted"
    assert client.get(_ME).status_code == 401
    # Al volver a conceder, el mismo enlace sigue sirviendo.
    _conceder("email", "ana@empresa.example")
    assert client.post(_VERIFY, json={"token": token}).status_code == 200


def test_un_token_inventado_da_400(client, buzon):
    resp = client.post(_VERIFY, json={"token": "x" * 43})
    assert resp.status_code == 400


def test_la_segunda_alta_sin_verificar_reemplaza_contrasena_y_enlace(client, buzon):
    """Quien se dio de alta primero con un correo ajeno no conserva nada."""
    _conceder("email", "ana@empresa.example")
    _alta(client, "ana@empresa.example", _PASSWORD)
    token_viejo = buzon.ultimo_token("/verificar-correo")

    _alta(client, "ana@empresa.example", _OTRA)
    token_nuevo = buzon.ultimo_token("/verificar-correo")

    assert token_nuevo != token_viejo
    assert client.post(_VERIFY, json={"token": token_viejo}).status_code == 400
    assert client.post(_VERIFY, json={"token": token_nuevo}).status_code == 200
    client.cookies.clear()
    viejo = client.post(_LOGIN, json={"email": "ana@empresa.example", "password": _PASSWORD})
    nuevo = client.post(_LOGIN, json={"email": "ana@empresa.example", "password": _OTRA})
    assert viejo.status_code == 401
    assert nuevo.status_code == 200, nuevo.text


# ---------------------------------------------------------------------------
# Cuentas que ya existen
# ---------------------------------------------------------------------------


def test_alta_sobre_cuenta_verificada_no_toca_la_contrasena_y_avisa(client, buzon):
    from db.users import create_user
    from shared.auth_core import hash_password

    _conceder("email", "ana@empresa.example")
    create_user(email="ana@empresa.example", password_hash=hash_password(_PASSWORD))

    resp = _alta(client, "ana@empresa.example", _OTRA)

    assert resp.status_code == 202
    assert buzon.enviados[-1]["subject"] == "Ya tienes una cuenta en TenderFlow"
    assert buzon.ultimo_token("/restablecer-contrasena")
    login = client.post(_LOGIN, json={"email": "ana@empresa.example", "password": _PASSWORD})
    assert login.status_code == 200, login.text


def test_cuenta_solo_google_estrena_contrasena_con_el_enlace_del_alta(client, buzon):
    from db.users import get_or_create_oauth_user

    _conceder("email", "ana@empresa.example")
    get_or_create_oauth_user(
        email="ana@empresa.example", oauth_provider="google", oauth_sub="sub-ana"
    )

    assert _alta(client, "ana@empresa.example").status_code == 202
    reset = buzon.ultimo_token("/restablecer-contrasena")
    confirm = client.post(_CONFIRM, json={"token": reset, "password": _OTRA})

    assert confirm.status_code == 200, confirm.text
    login = client.post(_LOGIN, json={"email": "ana@empresa.example", "password": _OTRA})
    assert login.status_code == 200, login.text


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def test_se_entra_con_el_correo_escrito_con_mayusculas_como_en_el_alta(client, buzon):
    """El alta cerrada guarda el correo en minúsculas; el login no puede exigirlo."""
    _conceder("email", "ana@empresa.example")
    _alta(client, "Ana@Empresa.example")
    client.post(_VERIFY, json={"token": buzon.ultimo_token("/verificar-correo")})
    client.cookies.clear()

    login = client.post(_LOGIN, json={"email": "Ana@Empresa.example", "password": _PASSWORD})

    assert login.status_code == 200, login.text


def test_login_sin_verificar_da_403_con_la_contrasena_buena_y_401_con_la_mala(client, buzon):
    _conceder("email", "ana@empresa.example")
    _alta(client, "ana@empresa.example")

    buena = client.post(_LOGIN, json={"email": "ana@empresa.example", "password": _PASSWORD})
    mala = client.post(_LOGIN, json={"email": "ana@empresa.example", "password": _OTRA})

    assert buena.status_code == 403
    assert buena.json()["detail"] == "email_not_verified"
    assert mala.status_code == 401


def test_revocar_la_concesion_corta_el_login_con_contrasena_salvo_al_admin(client, buzon):
    from db.access_grants import revoke_access
    from db.users import create_user, set_admin
    from shared.auth_core import hash_password

    grant_ana = _conceder("email", "ana@empresa.example")
    grant_admin = _conceder("email", "jefa@empresa.example")
    create_user(email="ana@empresa.example", password_hash=hash_password(_PASSWORD))
    admin_id = create_user(email="jefa@empresa.example", password_hash=hash_password(_PASSWORD))
    set_admin(admin_id, True)
    revoke_access(grant_ana)
    revoke_access(grant_admin)

    ana = client.post(_LOGIN, json={"email": "ana@empresa.example", "password": _PASSWORD})
    jefa = client.post(_LOGIN, json={"email": "jefa@empresa.example", "password": _PASSWORD})

    assert ana.status_code == 403
    assert ana.json()["detail"] == "access_not_granted"
    assert jefa.status_code == 200, jefa.text


# ---------------------------------------------------------------------------
# Persistencia: Google, reset y cuentas existentes
# ---------------------------------------------------------------------------


def test_google_sobre_cuenta_sin_verificar_la_verifica_y_borra_su_contrasena(tmp_db):
    from db.email_verification import register_unverified
    from db.users import get_or_create_oauth_user, get_user_by_id

    estado, user_id = register_unverified(
        email="ana@empresa.example",
        password_hash="hash-de-un-tercero",  # pragma: allowlist secret
        display_name=None,
        token_hash="t" * 64,
        expires_at="2999-01-01T00:00:00+00:00",
    )
    assert estado == "created"

    vinculada = get_or_create_oauth_user(
        email="ana@empresa.example", oauth_provider="google", oauth_sub="sub-ana"
    )

    assert vinculada == user_id
    user = get_user_by_id(vinculada)
    assert user is not None
    assert user["password_hash"] is None
    assert user["email_verified_at"] is not None


def test_google_sobre_cuenta_verificada_conserva_su_contrasena(tmp_db):
    from db.users import create_user, get_or_create_oauth_user, get_user_by_id

    user_id = create_user(email="ana@empresa.example", password_hash="hash-propio")
    get_or_create_oauth_user(
        email="ana@empresa.example", oauth_provider="google", oauth_sub="sub-ana"
    )

    user = get_user_by_id(user_id)
    assert user is not None
    assert user["password_hash"] == "hash-propio"  # pragma: allowlist secret


def test_consumir_un_reset_verifica_la_cuenta(tmp_db):
    from db.email_verification import register_unverified
    from db.password_reset import consume_reset_token, create_reset_token_for_user
    from db.users import get_user_by_id

    _, user_id = register_unverified(
        email="ana@empresa.example",
        password_hash="hash",  # pragma: allowlist secret
        display_name=None,
        token_hash="t" * 64,
        expires_at="2999-01-01T00:00:00+00:00",
    )
    assert user_id is not None
    assert create_reset_token_for_user(user_id, "r" * 64, "2999-01-01T00:00:00+00:00")

    assert consume_reset_token("r" * 64, "hash-nuevo") == user_id
    user = get_user_by_id(user_id)
    assert user is not None
    assert user["email_verified_at"] is not None


def test_las_cuentas_creadas_por_otros_caminos_nacen_verificadas(tmp_db):
    """`DEFAULT NOW()` de v154: OAuth, alta abierta y scripts no saben de la columna."""
    from db.users import create_user, get_or_create_oauth_user, get_user_by_id

    local = create_user(email="local@empresa.example", password_hash="x")
    oauth = get_or_create_oauth_user(
        email="google@empresa.example", oauth_provider="google", oauth_sub="sub-g"
    )

    for user_id in (local, oauth):
        user = get_user_by_id(user_id)
        assert user is not None
        assert user["email_verified_at"] is not None


def test_la_retencion_borra_solo_las_altas_sin_verificar_abandonadas(tmp_db):
    from db.database import connect
    from db.email_verification import delete_stale_unverified, register_unverified
    from db.users import create_user, get_user_by_id

    _, abandonada = register_unverified(
        email="abandonada@empresa.example",
        password_hash="x",
        display_name=None,
        token_hash="a" * 64,
        expires_at="2999-01-01T00:00:00+00:00",
    )
    _, reciente = register_unverified(
        email="reciente@empresa.example",
        password_hash="x",
        display_name=None,
        token_hash="b" * 64,
        expires_at="2999-01-01T00:00:00+00:00",
    )
    verificada = create_user(email="vieja@empresa.example", password_hash="x")
    with connect() as connection:
        connection.execute(
            "UPDATE users SET created_at = '2020-01-01T00:00:00+00:00' WHERE id IN (%s, %s)",
            (abandonada, verificada),
        )

    assert delete_stale_unverified(7, apply=False) == 1
    assert delete_stale_unverified(7) == 1

    assert get_user_by_id(abandonada, include_deactivated=True) is None
    assert get_user_by_id(reciente, include_deactivated=True) is not None
    assert get_user_by_id(verificada, include_deactivated=True) is not None


# ---------------------------------------------------------------------------
# Correo sin configurar
# ---------------------------------------------------------------------------


def test_credenciales_que_faltan_por_backend():
    from observability.mailer import credenciales_que_faltan

    def _ajustes(**valores: Any) -> MagicMock:
        from pydantic import SecretStr

        base: dict[str, Any] = {
            "EMAIL_BACKEND": "smtp",
            "ALERT_SMTP_USER": "",
            "ALERT_SMTP_PASSWORD": SecretStr(""),
            "EMAIL_API_KEY": SecretStr(""),
            "EMAIL_FROM": "",
            "EMAIL_FROM_NAME": "TenderFlow",
        }
        base.update(valores)
        return MagicMock(**base)

    from pydantic import SecretStr

    assert credenciales_que_faltan(_ajustes()) == ["ALERT_SMTP_USER", "ALERT_SMTP_PASSWORD"]
    assert (
        credenciales_que_faltan(
            _ajustes(ALERT_SMTP_USER="yo@gmail.com", ALERT_SMTP_PASSWORD=SecretStr("abcd"))
        )
        == []
    )
    assert credenciales_que_faltan(_ajustes(EMAIL_BACKEND="resend")) == [
        "EMAIL_API_KEY",
        "EMAIL_FROM",
    ]
    assert credenciales_que_faltan(_ajustes(EMAIL_BACKEND="console")) == []
