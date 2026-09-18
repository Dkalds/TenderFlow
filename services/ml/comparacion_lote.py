"""Backtest del modelo de baja por lote contra el agregado, sobre los mismos lotes.

El backlog P2 «Modelo de baja por lote» condiciona sustituir el agregado a una
medida: el ``mae_p50`` por lote tiene que mejorar al actual. Hay dos formas de
tomarla, y este módulo aporta la que no depende de haber servido nada:

- **Servida** (``services.ml.calibration.comparar_mae_p50``): empareja las
  predicciones que ``predicciones_baja`` guardó con las bajas que luego se
  observaron. Es la medida definitiva, pero solo existe después de que el batch
  por lote (``ML_BAJA_POR_LOTE``) haya corrido meses: hasta entonces todos los
  lotes se evalúan contra la fila del expediente y ``n_prediccion_por_lote``
  vale 0.
- **Backtest** (:func:`backtest_mae_p50_por_lote`, aquí): un corte temporal,
  los dos modelos entrenados con lo que ya estaba adjudicado antes del corte, y
  los dos evaluados sobre **exactamente los mismos lotes** publicados después.
  Responde hoy, con el histórico que ya hay.

Qué se compara, en concreto
---------------------------
Para cada lote adjudicado del bloque de evaluación, su baja real contra:

- ``agregado``: el p50 del modelo agregado para **su expediente** — lo que la
  vista de un lote sirve hoy (``prediccion_ambito='expediente'``);
- ``lote``: el p50 del modelo por lote para **ese lote**.

Mismo corte, mismos hiperparámetros fijos (``_HIPER_BASE``: la búsqueda de
hiperparámetros daría a cada modelo una ventaja distinta según su rejilla) y
mismo peso por recencia. Solo entran lotes cuyo expediente tiene fila en el
dataset agregado de evaluación: un par sin las dos predicciones no compara
nada.

Por qué además del delta hay un error estándar
----------------------------------------------
Es la lección de S6.4 (``services.ml.promotion``): v2 del modelo agregado
«mejoraba un 3,3 %» con una mejora absoluta dos veces y media menor que su
propio ruido. Aquí los errores son **pareados** (mismo lote, dos
predicciones), así que el ruido relevante es el de la diferencia por par:
``recomendacion='candidato_a_sustituir'`` exige que el delta supere dos errores
estándar, no solo que sea negativo.

Este módulo **no decide ni cambia nada**: no activa versiones, no escribe en
``predicciones_baja`` y no toca ``ML_BAJA_POR_LOTE``. Solo produce el número.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from observability.logging import get_logger
from services.ml.features import CATEGORICAL_COLUMNS, FEATURE_COLUMNS, FilaDataset, _fecha_dt

log = get_logger(__name__)

#: Umbral de la recomendación: el delta tiene que superar este múltiplo del
#: error estándar de la diferencia pareada.
Z_MINIMO = 2.0
#: Mínimo de pares evaluados para emitir una recomendación.
MIN_PARES = 30


def _ajustar_p50(
    train: list[FilaDataset], halflife: float
) -> Callable[[list[FilaDataset]], list[float]]:
    """Ajusta un único regresor cuantílico p50 con los hiperparámetros base.

    Devuelve un predictor ``filas -> list[float]``. Reutiliza la codificación,
    el descarte de columnas sin cobertura y el peso por recencia de
    ``services.ml.baja_model``: el backtest tiene que medir el mismo modelo que
    ``entrenar`` produciría, no una variante escrita aparte.
    """
    import numpy as np

    from services.ml.baja_model import (
        _BAJA_MAX,
        _HIPER_BASE,
        _aplicar_mascara,
        _codificar,
        _columnas_observadas,
        _filtrar,
        _fit_quantil,
        _pesos_recencia,
        _y_de,
    )

    X_completa, categorias = _codificar(train)
    mascara, _ = _columnas_observadas(X_completa)
    cat_mask = _filtrar([c in CATEGORICAL_COLUMNS for c in FEATURE_COLUMNS], mascara)
    modelo = _fit_quantil(
        0.50,
        _aplicar_mascara(X_completa, mascara),
        _y_de(train),
        _pesos_recencia(train, halflife),
        cat_mask,
        dict(_HIPER_BASE),
    )

    def predecir(filas: list[FilaDataset]) -> list[float]:
        if not filas:
            return []
        X, _ = _codificar(filas, categorias)
        crudo = modelo.predict(_aplicar_mascara(X, mascara))
        return [float(v) for v in np.clip(crudo, 0.0, _BAJA_MAX)]

    return predecir


def comparar_sobre_pares(
    *,
    train_expediente: list[FilaDataset],
    train_lote: list[FilaDataset],
    eval_expediente: list[FilaDataset],
    eval_lote: list[FilaDataset],
    halflife: float = 18.0,
) -> dict[str, Any]:
    """Entrena los dos modelos y los evalúa sobre los mismos lotes.

    Separado de :func:`backtest_mae_p50_por_lote` para poder probarlo sin BD:
    recibe los cuatro bloques ya cortados.
    """
    from services.ml.baja_model import MIN_TRAIN_SAMPLES

    if len(train_expediente) < MIN_TRAIN_SAMPLES or len(train_lote) < MIN_TRAIN_SAMPLES:
        return {
            "status": "datos_insuficientes",
            "n_train_expediente": len(train_expediente),
            "n_train_lote": len(train_lote),
            "min_train": MIN_TRAIN_SAMPLES,
        }

    predecir_exp = _ajustar_p50(train_expediente, halflife)
    predecir_lote = _ajustar_p50(train_lote, halflife)

    p50_expediente = dict(
        zip(
            (f.licitacion_id for f in eval_expediente),
            predecir_exp(eval_expediente),
            strict=True,
        )
    )
    evaluables = [f for f in eval_lote if f.licitacion_id in p50_expediente]
    p50_lote = predecir_lote(evaluables)

    todos = _metricas(
        [
            (float(f.baja or 0.0), p50_expediente[f.licitacion_id], p)
            for f, p in zip(evaluables, p50_lote, strict=True)
        ]
    )
    # El subconjunto donde las dos granularidades pueden diferir de verdad:
    # en un expediente de lote único el lote ES el expediente.
    multilote = _metricas(
        [
            (float(f.baja or 0.0), p50_expediente[f.licitacion_id], p)
            for f, p in zip(evaluables, p50_lote, strict=True)
            if f.lote_numero is not None
        ]
    )
    return {
        "status": "ok",
        "n_train_expediente": len(train_expediente),
        "n_train_lote": len(train_lote),
        "n_eval_lote": len(eval_lote),
        "n_eval_sin_agregado": len(eval_lote) - len(evaluables),
        "todos": todos,
        "solo_multilote": multilote,
        # La recomendación se decide sobre todos los pares: es la población
        # que el cambio de granularidad afectaría.
        "recomendacion": todos["recomendacion"],
    }


def _metricas(pares: list[tuple[float, float, float]]) -> dict[str, Any]:
    """MAE de cada modelo y el delta pareado con su error estándar.

    ``pares`` son ``(baja_real, p50_agregado, p50_lote)``. ``delta_mae_p50`` es
    ``lote - agregado``: negativo significa que el modelo por lote se equivoca
    menos, mismo signo que ``calibration.comparar_mae_p50``.
    """
    n = len(pares)
    if n == 0:
        return {
            "n": 0,
            "mae_p50_agregado": None,
            "mae_p50_lote": None,
            "delta_mae_p50": None,
            "error_estandar_delta": None,
            "recomendacion": "sin_datos_suficientes",
        }
    err_agregado = [abs(real - agregado) for real, agregado, _ in pares]
    err_lote = [abs(real - lote) for real, _, lote in pares]
    diferencias = [lo - ag for lo, ag in zip(err_lote, err_agregado, strict=True)]
    delta = sum(diferencias) / n
    varianza = sum((d - delta) ** 2 for d in diferencias) / (n - 1) if n > 1 else 0.0
    error_estandar = math.sqrt(varianza / n)

    if n < MIN_PARES:
        recomendacion = "sin_datos_suficientes"
    elif delta < 0 and -delta > Z_MINIMO * error_estandar:
        recomendacion = "candidato_a_sustituir"
    else:
        recomendacion = "mantener_agregado"
    return {
        "n": n,
        "mae_p50_agregado": round(sum(err_agregado) / n, 5),
        "mae_p50_lote": round(sum(err_lote) / n, 5),
        "delta_mae_p50": round(delta, 5),
        "error_estandar_delta": round(error_estandar, 5),
        "recomendacion": recomendacion,
    }


def backtest_mae_p50_por_lote(*, hasta: str | None = None, valid_meses: int = 6) -> dict[str, Any]:
    """Corte temporal único: entrena con lo adjudicado antes, evalúa lo publicado después.

    El corte es ``valid_meses`` antes de la última publicación del dataset por
    lote. Entrenan las filas cuya **etiqueta** ya era observable en el corte
    (adjudicadas antes, el mismo criterio asimétrico que ``_folds_rolling``) y
    se evalúan las **publicadas** después: ninguna fila de evaluación puede
    haber alimentado un ajuste.
    """
    from config import settings
    from services.ml.baja_model import (
        _fecha_label,
        _fechas_adjudicacion,
        filtrar_fechas_invalidas,
        sanear_fechas_label,
    )
    from services.ml.features import construir_dataset_baja

    def _preparar(filas: list[FilaDataset]) -> list[FilaDataset]:
        validas, _ = filtrar_fechas_invalidas(filas)
        # Mismo filtro que `entrenar`: una baja negativa no se puede predecir.
        return [f for f in validas if (f.baja or 0.0) >= 0.0]

    expediente = _preparar(construir_dataset_baja(hasta=hasta)[0])
    lote = _preparar(construir_dataset_baja(hasta=hasta, por_lote=True)[0])
    if not expediente or not lote:
        return {"status": "sin_datos", "n_expediente": len(expediente), "n_lote": len(lote)}

    fechas_exp, _ = sanear_fechas_label(_fechas_adjudicacion(hasta))
    fechas_lote, _ = sanear_fechas_label(_fechas_adjudicacion(hasta, por_lote=True))
    corte = max(_fecha_dt(f.fecha) for f in lote) - timedelta(days=valid_meses * 30)

    halflife = float(getattr(settings, "ML_BAJA_HALFLIFE_MESES", 18.0))
    resultado = comparar_sobre_pares(
        train_expediente=[f for f in expediente if _fecha_label(f, fechas_exp) < corte],
        train_lote=[f for f in lote if _fecha_label(f, fechas_lote) < corte],
        eval_expediente=[f for f in expediente if _fecha_dt(f.fecha) >= corte],
        eval_lote=[f for f in lote if _fecha_dt(f.fecha) >= corte],
        halflife=halflife,
    )
    resultado["corte"] = corte.date().isoformat()
    resultado["valid_meses"] = valid_meses
    log.info(
        "ml_baja_backtest_granularidad",
        status=resultado.get("status"),
        corte=resultado["corte"],
        recomendacion=resultado.get("recomendacion"),
        n=(resultado.get("todos") or {}).get("n"),
        delta_mae_p50=(resultado.get("todos") or {}).get("delta_mae_p50"),
    )
    return resultado
