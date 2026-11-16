"""Dos entradas de borde que el gemelo Python y el verificador trataban mal."""

from __future__ import annotations

import pytest

from db.sql_fragments import cpv4
from db.totp import verify_totp


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("72200000", "7220"),
        ("722", ""),  # el SQL exige cuatro dígitos (`^[0-9]{4}`): tres no son clave
        (" 72200000", ""),
        # Dígitos arábigo-índicos: `isdigit` los acepta, el regex de Postgres no.
        ("".join(map(chr, (0x667, 0x662, 0x662, 0x660))) + "0000", ""),
        (None, ""),
    ],
)
def test_cpv4_espeja_el_ancla_del_sql(valor: str | None, esperado: str) -> None:
    assert cpv4(valor) == esperado


def test_un_codigo_totp_con_digitos_no_ascii_es_incorrecto_y_no_un_error() -> None:
    """«١٢٣٤٥٦» es ``isdecimal`` y hacía lanzar a ``compare_digest`` (un 500)."""
    assert verify_totp("JBSWY3DPEHPK3PXP", "١٢٣٤٥٦") is False
