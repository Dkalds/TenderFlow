"""Servicio del alta cerrada con verificación de correo (``services/email_verification.py``).

Los recorridos por la API viven en ``tests/test_auth_alta_cerrada.py``; aquí se
fijan las piezas del servicio que ese recorrido no deja ver: qué se guarda del
token (solo su hash), cuánto vive, dónde viaja en el enlace, qué correo sale en
cada rama del alta y que la tarea en segundo plano nunca lanza.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import quote

import pytest

import services.email_verification as ev

_ORIGEN = "https://app.example"
_CORREO = "ana@empresa.example"
_CLAVE = "AltaCerrada2026"  # pragma: allowlist secret # gitleaks:allow


def _url(path: str) -> str:
    return f"{_ORIGEN}{path}"


@pytest.fixture()
def buzon() -> Iterator[MagicMock]:
    """Origen del frontend conocido y un envío falso que siempre sale."""
    envio = MagicMock(return_value=True)
    with (
        patch.object(ev, "url_absoluta", side_effect=_url),
        patch.object(ev, "enviar_email_transaccional", new=envio),
    ):
        yield envio


@pytest.fixture()
def alta() -> Iterator[dict[str, MagicMock]]:
    """``process_registration`` con la persistencia y los envíos doblados."""
    with (
        patch.object(ev, "register_unverified") as registrar,
        patch.object(ev, "log_event") as auditar,
        patch.object(ev, "create_reset_token_for_user", return_value=True) as crear_reset,
        patch.object(ev, "send_verification_email") as verificar,
        patch.object(ev, "send_existing_account_email") as ya_tienes,
    ):
        yield {
            "registrar": registrar,
            "auditar": auditar,
            "crear_reset": crear_reset,
            "verificar": verificar,
            "ya_tienes": ya_tienes,
        }


# ── Token ───────────────────────────────────────────────────────────────────


def test_el_token_emitido_se_guarda_solo_como_su_sha256() -> None:
    raw, digest, _ = ev.issue_verification_token()

    assert digest == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert raw not in digest


def test_el_token_emitido_caduca_a_las_24_horas() -> None:
    antes = datetime.now(UTC)

    _, _, expires_at = ev.issue_verification_token()

    caducidad = datetime.fromisoformat(expires_at)
    assert caducidad.tzinfo is not None
    esperado = antes + timedelta(hours=ev.VERIFICACION_TTL_HORAS)
    assert esperado <= caducidad <= esperado + timedelta(seconds=5)


def test_dos_emisiones_no_repiten_token() -> None:
    primero, _, _ = ev.issue_verification_token()
    segundo, _, _ = ev.issue_verification_token()

    assert primero != segundo
    assert len(primero) >= 43  # 32 bytes en base64url


# ── Correos ─────────────────────────────────────────────────────────────────


def test_el_enlace_de_activacion_lleva_el_token_en_el_fragmento(buzon: MagicMock) -> None:
    token = "a+b/c=d"  # caracteres que hay que escapar en una URL

    assert ev.send_verification_email(_CORREO, token) is True

    texto = buzon.call_args.kwargs["texto"]
    assert f"{_ORIGEN}/verificar-correo#token={quote(token)}" in texto
    assert "?token=" not in texto


def test_sin_origen_del_frontend_no_se_envia_correo_de_activacion() -> None:
    envio = MagicMock(return_value=True)
    with (
        patch.object(ev, "url_absoluta", return_value=None),
        patch.object(ev, "enviar_email_transaccional", new=envio),
    ):
        enviado = ev.send_verification_email(_CORREO, "tok")

    assert enviado is False
    envio.assert_not_called()


def test_el_correo_ya_tienes_cuenta_enlaza_al_restablecimiento(buzon: MagicMock) -> None:
    ev.send_existing_account_email(_CORREO, "reset-tok")

    kwargs = buzon.call_args.kwargs
    assert kwargs["subject"] == "Ya tienes una cuenta en TenderFlow"
    assert f"{_ORIGEN}/restablecer-contrasena#token=reset-tok" in kwargs["texto"]


def test_el_log_del_envio_no_lleva_ni_el_token_ni_el_correo(buzon: MagicMock) -> None:
    token = "token-secreto-de-prueba"
    with patch.object(ev, "log") as log:
        ev.send_verification_email(_CORREO, token)

    volcado = repr(log.mock_calls)
    assert token not in volcado
    assert _CORREO not in volcado
    assert "empresa.example" in volcado


def test_un_envio_fallido_se_registra_como_aviso(buzon: MagicMock) -> None:
    buzon.return_value = False
    with patch.object(ev, "log") as log:
        enviado = ev.send_verification_email(_CORREO, "tok")

    assert enviado is False
    log.warning.assert_called_once()
    log.info.assert_not_called()


# ── process_registration ────────────────────────────────────────────────────


def test_alta_nueva_manda_el_token_cuyo_hash_se_guardo(alta: dict[str, MagicMock]) -> None:
    alta["registrar"].return_value = ("created", 7)

    ev.process_registration(_CORREO, _CLAVE, "Ana")

    guardado = alta["registrar"].call_args.kwargs["token_hash"]
    correo, raw = alta["verificar"].call_args.args
    assert correo == _CORREO
    assert hashlib.sha256(raw.encode("utf-8")).hexdigest() == guardado
    alta["ya_tienes"].assert_not_called()


def test_alta_guarda_el_hash_de_la_contrasena_y_no_la_contrasena(
    alta: dict[str, MagicMock],
) -> None:
    from shared.auth_core import verify_password

    alta["registrar"].return_value = ("created", 7)

    ev.process_registration(_CORREO, _CLAVE, None)

    password_hash = alta["registrar"].call_args.kwargs["password_hash"]
    assert password_hash != _CLAVE
    assert verify_password(_CLAVE, password_hash)


def test_alta_que_reemplaza_una_sin_verificar_manda_enlace_nuevo(
    alta: dict[str, MagicMock],
) -> None:
    alta["registrar"].return_value = ("replaced", 7)

    ev.process_registration(_CORREO, _CLAVE, None)

    alta["verificar"].assert_called_once()
    alta["crear_reset"].assert_not_called()


def test_alta_sobre_cuenta_verificada_manda_reset_de_30_minutos(
    alta: dict[str, MagicMock],
) -> None:
    alta["registrar"].return_value = ("verified", 7)
    antes = datetime.now(UTC)

    ev.process_registration(_CORREO, _CLAVE, None)

    user_id, guardado, expires_at = alta["crear_reset"].call_args.args
    correo, raw = alta["ya_tienes"].call_args.args
    assert (user_id, correo) == (7, _CORREO)
    assert hashlib.sha256(raw.encode("utf-8")).hexdigest() == guardado
    assert datetime.fromisoformat(expires_at) <= antes + timedelta(minutes=30, seconds=5)
    alta["verificar"].assert_not_called()


def test_sin_token_de_reset_no_sale_el_correo_ya_tienes_cuenta(
    alta: dict[str, MagicMock],
) -> None:
    alta["registrar"].return_value = ("verified", 7)
    alta["crear_reset"].return_value = False

    ev.process_registration(_CORREO, _CLAVE, None)

    alta["ya_tienes"].assert_not_called()


def test_alta_sobre_cuenta_desactivada_no_manda_nada_y_audita_fallo(
    alta: dict[str, MagicMock],
) -> None:
    alta["registrar"].return_value = ("deactivated", 7)

    ev.process_registration(_CORREO, _CLAVE, None)

    alta["verificar"].assert_not_called()
    alta["ya_tienes"].assert_not_called()
    auditoria: dict[str, Any] = alta["auditar"].call_args.kwargs
    assert auditoria["outcome"] == "failure"
    assert auditoria["detail"] == {"estado": "deactivated"}


def test_la_auditoria_del_alta_no_lleva_el_correo(alta: dict[str, MagicMock]) -> None:
    alta["registrar"].return_value = ("created", 7)

    ev.process_registration(_CORREO, _CLAVE, None)

    assert _CORREO not in repr(alta["auditar"].call_args)


def test_un_fallo_de_la_bd_no_escapa_de_la_tarea(alta: dict[str, MagicMock]) -> None:
    alta["registrar"].side_effect = RuntimeError("bd caída")

    ev.process_registration(_CORREO, _CLAVE, None)  # no lanza

    alta["verificar"].assert_not_called()


# ── Contra Postgres ─────────────────────────────────────────────────────────


def _verificar_alta(buzon: MagicMock) -> str:
    """Hace el alta y devuelve el token bruto que llegó por correo."""
    ev.process_registration(_CORREO, _CLAVE, None)
    texto = buzon.call_args.kwargs["texto"]
    return texto.split("#token=", 1)[1].split()[0]


def test_la_bd_guarda_el_hash_y_no_el_token(tmp_db: Any, buzon: MagicMock) -> None:
    db_mod, _ = tmp_db

    raw = _verificar_alta(buzon)

    with db_mod.connect_read() as c:
        guardados = [
            str(f[0])
            for f in c.execute("SELECT token_hash FROM email_verification_tokens").fetchall()
        ]
    assert guardados == [hashlib.sha256(raw.encode("utf-8")).hexdigest()]


def test_un_enlace_caducado_no_verifica_la_cuenta(tmp_db: Any, buzon: MagicMock) -> None:
    from db.email_verification import consume_verification_token

    db_mod, _ = tmp_db
    raw = _verificar_alta(buzon)
    with db_mod.connect() as c:
        c.execute("UPDATE email_verification_tokens SET expires_at = NOW() - interval '1 minute'")

    assert consume_verification_token(ev.token_hash(raw)) is None
    with db_mod.connect_read() as c:
        fila = c.execute("SELECT email_verified_at FROM users").fetchone()
    assert fila is not None and fila[0] is None


def test_un_enlace_ya_usado_no_vuelve_a_valer(tmp_db: Any, buzon: MagicMock) -> None:
    from db.email_verification import consume_verification_token

    raw = _verificar_alta(buzon)
    digest = ev.token_hash(raw)

    primero = consume_verification_token(digest)
    segundo = consume_verification_token(digest)

    assert primero is not None
    assert segundo is None
