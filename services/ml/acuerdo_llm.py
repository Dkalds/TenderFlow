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
``>= F1_MIN_FAMILIA`` de F1 en cada familia con soporte suficiente. El soporte
de una familia son sus aciertos y errores (``tp + fp + fn``) sobre los
comparables que el humano dice TI, es decir, los positivos del humano **o**
del LLM: una familia que el LLM afirma y ningún humano confirma también se
juzga. Por debajo de ``SOPORTE_MIN_FAMILIA`` casos la familia no decide y se
lista en ``sin_soporte``. Familia es nivel 2 (``TECH_LABEL_TIPO ==
"categoria"``): los fabricantes que el LLM nombra no entran en esta cuenta.
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
from collections.abc import Iterable
from typing import NamedTuple

from config.keywords import TECH_LABEL_TIPO
from services.ml.golden_ti import EjemploGoldenTi

#: Acuerdo mínimo en «¿es TI?» (nivel 1) para que las etiquetas del LLM entrenen.
ACUERDO_MIN_ES_TI = 0.90
#: F1 mínima por familia (nivel 2) con soporte suficiente en el golden.
F1_MIN_FAMILIA = 0.80
#: Casos mínimos (``tp + fp + fn`` sobre los comparables que el humano dice TI)
#: para evaluar una familia.
SOPORTE_MIN_FAMILIA = 10


class RespuestaLlm(NamedTuple):
    """La respuesta vigente del LLM para una licitación, tal como la ve el
    informe de acuerdo: sin score ni evidencia, solo lo que hace falta para
    comparar contra el golden humano.

    Attributes:
        es_ti: Lo que dijo el marcador de nivel 1, o ``None`` si el LLM no se
            pronunció -- sin fila del marcador en su versión vigente, o con
            ``SIN_EVIDENCIA_SENTINEL`` en ella: las familias no sostuvieron
            su cita, y esa respuesta entera no entrena
            (``scheduler/jobs/llm_tech_labeling.py`` no escribe feedback para
            esas licitaciones), aunque la misma versión también traiga el
            marcador -- ver
            :func:`~db.repositories.tecnologia_pliego.
            _respuesta_desde_filas_vigentes`.
        familias: Las etiquetas que el LLM afirmó. Sin score:
            :meth:`~db.repositories.tecnologia_pliego.
            TecnologiaPliegoRepository.respuestas_llm_vigentes` ya filtró por
            ``PLIEGO_TECH_MIN_SCORE`` antes de construir esta tupla. Ese
            lector no separa niveles, así que puede traer también fabricantes;
            :func:`medir_acuerdo` se queda solo con las categorías.
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
            ejemplos comparables cuyo golden dice ``es_ti=True``. Soporte son
            los casos ``tp + fp + fn`` de la familia ahí: positivos del humano
            o del LLM.
        sin_soporte: Familias con algún caso pero menos de
            ``SOPORTE_MIN_FAMILIA``, incluidas las que solo afirma el LLM,
            ordenadas. Una familia sin ningún caso no aparece.
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


def _solo_familias(etiquetas: Iterable[str]) -> frozenset[str]:
    """Las etiquetas de nivel 2 (categorías): el fabricante es nivel 3."""
    return frozenset(e for e in etiquetas if TECH_LABEL_TIPO.get(e) == "categoria")


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

    # Casos de cada familia sobre los comparables que el humano dice TI:
    # aciertos (tp) y errores de los dos lados (fp, fn). El soporte es su suma,
    # no solo los positivos humanos: con esos, una familia que el LLM afirma
    # y ningún humano confirma nunca se evaluaría ni saldría en `sin_soporte`.
    tp: Counter[str] = Counter()
    fp: Counter[str] = Counter()
    fn: Counter[str] = Counter()
    for ejemplo, respuesta in comparables:
        if not ejemplo.es_ti:
            continue
        humanas = _solo_familias(ejemplo.familias)
        del_llm = _solo_familias(respuesta.familias)
        tp.update(humanas & del_llm)
        fp.update(del_llm - humanas)
        fn.update(humanas - del_llm)

    f1_por_familia: dict[str, float] = {}
    sin_soporte: list[str] = []
    for familia in sorted(tp.keys() | fp.keys() | fn.keys()):
        if tp[familia] + fp[familia] + fn[familia] < SOPORTE_MIN_FAMILIA:
            sin_soporte.append(familia)
            continue
        f1_por_familia[familia] = _f1(tp[familia], fp[familia], fn[familia])

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
