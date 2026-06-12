"""Modelo de baja ganadora — regresión cuantílica p10/p50/p90 (Fase 6.1).

Tres ``HistGradientBoostingRegressor`` con pérdida cuantílica: la predicción
de negocio es un **intervalo** ("baja esperada 12-18%, mediana 15%"), no un
punto — un punto sin incertidumbre invita a sobreconfianza en pujas.

Validación con split temporal estricto (entrena hasta T, valida los últimos
``valid_meses``). Baseline a batir: la media histórica del segmento
(``baja_media_organo_cpv4`` → ``baja_media_cpv4`` → ``baja_media_organo`` →
media global del train), que es exactamente lo que hoy sirve
``baja_de_referencia``. **Criterio de honestidad del RFC**: si el MAE(p50)
no mejora el baseline ≥10% relativo, la versión se registra pero NO se
activa, y el serving sigue siendo el baseline.

Registro en ``model_versions`` (name="baja_model") con métricas completas;
activación manual vía ``db.model_registry.activate_version`` o automática si
``ML_PRED_AUTO_ACTIVATE=true`` y se cumplen los criterios.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from observability.logging import get_logger
from services.ml.features import (
    CATEGORICAL_COLUMNS,
    FEATURE_COLUMNS,
    FilaDataset,
    _fecha_dt,
    construir_dataset_baja,
)

if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt

log = get_logger(__name__)

MODEL_NAME = "baja_model"
QUANTILES = (0.10, 0.50, 0.90)
MIN_TRAIN_SAMPLES = 200
_MODEL_PATH = Path(__file__).parents[2] / "data" / "models" / "baja_model.pkl"
# Tope físico del target: una baja real vive en [0, 1); el clip evita que
# outliers residuales empujen predicciones absurdas.
_BAJA_MAX = 0.95
# Criterios de activación (acceptance del RFC).
MEJORA_MINIMA_RELATIVA = 0.10
COBERTURA_OBJETIVO = (0.75, 0.85)

_BASELINE_FALLBACK = ("baja_media_organo_cpv4", "baja_media_cpv4", "baja_media_organo")


@dataclass
class Prediccion:
    licitacion_id: str
    p10: float
    p50: float
    p90: float


def _codificar(
    filas: list[FilaDataset], categorias: dict[str, dict[str, int]] | None = None
) -> tuple[npt.NDArray[np.float64], dict[str, dict[str, int]]]:
    """Matriz numérica: categóricas por ordinal aprendido en train (-1 = unseen)."""
    import numpy as np

    aprender = categorias is None
    cats: dict[str, dict[str, int]] = categorias if categorias is not None else {}
    if aprender:
        for col in CATEGORICAL_COLUMNS:
            valores = sorted({str(f.features[col]) for f in filas})
            cats[col] = {v: i for i, v in enumerate(valores)}

    X = np.full((len(filas), len(FEATURE_COLUMNS)), np.nan, dtype=np.float64)
    for i, fila in enumerate(filas):
        for j, col in enumerate(FEATURE_COLUMNS):
            valor = fila.features.get(col)
            if col in CATEGORICAL_COLUMNS:
                X[i, j] = float(cats[col].get(str(valor), -1))
            elif valor is not None:
                X[i, j] = float(valor)
    return X, cats


def _baseline(fila: FilaDataset, media_global: float) -> float:
    for col in _BASELINE_FALLBACK:
        valor = fila.features.get(col)
        if valor is not None:
            return float(valor)
    return media_global


class BajaModel:
    """Tres regresores cuantílicos + codificación de categóricas + metadata."""

    def __init__(
        self,
        modelos: dict[float, Any],
        categorias: dict[str, dict[str, int]],
        metadata: dict[str, Any],
    ) -> None:
        self.modelos = modelos
        self.categorias = categorias
        self.metadata = metadata

    def predict(self, filas: list[FilaDataset]) -> list[Prediccion]:
        if not filas:
            return []
        X, _ = _codificar(filas, self.categorias)
        por_quantil = {q: self.modelos[q].predict(X) for q in QUANTILES}
        out: list[Prediccion] = []
        for i, fila in enumerate(filas):
            # Monotonicidad: los tres fits son independientes y pueden cruzarse.
            p10, p50, p90 = sorted(
                min(max(float(por_quantil[q][i]), 0.0), _BAJA_MAX) for q in QUANTILES
            )
            out.append(Prediccion(licitacion_id=fila.licitacion_id, p10=p10, p50=p50, p90=p90))
        return out

    def save(self, path: Path | None = None) -> Path:
        import joblib

        target = path or _MODEL_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, target, compress=3)
        return target

    @classmethod
    def load(cls, path: Path | None = None) -> BajaModel:
        import joblib

        target = path or _MODEL_PATH
        if not target.exists():
            raise FileNotFoundError(f"No existe el modelo en {target}")
        obj = joblib.load(target)
        if not isinstance(obj, cls):
            raise TypeError(f"El archivo {target} no contiene un BajaModel")
        return obj


def _split_temporal(
    filas: list[FilaDataset], valid_meses: int
) -> tuple[list[FilaDataset], list[FilaDataset]]:
    """Entrena hasta T, valida T..T+valid_meses (las filas llegan ordenadas)."""
    corte = _fecha_dt(filas[-1].fecha) - timedelta(days=valid_meses * 30)
    train = [f for f in filas if _fecha_dt(f.fecha) < corte]
    valid = [f for f in filas if _fecha_dt(f.fecha) >= corte]
    if len(train) < MIN_TRAIN_SAMPLES // 2 or len(valid) < 30:
        # Histórico corto: split temporal 80/20 manteniendo el orden.
        k = int(len(filas) * 0.8)
        train, valid = filas[:k], filas[k:]
    return train, valid


def entrenar(
    *,
    hasta: str | None = None,
    valid_meses: int = 6,
    activar: bool | None = None,
    model_path: Path | None = None,
) -> dict[str, Any]:
    """Entrena p10/p50/p90, valida contra el baseline y registra la versión.

    ``activar=None`` aplica la política del RFC: solo activa si
    ``ML_PRED_AUTO_ACTIVE`` está encendido Y el modelo bate el baseline ≥10%
    relativo en MAE Y la cobertura del intervalo 80% nominal cae en [75, 85]%.
    Devuelve el resumen con métricas (clave ``activado``).
    """
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.metrics import mean_absolute_error, mean_pinball_loss

    filas, _ = construir_dataset_baja(hasta=hasta)
    if len(filas) < MIN_TRAIN_SAMPLES:
        log.warning("baja_model_insufficient_data", n=len(filas), min=MIN_TRAIN_SAMPLES)
        return {"status": "datos_insuficientes", "n": len(filas)}

    train, valid = _split_temporal(filas, valid_meses)
    X_train, categorias = _codificar(train)
    X_valid, _ = _codificar(valid, categorias)
    y_train = np.array([min(float(f.baja or 0.0), _BAJA_MAX) for f in train])
    y_valid = np.array([min(float(f.baja or 0.0), _BAJA_MAX) for f in valid])
    cat_mask = [col in CATEGORICAL_COLUMNS for col in FEATURE_COLUMNS]

    modelos: dict[float, Any] = {}
    for q in QUANTILES:
        est = HistGradientBoostingRegressor(
            loss="quantile",
            quantile=q,
            max_iter=300,
            learning_rate=0.06,
            max_depth=6,
            min_samples_leaf=30,
            categorical_features=cat_mask,
            random_state=42,
        )
        est.fit(X_train, y_train)
        modelos[q] = est

    pred = {q: np.clip(modelos[q].predict(X_valid), 0.0, _BAJA_MAX) for q in QUANTILES}
    p10 = np.minimum(pred[0.10], np.minimum(pred[0.50], pred[0.90]))
    p90 = np.maximum(pred[0.90], np.maximum(pred[0.50], pred[0.10]))

    media_global = float(y_train.mean())
    baseline_pred = np.array([_baseline(f, media_global) for f in valid])

    mae_p50 = float(mean_absolute_error(y_valid, pred[0.50]))
    mae_baseline = float(mean_absolute_error(y_valid, baseline_pred))
    mejora = 1.0 - mae_p50 / mae_baseline if mae_baseline > 0 else 0.0
    cobertura = float(np.mean((y_valid >= p10) & (y_valid <= p90)))
    metricas = {
        "mae_p50": round(mae_p50, 5),
        "mae_baseline": round(mae_baseline, 5),
        "mejora_relativa": round(mejora, 4),
        "pinball_p10": round(float(mean_pinball_loss(y_valid, pred[0.10], alpha=0.10)), 5),
        "pinball_p90": round(float(mean_pinball_loss(y_valid, pred[0.90], alpha=0.90)), 5),
        "cobertura_intervalo_80": round(cobertura, 4),
        "n_train": len(train),
        "n_valid": len(valid),
        "valid_desde": valid[0].fecha,
        "valid_hasta": valid[-1].fecha,
    }

    cumple = (
        mejora >= MEJORA_MINIMA_RELATIVA
        and COBERTURA_OBJETIVO[0] <= cobertura <= COBERTURA_OBJETIVO[1]
    )
    if activar is None:
        from config import settings

        activar = bool(getattr(settings, "ML_PRED_AUTO_ACTIVATE", False)) and cumple

    modelo = BajaModel(
        modelos,
        categorias,
        metadata={"feature_columns": list(FEATURE_COLUMNS), "metrics": metricas},
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
        notes="cumple criterios RFC 20260611-2" if cumple else "NO bate baseline — no activar",
    )
    log.info(
        "baja_model_trained",
        version=version,
        activado=bool(activar),
        cumple_criterios=cumple,
        **{k: v for k, v in metricas.items() if isinstance(v, int | float)},
    )
    return {
        "status": "ok",
        "version": version,
        "activado": bool(activar),
        "cumple_criterios": cumple,
        "path": str(path),
        **metricas,
    }


def predecir_baseline(filas: list[FilaDataset], media_global: float = 0.12) -> list[Prediccion]:
    """Serving honesto cuando no hay modelo activo: la media del segmento como
    p50 y un intervalo fijo ±40% relativo (heurística documentada)."""
    out: list[Prediccion] = []
    for fila in filas:
        p50 = min(max(_baseline(fila, media_global), 0.0), _BAJA_MAX)
        ancho = p50 * 0.4
        out.append(
            Prediccion(
                licitacion_id=fila.licitacion_id,
                p10=max(p50 - ancho, 0.0),
                p50=p50,
                p90=min(p50 + ancho, _BAJA_MAX),
            )
        )
    return out
