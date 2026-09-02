"""Prórroga prevista de un contrato, leída de la ficha estructurada del pliego.

El horizonte de renovaciones se calcula con ``fecha_inicio + duración`` en el
94% de las filas, y las prórrogas sólo entraban a posteriori, cuando la fuente
cambiaba ``fecha_fin``. Pero el pliego ya dice cuánto se puede prorrogar —la
ficha estructurada extrae la cláusula en ``extensions``— así que el horizonte
puede declarar «fin previsto» y «fin máximo con prórroga» sin esperar a que
ocurra. Aquí vive la lectura de esa cláusula; es texto libre con evidencia, no
un número, y por eso el parser es conservador: si no reconoce una duración
explícita devuelve ``None`` antes que inventar meses.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

# «prórroga de 12 meses», «prorrogable por 2 años», «hasta 24 meses más»,
# «dos prórrogas anuales» (esta última se resuelve por la tabla de números).
_NUMERO_RE = r"(\d{1,3}|un|una|uno|dos|tres|cuatro|cinco|seis)"
_DURACION_RE = re.compile(
    # «6 (seis) meses» y «seis (6) meses»: la aclaración entre paréntesis no
    # cambia la cantidad, así que se salta sea número o palabra.
    rf"{_NUMERO_RE}\s*(?:\([^)]{{1,20}}\)\s*)?(a[ñn]os?|meses|mes)\b",
    re.IGNORECASE,
)
_PRORROGAS_ANUALES_RE = re.compile(
    rf"{_NUMERO_RE}\s+pr[oó]rrogas?\s+anual(?:es)?",
    re.IGNORECASE,
)
_NUMEROS = {"un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6}

#: Tope de cordura: la LCSP limita la duración total (contrato + prórrogas) a
#: cinco años en servicios ordinarios; una lectura por encima de 10 años es un
#: error de parseo, no una cláusula.
_MAX_MESES = 120


def _a_entero(token: str) -> int | None:
    token = token.strip().lower()
    if token.isdigit():
        return int(token)
    return _NUMEROS.get(token)


def meses_de_prorroga_en_texto(texto: str) -> int | None:
    """Meses de prórroga que declara un fragmento de cláusula, o ``None``.

    Si el texto menciona varias duraciones («prórroga de 12 meses, hasta un
    máximo de 24») se queda con la **mayor**: el horizonte quiere el fin
    máximo posible, que es el que decide cuándo hay que estar preparado.
    """
    if not texto:
        return None
    candidatos: list[int] = []
    for match in _DURACION_RE.finditer(texto):
        cantidad = _a_entero(match.group(1))
        if cantidad is None:
            continue
        unidad = match.group(2).lower()
        meses = cantidad * 12 if unidad.startswith("a") else cantidad
        if 0 < meses <= _MAX_MESES:
            candidatos.append(meses)
    for match in _PRORROGAS_ANUALES_RE.finditer(texto):
        cantidad = _a_entero(match.group(1))
        if cantidad is not None and 0 < cantidad * 12 <= _MAX_MESES:
            candidatos.append(cantidad * 12)
    return max(candidatos) if candidatos else None


def meses_de_prorroga(facts: dict[str, Any] | str | None) -> int | None:
    """Meses de prórroga de una ficha (dict o JSON), leyendo ``extensions``."""
    if facts is None:
        return None
    if isinstance(facts, str):
        try:
            parsed = json.loads(facts)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(parsed, dict):
            return None
        facts = parsed
    extensiones = facts.get("extensions")
    if not isinstance(extensiones, list):
        return None
    meses: list[int] = []
    for item in extensiones:
        descripcion = item.get("description") if isinstance(item, dict) else None
        leido = meses_de_prorroga_en_texto(str(descripcion or ""))
        if leido is not None:
            meses.append(leido)
    return max(meses) if meses else None


def sumar_meses(fecha_iso: str | None, meses: int | None) -> str | None:
    """``fecha_iso`` (``YYYY-MM-DD``) más ``meses``, en el mismo formato."""
    if not fecha_iso or meses is None:
        return None
    try:
        base = date.fromisoformat(str(fecha_iso)[:10])
    except ValueError:
        return None
    total = base.year * 12 + (base.month - 1) + meses
    year, month = divmod(total, 12)
    month += 1
    # El día se recorta al último del mes destino (31 de enero + 1 mes = 28/29
    # de febrero), que es lo que hace Postgres con INTERVAL '1 month'.
    from calendar import monthrange

    day = min(base.day, monthrange(year, month)[1])
    return date(year, month, day).isoformat()
