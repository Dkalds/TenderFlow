"""Un código TOTP con dígitos no ASCII es un código incorrecto, no un error."""

from __future__ import annotations

from db.totp import verify_totp


def test_un_codigo_totp_con_digitos_no_ascii_es_incorrecto_y_no_un_error() -> None:
    """Los dígitos arábigo-índicos son ``isdecimal`` y hacían lanzar a ``compare_digest``."""
    codigo = "".join(map(chr, range(0x661, 0x667)))
    assert codigo.isdecimal() and len(codigo) == 6

    assert verify_totp("JBSWY3DPEHPK3PXP", codigo) is False
