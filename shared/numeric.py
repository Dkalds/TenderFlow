"""Igualdad de valores insensible al ruido de precisión de la BD.

``licitaciones.importe`` fue ``real`` (float4) hasta v156 y lo que se guardó
entonces no coincide exactamente con lo que traen los conectores (float8).
Comparar con ``!=`` convierte ese ruido en un cambio de dato falso, así que
todo detector de diffs sobre columnas numéricas compara a través de
``values_equal``: con :data:`FLOAT_REL_TOL` contra la fila viva y con
:data:`FLOAT_REL_TOL_HISTORIAL` contra un snapshot del historial.

Consumidores: ``db.upsert`` (historial de licitaciones), y
``services.contract_events`` y ``services.avisos`` (leen ese historial).

También vive aquí :func:`importes_en_texto`, el único lector de importes
escritos en prosa española, que antes tenía dos copias que ya divergían.
"""

from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Any

# Cota del ruido entre un importe leído de la BD y el que trae el conector.
#
# Desde v156 (2026-11-06) las columnas son ``double precision``. Un expediente
# no reingerido desde entonces guarda el valor float4 promovido a float8 tal
# cual: 24 bits de mantisa, ≤6e-8 de desvío relativo. 1e-7 cubre eso y ve
# cambios reales desde 1 € en un contrato de 10 M€. No es 0 por esas filas.
FLOAT_REL_TOL = 1e-7

# Cota cuando uno de los dos valores sale de un snapshot de
# ``licitaciones_history`` escrito mientras la columna era ``real``: el motor
# devolvía un ``real`` con 6 cifras significativas (1 000 004 → 1 000 000),
# hasta ~5e-6 de desvío relativo (medido el 2026-08-16 en 635 filas de un
# backfill de TED: máximo 4,96e-6, ningún cambio real). 1e-5 deja ~2x de margen.
# shortcut: comparar snapshots siempre con esta cota ciega cambios por debajo
# del 0,001 % también en filas nuevas: un cambio real entre 1e-7 y 1e-5 deja
# fila de historial (el upsert usa FLOAT_REL_TOL) pero no evento de contrato ni
# aviso. Pasar sus lectores a FLOAT_REL_TOL cuando el historial anterior a v156
# esté limpio (limpiar_ruido_importe_historial.py).
FLOAT_REL_TOL_HISTORIAL = 1e-5

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


# Un importe en euros en prosa española: «2.364.210,48 €», «1.500 euros»,
# «12,5 EUR». Con un solo punto y una o dos cifras detrás («1.5 €», «12.50 €»)
# el punto es decimal: leerlo como de miles daba 15 y 1250. El lookbehind
# impide empezar a mitad de un número cuya forma no encaja («1.2345 €»).
_IMPORTE_EN_TEXTO_RE = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
    r"\s*(?:€|&euro;|eur(?:os)?\b)",
    flags=re.IGNORECASE,
)
_MILES_RE = re.compile(r"\d{1,3}(?:\.\d{3})+")


def _numero_es(crudo: str) -> float:
    if "," in crudo:
        return float(crudo.replace(".", "").replace(",", "."))
    if _MILES_RE.fullmatch(crudo):
        return float(crudo.replace(".", ""))
    return float(crudo)


def importes_en_texto(texto: str) -> list[float]:
    """Los importes en euros que cita un texto, en el orden en que aparecen."""
    return [_numero_es(m.group(1)) for m in _IMPORTE_EN_TEXTO_RE.finditer(texto)]
