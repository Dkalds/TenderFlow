"""Tests para shared/numeric.py — igualdad tolerante al ruido de float4."""

from __future__ import annotations

import struct

from shared.numeric import FLOAT_REL_TOL, values_equal


def _float4_roundtrip(value: float) -> float:
    """Lo que devuelve una columna ``real`` de Postgres para ``value``.

    Reproduce las dos pérdidas encadenadas del camino real: el almacenamiento
    en 4 bytes (``struct`` con formato ``f``) y la serialización a texto con 6
    cifras significativas con la que el valor vuelve al cliente.
    """
    almacenado: float = struct.unpack("f", struct.pack("f", value))[0]
    return float(f"{almacenado:.6g}")


def test_roundtrip_float4_no_cuenta_como_cambio():
    """El ruido existe (el valor leído difiere) pero no es un cambio de dato."""
    # 1 000 004,5 es el caso peor: mantisa justo por encima de 1, donde el
    # redondeo a 6 cifras significativas desvía ~4,5e-6 — el orden de magnitud
    # del 4,96e-6 medido en producción.
    for importe in (12_345_678.91, 1_000_004.5, 87_654.32):
        leido = _float4_roundtrip(importe)
        assert leido != importe, f"{importe} no ejercita el round-trip"
        assert values_equal(importe, leido)


def test_tolerancia_cubre_el_desvio_maximo_medido_en_produccion():
    """4,96e-6 fue el desvío relativo máximo entre snapshot y valor actual.

    Medido el 2026-08-16 sobre las 635 filas de historial que un backfill de
    TED escribió con ``changed_fields='importe'`` sin que ningún importe
    hubiera cambiado.
    """
    base = 1_000_000.0
    assert values_equal(base, base * (1 + 4.96e-6))


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
    """Un llamador con una columna float8 puede exigir más precisión."""
    base = 100_000.0
    casi = base * (1 + 1e-6)
    assert values_equal(base, casi)
    assert not values_equal(base, casi, rel_tol=1e-9)


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
