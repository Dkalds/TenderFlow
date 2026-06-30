"""Evaluación honesta del clasificador SAP contra un golden set etiquetado a mano.

Motivación
----------
El dataset de entrenamiento deriva sus etiquetas de ``raw_keywords IS NOT NULL``
(ver :func:`scraper.ml_pipeline._build_dataset`). Por tanto, las métricas internas
calculadas sobre el test split (F1, PR-AUC) miden cuánto **imita** el modelo al
filtro de keywords, no cuánto **detecta SAP de verdad**. El valor real del ML
—pescar licitaciones SAP que las keywords pierden— solo es medible contra
etiquetas humanas independientes.

Este módulo carga un golden set JSONL etiquetado a mano y mide:

  - Métricas globales (precision/recall/F1/F-beta/accuracy) contra labels humanas.
  - **Recall en la zona de desacuerdo** (``keyword_match == False``): la métrica
    que de verdad refleja si el modelo aporta sobre el filtro de keywords. Un
    modelo que solo replica las keywords tendrá ``recall_no_keyword`` ≈ 0.

Uso típico::

    from scraper.ml_classifier import SAPClassifier
    from services.ml_eval import evaluate_classifier, load_golden_set

    clf = SAPClassifier.load()
    result = evaluate_classifier(clf)
    print(result.recall_no_keyword)  # ¿pescamos SAP sin keyword?
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from observability.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

log = get_logger(__name__)

# Raíz del repo (este archivo vive en services/).
_REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class GoldenExample:
    """Un ejemplo del golden set con etiqueta humana."""

    id: str
    titulo: str
    descripcion: str
    label: int  # 1 = SAP, 0 = no-SAP (etiqueta humana, no derivada de keywords)
    cpv: str | None = None
    importe: float | None = None
    keyword_match: bool | None = None  # ¿lo detectaría el filtro de keywords?
    note: str = ""

    @property
    def text(self) -> str:
        """Texto combinado título + descripción (sin tokens estructurales)."""
        return f"{self.titulo} {self.descripcion}".strip()


@dataclass
class GoldenEvalResult:
    """Resultado de evaluar el clasificador contra el golden set."""

    n: int
    n_positive: int
    n_negative: int
    threshold: float
    accuracy: float
    precision: float
    recall: float
    f1: float
    fbeta: float
    beta: float
    # Recall sobre el subconjunto que las keywords NO detectan (keyword_match==False)
    # y son SAP reales: mide el valor incremental del modelo sobre las keywords.
    recall_no_keyword: float
    n_no_keyword_positive: int
    n_no_keyword_caught: int
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Serializa a dict plano (para logging/registry/API)."""
        return {
            "n": self.n,
            "n_positive": self.n_positive,
            "n_negative": self.n_negative,
            "threshold": round(self.threshold, 4),
            "accuracy": round(self.accuracy, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "fbeta": round(self.fbeta, 4),
            "beta": round(self.beta, 4),
            "recall_no_keyword": round(self.recall_no_keyword, 4),
            "n_no_keyword_positive": self.n_no_keyword_positive,
            "n_no_keyword_caught": self.n_no_keyword_caught,
            **self.extra,
        }


class _ProbaClassifier(Protocol):
    """Interfaz mínima de un clasificador con probabilidad de SAP."""

    def predict(
        self, text: str, *, cpv: str | None = ..., importe: float | None = ...
    ) -> tuple[bool, float]: ...


def _default_golden_path() -> Path:
    """Resuelve la ruta del golden set desde settings (relativa al repo)."""
    from config import settings

    raw = getattr(settings, "ML_GOLDEN_SET_PATH", "tests/fixtures/golden_set.jsonl")
    p = Path(raw)
    return p if p.is_absolute() else _REPO_ROOT / p


def load_golden_set(path: str | Path | None = None) -> list[GoldenExample]:
    """Carga el golden set JSONL. Tolera líneas vacías y comentarios (``#``).

    Args:
        path: Ruta al fichero JSONL. Si es ``None``, usa ``ML_GOLDEN_SET_PATH``.

    Returns:
        Lista de :class:`GoldenExample`. Vacía si el fichero no existe.

    Raises:
        ValueError: Si una línea es JSON inválido o le faltan campos requeridos.
    """
    target = Path(path) if path is not None else _default_golden_path()
    if not target.exists():
        log.warning("ml_eval.golden_set_missing", path=str(target))
        return []

    examples: list[GoldenExample] = []
    for lineno, raw_line in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Golden set: JSON inválido en línea {lineno}: {exc}") from exc
        if "titulo" not in obj or "label" not in obj:
            raise ValueError(f"Golden set: faltan campos 'titulo'/'label' en línea {lineno}")
        importe_raw = obj.get("importe")
        examples.append(
            GoldenExample(
                id=str(obj.get("id", f"line-{lineno}")),
                titulo=str(obj.get("titulo", "")),
                descripcion=str(obj.get("descripcion", "")),
                label=int(obj["label"]),
                cpv=str(obj["cpv"]) if obj.get("cpv") is not None else None,
                importe=float(importe_raw) if importe_raw is not None else None,
                keyword_match=(
                    bool(obj["keyword_match"]) if obj.get("keyword_match") is not None else None
                ),
                note=str(obj.get("note", "")),
            )
        )
    log.info("ml_eval.golden_set_loaded", path=str(target), n=len(examples))
    return examples


def evaluate_probas(
    y_true: Sequence[int],
    y_proba: Sequence[float],
    *,
    keyword_match: Sequence[bool | None] | None = None,
    threshold: float = 0.5,
    beta: float = 1.0,
) -> GoldenEvalResult:
    """Núcleo puro de evaluación a partir de etiquetas y probabilidades.

    Separado de :func:`evaluate_classifier` para poder testearlo sin un modelo.

    Args:
        y_true: Etiquetas humanas (0/1).
        y_proba: Probabilidad P(SAP) predicha por el modelo.
        keyword_match: Por ejemplo, ``True`` si las keywords detectarían el caso.
            Usado para calcular ``recall_no_keyword``. Si ``None``, ese recall
            se reporta como 0 con 0 ejemplos.
        threshold: Umbral de decisión aplicado a ``y_proba``.
        beta: β para F-beta (β>1 favorece recall).
    """
    import numpy as np
    from sklearn.metrics import accuracy_score, fbeta_score, precision_score, recall_score

    yt = np.asarray(y_true, dtype=int)
    yp = np.asarray(y_proba, dtype=float)
    if len(yt) == 0:
        return GoldenEvalResult(
            n=0,
            n_positive=0,
            n_negative=0,
            threshold=threshold,
            accuracy=0.0,
            precision=0.0,
            recall=0.0,
            f1=0.0,
            fbeta=0.0,
            beta=beta,
            recall_no_keyword=0.0,
            n_no_keyword_positive=0,
            n_no_keyword_caught=0,
        )

    y_pred = (yp >= threshold).astype(int)
    accuracy = float(accuracy_score(yt, y_pred))
    precision = float(precision_score(yt, y_pred, zero_division=0))
    recall = float(recall_score(yt, y_pred, zero_division=0))
    f1 = float(fbeta_score(yt, y_pred, beta=1.0, zero_division=0))
    fbeta = float(fbeta_score(yt, y_pred, beta=beta, zero_division=0))

    # Recall en la zona de desacuerdo: SAP reales que las keywords NO detectan.
    n_no_kw_pos = 0
    n_no_kw_caught = 0
    if keyword_match is not None:
        for label, pred, kw in zip(yt, y_pred, keyword_match, strict=False):
            if kw is False and label == 1:
                n_no_kw_pos += 1
                if pred == 1:
                    n_no_kw_caught += 1
    recall_no_kw = (n_no_kw_caught / n_no_kw_pos) if n_no_kw_pos else 0.0

    return GoldenEvalResult(
        n=len(yt),
        n_positive=int(yt.sum()),
        n_negative=int((yt == 0).sum()),
        threshold=float(threshold),
        accuracy=accuracy,
        precision=precision,
        recall=recall,
        f1=f1,
        fbeta=fbeta,
        beta=float(beta),
        recall_no_keyword=float(recall_no_kw),
        n_no_keyword_positive=n_no_kw_pos,
        n_no_keyword_caught=n_no_kw_caught,
    )


def evaluate_classifier(
    clf: _ProbaClassifier,
    examples: list[GoldenExample] | None = None,
    *,
    threshold: float | None = None,
    beta: float | None = None,
) -> GoldenEvalResult:
    """Evalúa un clasificador entrenado contra el golden set.

    Args:
        clf: Clasificador con ``predict(text, cpv=, importe=) -> (bool, proba)``.
        examples: Golden set ya cargado. Si ``None``, se carga desde settings.
        threshold: Umbral de decisión. Si ``None``, usa ``clf._threshold`` si
            existe, o ``ML_CONFIDENCE_THRESHOLD``.
        beta: β para F-beta. Si ``None``, usa ``ML_FBETA``.

    Returns:
        :class:`GoldenEvalResult` con las métricas (incluido ``recall_no_keyword``).
    """
    from config import settings

    if examples is None:
        examples = load_golden_set()
    if not examples:
        log.warning("ml_eval.no_examples")
        return evaluate_probas([], [], threshold=threshold or 0.5, beta=beta or 1.0)

    if threshold is None:
        threshold = float(getattr(clf, "_threshold", settings.ML_CONFIDENCE_THRESHOLD))
    if beta is None:
        beta = float(getattr(settings, "ML_FBETA", 1.0))

    y_true: list[int] = []
    y_proba: list[float] = []
    kw: list[bool | None] = []
    for ex in examples:
        _is_sap, proba = clf.predict(ex.text, cpv=ex.cpv, importe=ex.importe)
        y_true.append(ex.label)
        y_proba.append(proba)
        kw.append(ex.keyword_match)

    result = evaluate_probas(
        y_true, y_proba, keyword_match=kw, threshold=threshold, beta=beta
    )
    log.info("ml_eval.evaluated", **result.as_dict())
    return result


def tune_threshold_on_golden(
    clf: _ProbaClassifier,
    examples: list[GoldenExample] | None = None,
    *,
    cost_fp: float = 1.0,
    cost_fn: float = 1.0,
    min_examples: int = 10,
    clamp: tuple[float, float] = (0.30, 0.95),
    grid_step: float = 0.01,
) -> dict[str, Any] | None:
    """Busca el threshold que maximiza F-beta sobre el golden set (labels humanas).

    El threshold por defecto del clasificador se optimiza sobre un test split
    cuyas etiquetas derivan del filtro de keywords. Este tuning lo recalcula
    sobre etiquetas **humanas** con costos reales: ``beta = sqrt(cost_fn/cost_fp)``
    (un FN —perder una licitación SAP— cuesta más que un FP).

    Args:
        clf: Clasificador con ``predict(text, cpv=, importe=) -> (bool, proba)``.
        examples: Golden set ya cargado. Si ``None``, se carga desde settings.
        cost_fp: Coste de un falso positivo (revisar una falsa alerta).
        cost_fn: Coste de un falso negativo (perder una licitación SAP real).
        min_examples: Mínimo de ejemplos para fiarse del tuning (si no, ``None``).
        clamp: Rango ``[lo, hi]`` al que se acota el threshold resultante.
        grid_step: Resolución del barrido de umbral.

    Returns:
        Dict con ``threshold`` y métricas del golden set, o ``None`` si no hay
        datos suficientes (golden set pequeño o de una sola clase).
    """
    import numpy as np
    from sklearn.metrics import fbeta_score

    if cost_fp <= 0 or cost_fn <= 0:
        raise ValueError("cost_fp y cost_fn deben ser positivos")
    if examples is None:
        examples = load_golden_set()
    if len(examples) < min_examples:
        log.info("ml_eval.golden_tuning_skipped", n=len(examples), min_required=min_examples)
        return None

    y_true = [ex.label for ex in examples]
    if len(set(y_true)) < 2:
        log.info("ml_eval.golden_tuning_single_class")
        return None

    beta = float(np.sqrt(cost_fn / cost_fp))
    probas = [float(clf.predict(ex.text, cpv=ex.cpv, importe=ex.importe)[1]) for ex in examples]
    kw = [ex.keyword_match for ex in examples]
    yt = np.asarray(y_true, dtype=int)
    yp = np.asarray(probas, dtype=float)

    lo, hi = clamp
    grid = np.arange(lo, hi + 1e-9, grid_step)
    best_t = lo
    best_f = -1.0
    for t in grid:
        preds = (yp >= t).astype(int)
        f = float(fbeta_score(yt, preds, beta=beta, zero_division=0))
        if f > best_f:
            best_f = f
            best_t = float(t)

    result = evaluate_probas(y_true, probas, keyword_match=kw, threshold=best_t, beta=beta)
    out = result.as_dict()
    out["threshold"] = round(best_t, 4)
    out["fbeta"] = round(best_f, 4)
    out["beta"] = round(beta, 4)
    out["cost_fp"] = cost_fp
    out["cost_fn"] = cost_fn
    log.info("ml_eval.golden_threshold_tuned", **out)
    return out


__all__ = [
    "GoldenEvalResult",
    "GoldenExample",
    "evaluate_classifier",
    "evaluate_probas",
    "load_golden_set",
    "tune_threshold_on_golden",
]
