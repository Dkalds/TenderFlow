"""¿Pueden entrenar las etiquetas del LLM? (spec §3.5, plan de clasificación
en tres niveles, Tarea 6).

El plan usa un LLM para etiquetar el nivel 1 (``es_ti``) y las familias del
nivel 2 sobre el universo entero de licitaciones -- mucho más volumen que lo
que un humano puede revisar a mano. Antes de usar esas etiquetas para
entrenar el modelo hace falta saber si el LLM coincide con el juicio humano
lo bastante como para no envenenar el set de entrenamiento con su propio
sesgo.

La regla (spec §3.5): las etiquetas del LLM solo entrenan si su acuerdo con
los humanos en el golden es ``>= ACUERDO_MIN_ES_TI`` en ``es_ti`` y
``>= F1_MIN_FAMILIA`` de F1 en cada familia con soporte humano suficiente
(``>= SOPORTE_MIN_FAMILIA`` positivos en el golden comparable).
:func:`medir_acuerdo` es la función pura que aplica esa regla;
:meth:`db.repositories.tecnologia_pliego.TecnologiaPliegoRepository.
respuestas_llm_vigentes` trae la respuesta vigente del LLM por licitación, y
``scripts/medir_acuerdo_llm.py`` junta las dos piezas en un informe.

Uso típico::

    from db.repositories.tecnologia_pliego import TecnologiaPliegoRepository
    from services.ml.acuerdo_llm import RespuestaLlm, medir_acuerdo
    from services.ml.golden_ti import cargar_golden_ti

    golden = cargar_golden_ti()
    vigentes = TecnologiaPliegoRepository().respuestas_llm_vigentes(
        [e.id_externo for e in golden]
    )
    respuestas = {
        id_: RespuestaLlm(v["es_ti"], frozenset(v["familias"]))
        for id_, v in vigentes.items()
    }
    acuerdo = medir_acuerdo(golden, respuestas)
"""

from __future__ import annotations

from collections import Counter
from typing import NamedTuple

from services.ml.golden_ti import EjemploGoldenTi

#: Acuerdo mínimo en «¿es TI?» (nivel 1) para que las etiquetas del LLM entrenen.
ACUERDO_MIN_ES_TI = 0.90
#: F1 mínima por familia (nivel 2) con soporte suficiente en el golden.
F1_MIN_FAMILIA = 0.80
#: Soporte humano mínimo (positivos en el golden comparable) para evaluar una familia.
SOPORTE_MIN_FAMILIA = 10


class RespuestaLlm(NamedTuple):
    """La respuesta vigente del LLM para una licitación, tal como la ve el
    informe de acuerdo: sin score ni evidencia, solo lo que hace falta para
    comparar contra el golden humano.

    Attributes:
        es_ti: Lo que dijo el marcador de nivel 1, o ``None`` si el LLM no se
            pronunció (sin fila del marcador en su versión vigente).
        familias: Las familias (nivel 2) que el LLM afirmó. Sin score:
            :meth:`~db.repositories.tecnologia_pliego.
            TecnologiaPliegoRepository.respuestas_llm_vigentes` ya filtró por
            ``PLIEGO_TECH_MIN_SCORE`` antes de construir esta tupla.
    """

    es_ti: bool | None
    familias: frozenset[str]


class AcuerdoLlm(NamedTuple):
    """Resultado de :func:`medir_acuerdo`: si las etiquetas del LLM pueden
    entrenar (spec §3.5).

    Attributes:
        n_comparables: Ejemplos del golden con respuesta del LLM
            (``es_ti is not None``). El resto no se pronunció y no cuenta ni
            a favor ni en contra del acuerdo.
        acuerdo_es_ti: Fracción de ``n_comparables`` en la que el LLM coincide
            con el humano en ``es_ti``. ``None`` si ``n_comparables == 0``.
        f1_por_familia: F1 de cada familia con soporte suficiente, sobre los
            ejemplos comparables cuyo golden dice ``es_ti=True``.
        sin_soporte: Familias del golden comparable sin soporte suficiente
            (``< SOPORTE_MIN_FAMILIA`` positivos humanos), ordenadas.
        apto: Si las etiquetas del LLM pasan la regla de la spec entera.
        motivos: Un texto por cada incumplimiento (vacío si ``apto``).
    """

    n_comparables: int
    acuerdo_es_ti: float | None
    f1_por_familia: dict[str, float]
    sin_soporte: tuple[str, ...]
    apto: bool
    motivos: tuple[str, ...]


def _f1(tp: int, fp: int, fn: int) -> float:
    """F1 a mano, sin sklearn. ``1.0`` si no hubo ni aciertos ni errores: una
    familia que ni el humano ni el LLM afirman nunca falla nada."""
    if tp == 0 and fp == 0 and fn == 0:
        return 1.0
    return 2 * tp / (2 * tp + fp + fn)


def medir_acuerdo(golden: list[EjemploGoldenTi], respuestas: dict[str, RespuestaLlm]) -> AcuerdoLlm:
    """Aplica la regla de la spec §3.5 sobre un golden set y las respuestas
    vigentes del LLM para esos mismos expedientes.

    Pura: no toca la BD ni el fichero del golden -- ambos ya vienen resueltos
    por el llamador (:mod:`db.repositories.tecnologia_pliego` y
    :mod:`services.ml.golden_ti`), lo que la hace comprobable sin fixtures de
    infraestructura (ver ``tests/test_acuerdo_llm.py``).

    Args:
        golden: El golden set humano, o un subconjunto suyo (p. ej. solo
            ``holdout``) -- esta función no filtra por ``split``.
        respuestas: Respuesta vigente del LLM por ``id_externo``. Un
            expediente del golden ausente de este dict cuenta igual que uno
            presente con ``es_ti=None``: el LLM no se pronunció sobre él.

    Returns:
        El :class:`AcuerdoLlm` con el veredicto y sus motivos.
    """
    comparables: list[tuple[EjemploGoldenTi, RespuestaLlm]] = []
    for ejemplo in golden:
        respuesta = respuestas.get(ejemplo.id_externo)
        if respuesta is not None and respuesta.es_ti is not None:
            comparables.append((ejemplo, respuesta))
    n_comparables = len(comparables)

    aciertos = sum(1 for ejemplo, respuesta in comparables if respuesta.es_ti == ejemplo.es_ti)
    acuerdo_es_ti = aciertos / n_comparables if n_comparables else None

    # Soporte humano de cada familia: positivos (es_ti=True) del golden
    # comparable que la marcan. Una familia que nunca aparece ahí no se
    # evalúa ni va a `sin_soporte` -- no hay con qué juzgarla.
    soporte: Counter[str] = Counter()
    for ejemplo, _respuesta in comparables:
        if ejemplo.es_ti:
            soporte.update(ejemplo.familias)

    f1_por_familia: dict[str, float] = {}
    sin_soporte: list[str] = []
    for familia in sorted(soporte):
        if soporte[familia] < SOPORTE_MIN_FAMILIA:
            sin_soporte.append(familia)
            continue
        tp = fp = fn = 0
        for ejemplo, respuesta in comparables:
            if not ejemplo.es_ti:
                continue
            humano_dice = familia in ejemplo.familias
            llm_dice = familia in respuesta.familias
            if humano_dice and llm_dice:
                tp += 1
            elif llm_dice:
                fp += 1
            elif humano_dice:
                fn += 1
        f1_por_familia[familia] = _f1(tp, fp, fn)

    motivos: list[str] = []
    if acuerdo_es_ti is None:
        motivos.append("es_ti sin comparables")
    elif acuerdo_es_ti < ACUERDO_MIN_ES_TI:
        motivos.append(f"es_ti {acuerdo_es_ti:.2f} < {ACUERDO_MIN_ES_TI:.2f}")
    for familia, f1 in f1_por_familia.items():
        if f1 < F1_MIN_FAMILIA:
            motivos.append(f"{familia} f1 {f1:.2f} < {F1_MIN_FAMILIA:.2f}")

    apto = (
        acuerdo_es_ti is not None
        and acuerdo_es_ti >= ACUERDO_MIN_ES_TI
        and all(f1 >= F1_MIN_FAMILIA for f1 in f1_por_familia.values())
    )

    return AcuerdoLlm(
        n_comparables=n_comparables,
        acuerdo_es_ti=acuerdo_es_ti,
        f1_por_familia=f1_por_familia,
        sin_soporte=tuple(sin_soporte),
        apto=apto,
        motivos=tuple(motivos),
    )


__all__ = [
    "ACUERDO_MIN_ES_TI",
    "F1_MIN_FAMILIA",
    "SOPORTE_MIN_FAMILIA",
    "AcuerdoLlm",
    "RespuestaLlm",
    "medir_acuerdo",
]
