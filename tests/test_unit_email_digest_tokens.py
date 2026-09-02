"""Los tokens de baja degradan sin romper el envío y verifican en cerrado."""

from __future__ import annotations

from unittest.mock import patch

from services.email_digest import token_de_baja, url_de_baja_alertas, verificar_token_de_baja


def test_sin_claves_de_firma_no_hay_token_ni_enlace_pero_no_se_lanza() -> None:
    with patch("shared.signing.sign", side_effect=RuntimeError("sin SIGNING_KEY")):
        assert token_de_baja("clave-de-prueba-a") is None
        assert url_de_baja_alertas("clave-de-prueba-a", "https://app.example") is None


def test_un_fallo_del_verificador_cuenta_como_firma_invalida() -> None:
    with patch("shared.signing.verify", side_effect=RuntimeError("kid desconocido")):
        assert verificar_token_de_baja("clave-de-prueba-a", "k1.firma") is False


def test_entradas_vacias_no_firman_ni_verifican() -> None:
    assert token_de_baja("") is None
    assert verificar_token_de_baja("", "k1.firma") is False
    assert verificar_token_de_baja("clave-de-prueba-a", "") is False


def test_sin_sitio_conocido_no_se_inventa_una_url_de_baja() -> None:
    assert url_de_baja_alertas("clave-de-prueba-a", None) is None
