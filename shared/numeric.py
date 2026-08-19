"""Igualdad de valores insensible al ruido de precisión de la BD.

``licitaciones.importe`` es ``real`` (float4, 4 bytes) en producción mientras
que los conectores producen ``float`` de Python (float8): el valor que se lee
de vuelta **nunca** coincide exactamente con el que se escribió. Comparar con
``!=`` convierte ese ruido en un cambio de dato falso, así que todo detector de
diffs sobre columnas numéricas compara a través de ``values_equal``.

Consumidores: ``db.upsert`` (historial de licitaciones) y
``services.contract_events`` (eventos derivados de ese historial).
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

# Cota del ruido del round-trip float8 → float4 → float8.
#
# El almacenamiento aporta poco: float4 tiene 24 bits de mantisa, o sea ≤6e-8
# de desvío relativo. Lo que domina es la representación con la que el valor
# vuelve del motor: un ``real`` se serializa con 6 cifras significativas, y
# redondear a 6 cifras un número cuya mantisa está justo por encima de 1
# (1 000 004 → 1 000 000) da hasta ~5e-6 de desvío relativo.
#
# Medido en producción el 2026-08-16 sobre las 635 filas que un backfill de TED
# escribió en ``licitaciones_history`` con ``changed_fields='importe'``: el
# desvío relativo máximo entre el snapshot y el valor actual fue 4,96e-6 y
# ningún importe había cambiado de verdad.
#
# 1e-5 deja ~2x de margen sobre esa cota. En el otro sentido ignora cambios por
# debajo del 0,001 % —10 € en un contrato de 1 M€—, dos órdenes de magnitud por
# debajo de cualquier modificación contractual real y del mismo orden que lo
# que la propia columna float4 puede representar a esa magnitud (~0,06 €).
FLOAT_REL_TOL = 1e-5

# Suelo absoluto: la tolerancia relativa exige igualdad exacta alrededor de
# cero (rel_tol * 0 == 0), así que sin esto un 0.0 comparado con un residuo
# numérico volvería a contar como cambio.
FLOAT_ABS_TOL = 1e-9


def _is_number(value: Any) -> bool:
    """True si el valor entra en la comparación numérica con tolerancia.

    ``bool`` queda fuera a propósito: es subclase de ``int`` en Python y
    aplicarle tolerancia no tiene sentido para un campo de dos estados.
    """
    return isinstance(value, int | float | Decimal) and not isinstance(value, bool)


def values_equal(old: Any, new: Any, *, rel_tol: float = FLOAT_REL_TOL) -> bool:
    """Compara dos valores de una misma columna tolerando el ruido de float4.

    Dos números son iguales si su diferencia relativa cabe dentro de
    ``rel_tol``. Para cualquier otro par (texto, fechas ISO, ``None``) es la
    igualdad exacta de Python: la tolerancia se aplica sólo donde el motor pudo
    haber perdido precisión, nunca sobre estados o fechas.
    """
    if old is None or new is None:
        return old is None and new is None
    if _is_number(old) and _is_number(new):
        return math.isclose(float(old), float(new), rel_tol=rel_tol, abs_tol=FLOAT_ABS_TOL)
    return bool(old == new)
