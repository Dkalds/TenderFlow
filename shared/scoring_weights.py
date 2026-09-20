"""Validación de los pesos del scoring — un solo sitio para las dos entradas.

Los pesos entran al sistema por dos puertas: ``settings.SCORING_WEIGHTS``
(global, vía ENV) y el perfil de usuario (``PUT /api/v1/me/profile``). La
primera estaba bien defendida; la segunda solo comprobaba que sumaran 100, así
que aceptaba ``{"foo": 100}`` —que deja las cinco dimensiones reales a 0 y
manda todo el corpus a la banda Descarte— y también pesos negativos.

Este módulo vive en ``shared/`` porque lo consumen ``config/`` y ``api/``, y
ninguno de los dos puede depender del otro.
"""

from __future__ import annotations

from collections.abc import Mapping

# Dimensiones ponderables del score. `riesgo` no está: es una penalización
# fuera de la suma, no una dimensión con peso propio.
KNOWN_WEIGHT_KEYS: frozenset[str] = frozenset(
    {"importe", "plazo", "competencia", "margen", "afinidad", "senal_tecnica"}
)

WEIGHTS_TOTAL = 100

#: Penalizaciones con peso configurable (F1.4). **No son dimensiones**: no
#: entran en la suma de 100 ni en el reparto de afinidad, y su valor son los
#: puntos que se restan cuando la fila tiene el flag del mismo nombre. Viven en
#: el mismo mapa que los pesos porque el plan lo pide así —«el peso vive en
#: `SCORING_WEIGHTS` y el perfil puede ponerlo a cero»— y porque una segunda
#: variable de entorno sería otro sitio que olvidar al revisar el scoring.
PENALTY_WEIGHT_KEYS: frozenset[str] = frozenset({"organo_anula_frecuente"})

#: Techo de una penalización. Más de 30 puntos sacaría de «Caliente» a
#: «Descarte» cualquier expediente por una sola señal estadística.
PENALTY_MAX = 30


def dimension_weights(weights: Mapping[str, int]) -> dict[str, int]:
    """Solo las dimensiones ponderables, sin las penalizaciones."""
    return {k: int(v) for k, v in weights.items() if k not in PENALTY_WEIGHT_KEYS}


def penalty_weights(weights: Mapping[str, int]) -> dict[str, int]:
    """Solo las penalizaciones presentes en ``weights``."""
    return {k: int(v) for k, v in weights.items() if k in PENALTY_WEIGHT_KEYS}


def validate_scoring_weights(weights: Mapping[str, int], *, source: str = "weights") -> None:
    """Valida un mapa de pesos. Lanza ``ValueError`` con el motivo concreto.

    ``source`` nombra el origen en el mensaje de error (``SCORING_WEIGHTS``
    para el global, ``weights`` para el perfil), que es lo que acaba viendo el
    usuario en el 422 o el operador en el arranque.

    Las penalizaciones (:data:`PENALTY_WEIGHT_KEYS`) son opcionales, van de 0 a
    :data:`PENALTY_MAX` y no cuentan en la suma de 100.
    """
    permitidas = KNOWN_WEIGHT_KEYS | PENALTY_WEIGHT_KEYS
    for key, val in weights.items():
        if key not in permitidas:
            raise ValueError(
                f"{source} contiene clave desconocida: {key!r}. "
                f"Claves permitidas: {sorted(permitidas)}"
            )
        if val < 0:
            raise ValueError(
                f"{source}[{key!r}] = {val} es negativo. Todos los pesos deben ser >= 0."
            )
        if key in PENALTY_WEIGHT_KEYS and val > PENALTY_MAX:
            raise ValueError(
                f"{source}[{key!r}] = {val} supera el máximo de una penalización ({PENALTY_MAX})."
            )

    total = sum(dimension_weights(weights).values())
    if total != WEIGHTS_TOTAL:
        raise ValueError(
            f"{source} suma {total}, debe ser exactamente {WEIGHTS_TOTAL}. "
            f"Valores actuales: {dict(weights)}"
        )

    # Con afinidad al 100% el resto de dimensiones desaparece, y si además el
    # perfil no tiene keywords la redistribución se queda sin nada que repartir.
    afinidad = weights.get("afinidad", 0)
    if afinidad >= WEIGHTS_TOTAL:
        raise ValueError(f"{source}['afinidad'] = {afinidad} debe ser < {WEIGHTS_TOTAL}.")
