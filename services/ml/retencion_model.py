"""Modelo de retención de renovaciones (Fase 6.2 v1, RFC 20260611-2).

``HistGradientBoostingClassifier`` + calibración isotónica (patrón
``ml_classifier``) sobre los pares etiquetados de ``retencion_labels``.
Output de negocio: "riesgo de cambio de manos" (= 1 - P(retención)) en la
vista Renovaciones.

Métricas de validación temporal: PR-AUC, Brier score y ECE. Criterios de
activación del RFC: PR-AUC > prevalencia + 0.15 absoluto y ECE < 0.08.
Como en el modelo de baja, la versión se registra siempre y la activación
es manual salvo ``ML_PRED_AUTO_ACTIVATE`` con criterios cumplidos.

Baseline y dispersión (S6.4)
----------------------------
v1 se registró sin **ninguna** métrica de baseline: ``pr_auc`` 0.2453 sobre
prevalencia 0.1099 y nadie podía decir si eso era bueno (backlog P2). Aquí el
baseline es explícito y es el del **ranking trivial**: el PR-AUC esperado de
ordenar al azar es la prevalencia de la clase positiva, así que un modelo con
PR-AUC igual a la prevalencia no ordena nada. Se registra como
``pr_auc_baseline``.

Y como el gate compara la mejora contra su propio error de medición, hace
falta una dispersión. El modelo no hace folds —valida sobre el último tramo
temporal— así que se mide el PR-AUC por **bloques contiguos** de esa ventana
(:func:`_pr_auc_por_bloques`): mismo papel que la desviación entre folds de
``baja_model``, calculado sobre lo que hay.
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
#: Bloques contiguos en los que se parte la ventana de validación para estimar
#: la dispersión del PR-AUC. Tres, como los folds por defecto de ``baja_model``
#: (``ML_BAJA_FOLDS``): con menos, la desviación se calcula sobre dos números;
#: con más, cada bloque se queda sin positivos y mide ruido de muestreo.
_BLOQUES_DISPERSION = 3
#: Bajo esto un bloque no da un PR-AUC interpretable (hace falta al menos un
#: positivo y un negativo, y unas cuantas filas para que no sea anecdótico).
_MIN_FILAS_BLOQUE = 20


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
        ece += abs(float(y_prob[mask].mean()) - float(y_true[mask].mean())) * (mask.sum() / total)
    return ece


def _pr_auc_por_bloques(
    y_true: npt.NDArray[np.float64],
    y_prob: npt.NDArray[np.float64],
    *,
    bloques: int = _BLOQUES_DISPERSION,
) -> tuple[float | None, list[float]]:
    """Desviación típica del PR-AUC entre bloques contiguos de validación.

    Los bloques son contiguos y **no** aleatorios porque la validación es
    temporal: partir al azar mezclaría meses y mediría una dispersión que la
    serie no tiene. Cada bloque necesita las dos clases y un mínimo de filas;
    con menos de dos bloques utilizables no hay desviación que calcular y se
    devuelve ``None`` — que el gate trata como "no se puede distinguir del
    ruido", no como cero.

    Returns:
        ``(desviacion, valores_por_bloque)``.
    """
    import numpy as np
    from sklearn.metrics import average_precision_score

    n = len(y_true)
    tamano = n // bloques
    if tamano < _MIN_FILAS_BLOQUE:
        return None, []

    valores: list[float] = []
    for i in range(bloques):
        # El último bloque se lleva el resto de la división entera.
        fin = n if i == bloques - 1 else (i + 1) * tamano
        yt = y_true[i * tamano : fin]
        yp = y_prob[i * tamano : fin]
        if len(set(yt.tolist())) < 2:
            continue
        valores.append(float(average_precision_score(yt, yp)))

    if len(valores) < 2:
        return None, valores
    return float(np.std(valores)), valores


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
        """Serializa el modelo con joblib + checksum SHA256 co-ubicado."""
        import joblib

        from shared.model_integrity import write_checksum

        target = path or _MODEL_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, target, compress=3)
        write_checksum(target)
        return target

    @classmethod
    def load(cls, path: Path | None = None) -> RetencionModel:
        """Carga un modelo serializado con joblib. Lanza FileNotFoundError si no existe.

        Verifica la integridad del fichero (pin out-of-band
        ML_RETENCION_MODEL_SHA256 y/o checksum co-ubicado .sha256) antes de
        deserializar — ver ``shared.model_integrity`` para el razonamiento
        completo: joblib.load ejecuta código arbitrario, así que un .pkl
        manipulado es RCE.
        """
        import joblib

        from config import settings
        from shared.model_integrity import verify_model_integrity

        target = path or _MODEL_PATH
        if not target.exists():
            raise FileNotFoundError(f"No existe el modelo en {target}")

        verify_model_integrity(
            target,
            pinned_sha256=str(getattr(settings, "ML_RETENCION_MODEL_SHA256", "") or ""),
            pin_setting_name="ML_RETENCION_MODEL_SHA256",
            model_label=MODEL_NAME,
            env=str(getattr(settings, "ENV", "dev")),
        )

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
    dispersion, pr_auc_bloques = _pr_auc_por_bloques(y_valid, proba)
    metricas: dict[str, Any] = {
        "pr_auc": round(pr_auc, 4),
        "prevalencia": round(prevalencia, 4),
        # Baseline explícito: el PR-AUC del ranking trivial es la prevalencia.
        # Duplica el valor a propósito — `prevalencia` describe los datos y
        # `pr_auc_baseline` describe el rival, y quien lea el registro tiene
        # que poder comparar dos números con el mismo nombre de métrica.
        "pr_auc_baseline": round(prevalencia, 4),
        "pr_auc_std_folds": round(dispersion, 5) if dispersion is not None else None,
        "pr_auc_por_bloque": [round(v, 4) for v in pr_auc_bloques],
        "brier": round(float(brier_score_loss(y_valid, proba)), 5),
        "ece": round(ece, 5),
        "n_train": len(train),
        "n_valid": len(valid),
        "valid_desde": valid[0].fecha_sucesor,
        "valid_hasta": valid[-1].fecha_sucesor,
    }

    # Gate de promoción (S6.4): los dos criterios del RFC entran como motivos
    # extra y el gate añade la comparación contra la dispersión.
    from services.ml.promotion import evaluar_promocion_predictiva

    motivos_rfc: list[str] = []
    if pr_auc <= prevalencia + PR_AUC_MARGEN:
        motivos_rfc.append(
            f"pr_auc {pr_auc:.4f} <= prevalencia {prevalencia:.4f} + {PR_AUC_MARGEN} "
            "(criterio RFC 20260611-2)"
        )
    if ece >= ECE_MAX:
        motivos_rfc.append(f"ece {ece:.5f} >= {ECE_MAX}: las probabilidades no están calibradas")

    decision = evaluar_promocion_predictiva(
        metrica=pr_auc,
        baseline=prevalencia,
        dispersion=dispersion,
        nombre_metrica="pr_auc",
        mejor_es_mayor=True,
        motivos_extra=motivos_rfc,
    )
    metricas.update(decision.as_dict())
    cumple = decision.promocionable
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
        # Mismo cambio que en `baja_model`: la nota lleva el número que decidió.
        notes=decision.promotion_reason,
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
