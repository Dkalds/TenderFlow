"""Calibración de probabilidades y tuning de umbral (F3).

Combina :class:`sklearn.calibration.CalibratedClassifierCV` con búsqueda
exhaustiva de umbral óptimo para una métrica **F-beta** sensible al coste:

    F_beta = (1 + β²) · P · R / (β² · P + R)

Con ``beta = sqrt(cost_FN / cost_FP)``: si los falsos negativos cuestan
más que los falsos positivos (típico en alertas SAP — perder una licitación
es peor que revisar una falsa), ``beta > 1`` y el threshold óptimo se
desplaza hacia mayor recall.

Uso típico::

    from services.threshold_tuning import calibrate_and_tune

    result = calibrate_and_tune(
        base_estimator=clf,
        X_train=X_tr, y_train=y_tr,
        X_val=X_v, y_val=y_v,
        cost_fp=1.0, cost_fn=5.0,
    )
    # result.threshold → umbral óptimo
    # result.calibrated → modelo calibrado (sigmoid/isotonic)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sklearn.base import BaseEstimator
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import fbeta_score, precision_recall_curve

from observability.logging import get_logger

log = get_logger(__name__)


@dataclass
class ThresholdTuningResult:
    """Resultado de la calibración + búsqueda de umbral."""

    calibrated: BaseEstimator
    threshold: float
    beta: float
    fbeta: float
    precision: float
    recall: float
    method: str = "sigmoid"
    grid: dict[str, list[float]] = field(default_factory=dict)


def calibrate_and_tune(
    *,
    base_estimator: BaseEstimator,
    X_train: Any,
    y_train: Any,
    X_val: Any,
    y_val: Any,
    cost_fp: float = 1.0,
    cost_fn: float = 1.0,
    cv: int = 5,
    method: str = "sigmoid",
    threshold_step: float = 0.005,
) -> ThresholdTuningResult:
    """Calibra el estimador y busca el umbral que maximiza F-beta sensible a coste.

    .. note:: Double calibration avoided

        ``SAPClassifier`` builds its base pipeline **without** an internal
        ``CalibratedClassifierCV`` when ``ML_USE_CALIBRATION=True`` (see
        ``SAPClassifier.__init__``), so this function applies the single
        calibration layer. When calling it on other pipelines, ensure the
        upstream estimator is **not** already calibrated, otherwise a second
        layer degrades probability estimates (oversmoothing, loss of sharpness).

    Args:
        base_estimator: Clasificador ``fit/predict_proba`` ya entrenado.
        X_train, y_train: Datos para la calibración (cv-fold interno).
        X_val, y_val: Conjunto de validación independiente para el tuning.
        cost_fp: Coste de un falso positivo (alertar de una licitación no-SAP).
        cost_fn: Coste de un falso negativo (perder una licitación SAP real).
        cv: Folds para CalibratedClassifierCV.
        method: ``"sigmoid"`` (Platt) o ``"isotonic"``.
        threshold_step: Resolución de la búsqueda en (0, 1).
    """
    if cost_fp <= 0 or cost_fn <= 0:
        raise ValueError("cost_fp y cost_fn deben ser positivos")

    beta = float(np.sqrt(cost_fn / cost_fp))

    calibrated = CalibratedClassifierCV(base_estimator, method=method, cv=cv)
    calibrated.fit(X_train, y_train)

    probas = calibrated.predict_proba(X_val)[:, 1]
    _precision, _recall, raw_thresholds = precision_recall_curve(y_val, probas)

    # precision_recall_curve devuelve len(thresholds) == len(precision) - 1
    # (concatenación preservada por si se necesita en el futuro)
    _ = np.concatenate([raw_thresholds, [1.0]])

    # Búsqueda explícita sobre malla para asegurar paso constante
    grid_t = np.arange(threshold_step, 1.0, threshold_step)
    grid_f: list[float] = []
    grid_p: list[float] = []
    grid_r: list[float] = []
    for t in grid_t:
        preds = (probas >= t).astype(int)
        f = float(fbeta_score(y_val, preds, beta=beta, zero_division=0))
        grid_f.append(f)
        # P/R simples para registro
        tp = int(((preds == 1) & (y_val == 1)).sum())
        fp = int(((preds == 1) & (y_val == 0)).sum())
        fn = int(((preds == 0) & (y_val == 1)).sum())
        grid_p.append(tp / (tp + fp) if (tp + fp) else 0.0)
        grid_r.append(tp / (tp + fn) if (tp + fn) else 0.0)

    best_idx = int(np.argmax(grid_f))
    best_t = float(grid_t[best_idx])

    log.info(
        "threshold_tuned",
        beta=round(beta, 3),
        threshold=round(best_t, 4),
        fbeta=round(grid_f[best_idx], 4),
        method=method,
        n_val=len(y_val),
    )

    return ThresholdTuningResult(
        calibrated=calibrated,
        threshold=best_t,
        beta=beta,
        fbeta=float(grid_f[best_idx]),
        precision=float(grid_p[best_idx]),
        recall=float(grid_r[best_idx]),
        method=method,
        grid={
            "threshold": grid_t.tolist(),
            "fbeta": grid_f,
            "precision": grid_p,
            "recall": grid_r,
        },
    )


__all__ = ["ThresholdTuningResult", "calibrate_and_tune"]
