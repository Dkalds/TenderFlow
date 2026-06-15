"""Jobs de modelos predictivos (Fase 6, RFC 20260611-2).

- ``run_scoring``: batch nocturno que materializa ``predicciones_baja`` para
  licitaciones abiertas (serving = lectura de tabla, patrón ``ml_proba``).
- ``run_retrain``: re-entrenamiento mensual; registra la versión nueva en
  ``model_versions`` SIN activar (salvo ``ML_PRED_AUTO_ACTIVATE`` y criterios
  del RFC cumplidos). La activación es decisión humana vía model_registry.
"""

from __future__ import annotations

from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)


def run_scoring() -> dict[str, Any]:
    from services.ml.calibration import comprobar_calibracion_baja
    from services.ml.drift import comprobar_drift_baja
    from services.ml.scoring import score_predicciones_baja, score_predicciones_retencion

    baja = score_predicciones_baja()
    retencion = score_predicciones_retencion()
    drift = comprobar_drift_baja()
    calibracion = comprobar_calibracion_baja()
    return {"baja": baja, "retencion": retencion, "drift": drift, "calibracion": calibracion}


def run_retrain() -> dict[str, Any]:
    from services.ml.baja_model import entrenar as entrenar_baja
    from services.ml.retencion_model import entrenar as entrenar_retencion

    resultados = {"baja": entrenar_baja(), "retencion": entrenar_retencion()}
    for nombre, resumen in resultados.items():
        if resumen.get("status") == "ok" and not resumen.get("activado"):
            log.info(
                "ml_retrain_pending_activation",
                modelo=nombre,
                version=resumen.get("version"),
                cumple_criterios=resumen.get("cumple_criterios"),
            )
    return resultados
