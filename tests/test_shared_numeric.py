"""Tests para shared/numeric.py — igualdad tolerante al ruido de float4."""

from __future__ import annotations

import struct

import pytest

from shared.numeric import (
    FLOAT_REL_TOL,
    FLOAT_REL_TOL_HISTORIAL,
    importes_en_texto,
    values_equal,
)


def _float4_almacenado(value: float) -> float:
    """El valor float4 promovido a float8: lo que dejó guardado el ``ALTER`` de v156."""
    almacenado: float = struct.unpack("f", struct.pack("f", value))[0]
    return almacenado


def _float4_roundtrip(value: float) -> float:
    """Lo que devolvía una columna ``real`` de Postgres para ``value`` (antes de v156).

    Reproduce las dos pérdidas encadenadas del camino real: el almacenamiento
    en 4 bytes (``struct`` con formato ``f``) y la serialización a texto con 6
    cifras significativas con la que el valor vuelve al cliente.
    """
    return float(f"{_float4_almacenado(value):.6g}")


def test_float4_promovido_no_cuenta_como_cambio_contra_la_fila_viva():
    """Un expediente no reingerido desde v156 guarda el float4 promovido a float8."""
    for importe in (12_345_678.91, 87_654.32, 11_782_154.55):
        guardado = _float4_almacenado(importe)
        assert guardado != importe, f"{importe} no ejercita la promoción"
        assert values_equal(guardado, importe)


def test_contra_la_fila_viva_se_ve_un_cambio_de_euro_y_medio_en_diez_millones():
    assert not values_equal(10_000_000.0, 10_000_001.5)


def test_roundtrip_float4_no_cuenta_como_cambio_contra_un_snapshot():
    """El ruido existe (el valor leído difiere) pero no es un cambio de dato."""
    # 1 000 004,5 es el caso peor: mantisa justo por encima de 1, donde el
    # redondeo a 6 cifras significativas desvía ~4,5e-6 — el orden de magnitud
    # del 4,96e-6 medido en producción.
    for importe in (12_345_678.91, 1_000_004.5, 87_654.32):
        leido = _float4_roundtrip(importe)
        assert leido != importe, f"{importe} no ejercita el round-trip"
        assert values_equal(importe, leido, rel_tol=FLOAT_REL_TOL_HISTORIAL)
        # Por eso los lectores del historial no usan la cota de la fila viva.
        assert not values_equal(importe, leido)


def test_tolerancia_cubre_el_desvio_maximo_medido_en_produccion():
    """4,96e-6 fue el desvío relativo máximo entre snapshot y valor actual.

    Medido el 2026-08-16 sobre las 635 filas de historial que un backfill de
    TED escribió con ``changed_fields='importe'`` sin que ningún importe
    hubiera cambiado.
    """
    base = 1_000_000.0
    assert values_equal(base, base * (1 + 4.96e-6), rel_tol=FLOAT_REL_TOL_HISTORIAL)


def test_tolerancia_no_tapa_una_modificacion_real():
    # Modificación contractual típica: +2 % sobre 500 k€.
    assert not values_equal(500_000.0, 510_000.0)
    # Y tampoco una mucho más fina: 50 € sobre 500 k€ (1e-4 relativo, 10x la
    # tolerancia). El umbral separa ruido de dato, no "grande" de "pequeño".
    assert not values_equal(500_000.0, 500_050.0)


def test_frontera_de_la_tolerancia():
    base = 100_000.0
    assert values_equal(base, base * (1 + FLOAT_REL_TOL / 2))
    assert not values_equal(base, base * (1 + FLOAT_REL_TOL * 10))


def test_rel_tol_es_parametrizable():
    """Un lector del historial afloja la cota; la fila viva no."""
    base = 100_000.0
    casi = base * (1 + 1e-6)
    assert not values_equal(base, casi)
    assert values_equal(base, casi, rel_tol=FLOAT_REL_TOL_HISTORIAL)


def test_none_solo_es_igual_a_none():
    """Semántica preservada del ``!=`` anterior: NULL no es 0."""
    assert values_equal(None, None)
    assert not values_equal(None, 0.0)
    assert not values_equal(1000.0, None)


def test_cero_es_estable():
    """La tolerancia relativa exige igualdad exacta en 0; el suelo absoluto no."""
    assert values_equal(0.0, 0.0)
    assert values_equal(0.0, 1e-12)
    assert not values_equal(0.0, 1.0)


def test_texto_se_compara_exacto():
    """La tolerancia es de números: estados y fechas siguen con igualdad exacta."""
    assert values_equal("PUB", "PUB")
    assert not values_equal("PUB", "ADJ")
    assert not values_equal("2026-08-15T21:59:00+00:00", "2026-09-01T21:59:00+00:00")
    # Un número y su texto no son el mismo valor (el snapshot JSON guarda el
    # tipo original, y confundirlos ocultaría un cambio de forma del dato).
    assert not values_equal(1000.0, "1000.0")


def test_bool_no_entra_en_la_comparacion_numerica():
    """``bool`` es subclase de ``int``; darle tolerancia no tendría sentido."""
    assert values_equal(True, True)
    assert not values_equal(True, 1.000001)


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Importe: 2.364.210,48 €", [2364210.48]),
        ("1.500 euros", [1500.0]),
        ("50000 EUR", [50000.0]),
        ("12,5 €", [12.5]),
        # Un solo punto con una o dos cifras detrás es decimal, no de miles.
        ("1.5 €", [1.5]),
        ("12.50 €", [12.5]),
        ("300.000,00 euros y 1.200.000 €", [300000.0, 1200000.0]),
        ("Importe: 7&euro;", [7.0]),
        # Ni una forma ambigua ni un número sin moneda cuentan como importe.
        ("1.2345 €", []),
        ("expediente 2026/123", []),
        ("12 europeos", []),
    ],
)
def test_importes_en_texto(texto, esperado):
    assert importes_en_texto(texto) == esperado
