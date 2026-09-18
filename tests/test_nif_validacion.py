"""Validación de NIF español con letra de control (2026-09-14).

Los valores válidos de abajo están **calculados** con las reglas oficiales
(DNI/NIE: letra = tabla[n % 23]; CIF: Orden EHA/451/2008), no copiados de
personas reales. Los CIF de organismos públicos (letra Q/S/P) son de forma
pública y sirven de contraste.
"""

from __future__ import annotations

import pytest

from services.normalization import (
    clasificar_nif,
    nif_espanol_malformado,
    nif_valido,
    normalize_nif,
)


@pytest.mark.parametrize(
    "valor",
    [
        "12345678Z",  # pragma: allowlist secret
        "00000000T",  # pragma: allowlist secret
        "99999999R",  # pragma: allowlist secret
        "12.345.678-Z",  # con separadores: normaliza antes  # pragma: allowlist secret
        "12345678z",  # minúscula  # pragma: allowlist secret
    ],
)
def test_dni_valido(valor: str) -> None:
    assert clasificar_nif(valor) == "dni"
    assert nif_valido(valor)


@pytest.mark.parametrize(
    "valor",
    [
        "X1234567L",  # pragma: allowlist secret
        "Y7654321G",  # pragma: allowlist secret
        "Z0000001Y",  # pragma: allowlist secret
    ],
)
def test_nie_valido(valor: str) -> None:
    assert clasificar_nif(valor) == "nie"


@pytest.mark.parametrize(
    "valor",
    [
        "B12345674",  # control dígito obligatorio (B)  # pragma: allowlist secret
        "A58431057",  # pragma: allowlist secret
        "A00000000",  # pragma: allowlist secret
        "Q2826000H",  # control letra obligatoria (Q)  # pragma: allowlist secret
        "S2826000H",  # pragma: allowlist secret
        "P2800000H",  # pragma: allowlist secret
        "N0012345E",  # pragma: allowlist secret
        "W8765432C",  # pragma: allowlist secret
        "G12345674",  # G admite dígito o letra  # pragma: allowlist secret
        "G1234567D",  # pragma: allowlist secret
        "b-12.345.674",  # con separadores  # pragma: allowlist secret
    ],
)
def test_cif_valido(valor: str) -> None:
    assert clasificar_nif(valor) == "cif"
    assert nif_valido(valor)


@pytest.mark.parametrize(
    "valor",
    [
        "12345678A",  # letra de DNI incorrecta  # pragma: allowlist secret
        "X1234567A",  # letra de NIE incorrecta  # pragma: allowlist secret
        "B12345678",  # control de CIF incorrecto  # pragma: allowlist secret
        "B1234567D",  # B exige dígito, no letra  # pragma: allowlist secret
        "Q28260008",  # Q exige letra, no dígito  # pragma: allowlist secret
        "A5843105G",  # A exige dígito  # pragma: allowlist secret
    ],
)
def test_forma_espanola_con_control_incorrecto_es_invalido(valor: str) -> None:
    assert clasificar_nif(valor) == "invalido"
    assert not nif_valido(valor)
    assert nif_espanol_malformado(valor)


@pytest.mark.parametrize(
    "valor",
    [
        "ESB12345674",  # IVA intracomunitario con prefijo de país  # pragma: allowlist secret
        "DE123456789",  # IVA alemán  # pragma: allowlist secret
        "FR12345678901",  # pragma: allowlist secret
        "1234567",  # demasiado corto para cualquier forma española
        "ABCDEFGHI",
    ],
)
def test_identificador_extranjero_no_es_valido_ni_malformado(valor: str) -> None:
    """Un id extranjero no es un NIF, pero tampoco una errata: se conserva opaco."""
    assert clasificar_nif(valor) == "extranjero"
    assert not nif_valido(valor)
    assert not nif_espanol_malformado(valor)


@pytest.mark.parametrize("valor", [None, "", "   ", "-.-"])
def test_vacio_es_invalido_pero_no_malformado(valor: str | None) -> None:
    assert normalize_nif(valor) is None
    assert clasificar_nif(valor) == "invalido"
    assert not nif_valido(valor)
    assert not nif_espanol_malformado(valor)


def test_normalize_nif_sigue_sin_validar() -> None:
    """El contrato de ``normalize_nif`` no cambia: normaliza, no rechaza."""
    assert normalize_nif("b-12.345.678") == "B12345678"  # pragma: allowlist secret
    assert normalize_nif("DE 123 456 789") == "DE123456789"  # pragma: allowlist secret
