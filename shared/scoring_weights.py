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


def validate_scoring_weights(weights: Mapping[str, int], *, source: str = "weights") -> None:
    """Valida un mapa de pesos. Lanza ``ValueError`` con el motivo concreto.

    ``source`` nombra el origen en el mensaje de error (``SCORING_WEIGHTS``
    para el global, ``weights`` para el perfil), que es lo que acaba viendo el
    usuario en el 422 o el operador en el arranque.
    """
    for key, val in weights.items():
        if key not in KNOWN_WEIGHT_KEYS:
            raise ValueError(
                f"{source} contiene clave desconocida: {key!r}. "
                f"Claves permitidas: {sorted(KNOWN_WEIGHT_KEYS)}"
            )
        if val < 0:
            raise ValueError(
                f"{source}[{key!r}] = {val} es negativo. Todos los pesos deben ser >= 0."
            )

    total = sum(weights.values())
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
