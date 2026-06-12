"""Modelo de retención de renovaciones (Fase 6.2 v1, RFC 20260611-2).

``HistGradientBoostingClassifier`` + calibración isotónica (patrón
``ml_classifier``) sobre los pares etiquetados de ``retencion_labels``.
Output de negocio: "riesgo de cambio de manos" (= 1 - P(retención)) en la
vista Renovaciones.

Métricas de validación temporal: PR-AUC, Brier score y ECE. Criterios de
activación del RFC: PR-AUC > prevalencia + 0.15 absoluto y ECE < 0.08.
Como en el modelo de baja, la versión se registra siempre y la activación
es manual salvo ``ML_PRED_AUTO_ACTIVATE`` con criterios cumplidos.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from observability.logging import get_logger
from services.ml.retencion_labels import FEATURE_COLUMNS_RETENCION, ParRetencion

if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt

log = get_logger(__name__)

MODEL_NAME = "retencion_model"
MIN_TRAIN_SAMPLES = 150
_MODEL_PATH = Path(__file__).parents[2] / "data" / "models" / "retencion_model.pkl"
PR_AUC_MARGEN = 0.15
ECE_MAX = 0.08


def _matriz(pares: list[ParRetencion]) -> npt.NDArray[np.float64]:
    import numpy as np

    X = np.full((len(pares), len(FEATURE_COLUMNS_RETENCION)), np.nan, dtype=np.float64)
    for i, par in enumerate(pares):
        for j, col in enumerate(FEATURE_COLUMNS_RETENCION):
            valor = par.features.get(col)
            if valor is not None:
                X[i, j] = float(valor)
    return X


def _ece(y_true: npt.NDArray[np.float64], y_prob: npt.NDArray[np.float64], bins: int = 10) -> float:
    """Expected Calibration Error con bins equiespaciados."""

    total = len(y_true)
    if total == 0:
        return 0.0
    ece = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        mask = (y_prob >= lo) & (y_prob < hi if b < bins - 1 else y_prob <= hi)
        if not mask.any():
            continue
        ece += abs(float(y_prob[mask].mean()) - float(y_true[mask].mean())) * (
            mask.sum() / total
        )
    return ece


class RetencionModel:
    """Clasificador calibrado + metadata."""

    def __init__(self, clf: Any, metadata: dict[str, Any]) -> None:
        self.clf = clf
        self.metadata = metadata

    def predict_proba_retencion(self, pares: list[ParRetencion]) -> list[float]:
        if not pares:
            return []
        proba = self.clf.predict_proba(_matriz(pares))[:, 1]
        return [float(p) for p in proba]

    def save(self, path: Path | None = None) -> Path:
        import joblib

        target = path or _MODEL_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, target, compress=3)
        return target

    @classmethod
    def load(cls, path: Path | None = None) -> RetencionModel:
        import joblib

        target = path or _MODEL_PATH
        if not target.exists():
            raise FileNotFoundError(f"No existe el modelo en {target}")
        obj = joblib.load(target)
        if not isinstance(obj, cls):
            raise TypeError(f"El archivo {target} no contiene un RetencionModel")
        return obj


def entrenar(
    *,
    valid_fraccion: float = 0.2,
    activar: bool | None = None,
    model_path: Path | None = None,
) -> dict[str, Any]:
    """Entrena, valida temporalmente (último 20% por fecha de sucesor) y registra."""
    import numpy as np
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import average_precision_score, brier_score_loss

    from services.ml.retencion_labels import construir_pares

    pares = construir_pares()
    if len(pares) < MIN_TRAIN_SAMPLES:
        log.warning("retencion_model_insufficient_data", n=len(pares), min=MIN_TRAIN_SAMPLES)
        return {"status": "datos_insuficientes", "n": len(pares)}

    k = int(len(pares) * (1 - valid_fraccion))
    train, valid = pares[:k], pares[k:]  # construir_pares ya ordena por fecha_sucesor
    y_train = np.array([p.label for p in train])
    y_valid = np.array([float(p.label) for p in valid])
    if len(set(y_train.tolist())) < 2 or len(valid) < 20:
        return {"status": "datos_insuficientes", "n": len(pares)}

    base = HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.06, max_depth=6, min_samples_leaf=20, random_state=42
    )
    clf = CalibratedClassifierCV(base, method="isotonic", cv=3)
    clf.fit(_matriz(train), y_train)

    proba = clf.predict_proba(_matriz(valid))[:, 1]
    prevalencia = float(y_valid.mean())
    pr_auc = float(average_precision_score(y_valid, proba))
    ece = _ece(y_valid, proba)
    metricas: dict[str, Any] = {
        "pr_auc": round(pr_auc, 4),
        "prevalencia": round(prevalencia, 4),
        "brier": round(float(brier_score_loss(y_valid, proba)), 5),
        "ece": round(ece, 5),
        "n_train": len(train),
        "n_valid": len(valid),
        "valid_desde": valid[0].fecha_sucesor,
        "valid_hasta": valid[-1].fecha_sucesor,
    }
    cumple = pr_auc > prevalencia + PR_AUC_MARGEN and ece < ECE_MAX
    if activar is None:
        from config import settings

        activar = bool(getattr(settings, "ML_PRED_AUTO_ACTIVATE", False)) and cumple

    modelo = RetencionModel(
        clf, metadata={"feature_columns": list(FEATURE_COLUMNS_RETENCION), "metrics": metricas}
    )
    path = modelo.save(model_path)
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    from db.model_registry import register_version

    version = register_version(
        name=MODEL_NAME,
        path=str(path),
        sha256=sha256,
        metrics=metricas,
        n_samples=len(train),
        activate=bool(activar),
        notes="cumple criterios RFC 20260611-2" if cumple else "NO cumple criterios — no activar",
    )
    log.info("retencion_model_trained", version=version, activado=bool(activar), **metricas)
    return {
        "status": "ok",
        "version": version,
        "activado": bool(activar),
        "cumple_criterios": cumple,
        "path": str(path),
        **metricas,
    }
