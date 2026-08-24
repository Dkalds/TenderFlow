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
from dataclasses import dataclass, field, replace
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
    # "tune" (elegir el umbral) | "holdout" (reportar). Vacío = sin asignar:
    # `asignar_splits` lo reparte por hash del id. El default NO puede ser una
    # de las dos mitades, o los ejemplos construidos en código se irían todos
    # al mismo lado y el reparto por hash nunca llegaría a ejecutarse.
    split: str = ""

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
                split=str(obj.get("split") or ""),
            )
        )
    examples = asignar_splits(examples)
    n_tune = sum(1 for e in examples if e.split == SPLIT_TUNE)
    log.info(
        "ml_eval.golden_set_loaded",
        path=str(target),
        n=len(examples),
        n_tune=n_tune,
        n_holdout=len(examples) - n_tune,
    )
    return examples


SPLIT_TUNE = "tune"
SPLIT_HOLDOUT = "holdout"
# Mínimos por debajo de los cuales una mitad del golden set no sostiene lo que
# se le pide. Medido sobre el golden actual (27 ejemplos, 6 positivos sin
# keyword): el umbral elegido tiene sigma=0.084 y p5-p95 = [0.30, 0.56], y el
# F-beta reportado sobre el mismo conjunto donde se eligió sobreestima el real
# en +0.08 de media (+0.25 en el p90).
MIN_TUNE_EXAMPLES = 60
MIN_HOLDOUT_EXAMPLES = 60


def asignar_splits(examples: list[GoldenExample]) -> list[GoldenExample]:
    """Reparte el golden set en "tune" y "holdout" de forma **estable**.

    El umbral operativo no puede elegirse y reportarse sobre el mismo
    conjunto. Los ejemplos que traen ``split`` explícito en el JSONL lo
    conservan; el resto se asigna por hash del ``id``, de modo que:

      - la asignación es determinista y no cambia entre ejecuciones,
      - añadir ejemplos nuevos **no** reasigna los existentes,
      - ~50% cae en cada mitad.
    """
    import hashlib

    asignados: list[GoldenExample] = []
    for ex in examples:
        if ex.split in (SPLIT_TUNE, SPLIT_HOLDOUT):
            asignados.append(ex)
            continue
        digest = hashlib.sha256(ex.id.encode("utf-8")).digest()
        destino = SPLIT_TUNE if digest[0] % 2 == 0 else SPLIT_HOLDOUT
        asignados.append(replace(ex, split=destino))
    return asignados


def filtrar_split(examples: list[GoldenExample], split: str) -> list[GoldenExample]:
    """Devuelve los ejemplos de una mitad del golden set."""
    return [e for e in examples if e.split == split]


def metricas_operativas(
    y_true: Sequence[int],
    y_proba: Sequence[float],
    *,
    cost_fp: float = 1.0,
    cost_fn: float = 1.0,
    ks: tuple[int, ...] = (10, 25, 50),
    precisiones_objetivo: tuple[float, ...] = (0.80, 0.90),
) -> dict[str, Any]:
    """Métricas del problema tal y como se usa, no del clasificador en abstracto.

    Un analista revisa una cola ordenada por probabilidad y perder una
    licitación SAP cuesta más que revisar una falsa. Eso no lo captura ni el
    F1 ni el PR-AUC:

      - ``precision_at_k``: de las k mejor puntuadas, cuántas son relevantes.
        Es lo que ve quien abre la cola.
      - ``recall_at_precision_X``: cuánto recall se puede exigir sin bajar la
        precisión de X. Responde a "¿cuánto podemos pescar sin ahogar al que
        revisa?".
      - ``coste_esperado_min`` y su umbral: el coste total mínimo alcanzable
        con ``ML_COST_FN``/``ML_COST_FP``, y dónde está. Es la única cifra
        comparable entre dos modelos cuando los errores no cuestan igual.
    """
    import numpy as np

    yt = np.asarray(y_true, dtype=int)
    yp = np.asarray(y_proba, dtype=float)
    out: dict[str, Any] = {}
    if len(yt) == 0:
        return out

    orden = np.argsort(-yp)
    yt_ord = yt[orden]
    total_pos = int(yt.sum())
    for k in ks:
        if k <= len(yt_ord):
            out[f"precision_at_{k}"] = round(float(yt_ord[:k].sum()) / k, 4)

    # recall alcanzable sin bajar de cada precisión objetivo
    umbrales = np.unique(yp)
    for objetivo in precisiones_objetivo:
        mejor_recall = 0.0
        for t in umbrales:
            pred = (yp >= t).astype(int)
            tp = int(((pred == 1) & (yt == 1)).sum())
            fp = int(((pred == 1) & (yt == 0)).sum())
            if tp + fp == 0:
                continue
            prec = tp / (tp + fp)
            if prec >= objetivo and total_pos:
                mejor_recall = max(mejor_recall, tp / total_pos)
        out[f"recall_at_precision_{int(objetivo * 100)}"] = round(mejor_recall, 4)

    # coste esperado mínimo y umbral que lo alcanza
    mejor_coste = float("inf")
    mejor_t = 0.5
    for t in umbrales:
        pred = (yp >= t).astype(int)
        fp = int(((pred == 1) & (yt == 0)).sum())
        fn = int(((pred == 0) & (yt == 1)).sum())
        coste = fp * cost_fp + fn * cost_fn
        if coste < mejor_coste:
            mejor_coste = coste
            mejor_t = float(t)
    if mejor_coste < float("inf"):
        out["coste_esperado_min"] = round(mejor_coste / len(yt), 4)
        out["coste_esperado_min_threshold"] = round(mejor_t, 4)
    return out


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
    split: str | None = SPLIT_HOLDOUT,
) -> GoldenEvalResult:
    """Evalúa un clasificador entrenado contra el golden set.

    Args:
        clf: Clasificador con ``predict(text, cpv=, importe=) -> (bool, proba)``.
        examples: Golden set ya cargado. Si ``None``, se carga desde settings.
        threshold: Umbral de decisión. Si ``None``, usa ``clf._threshold`` si
            existe, o ``ML_CONFIDENCE_THRESHOLD``.
        beta: β para F-beta. Si ``None``, usa ``ML_FBETA``.
        split: Mitad del golden set a evaluar. Por defecto ``"holdout"``, la
            que **no** se usó para elegir el umbral — es la única que da una
            cifra que no está inflada por el propio tuning. Pasar ``None``
            evalúa el conjunto entero (útil para inspección manual, no para
            reportar).

    Returns:
        :class:`GoldenEvalResult` con las métricas (incluido ``recall_no_keyword``).
    """
    from config import settings

    if examples is None:
        examples = load_golden_set()
    if split is not None:
        # `asignar_splits` es idempotente: respeta los splits ya fijados y
        # reparte los que falten, por si el caller trae ejemplos construidos
        # a mano en vez de cargados del JSONL.
        examples = filtrar_split(asignar_splits(examples), split)
    if not examples:
        log.warning("ml_eval.no_examples", split=split)
        return evaluate_probas([], [], threshold=threshold or 0.5, beta=beta or 1.0)
    if split == SPLIT_HOLDOUT and len(examples) < MIN_HOLDOUT_EXAMPLES:
        log.warning(
            "ml_eval.golden_holdout_too_small",
            n=len(examples),
            min_recomendado=MIN_HOLDOUT_EXAMPLES,
        )

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

    result = evaluate_probas(y_true, y_proba, keyword_match=kw, threshold=threshold, beta=beta)
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
    # SOLO la mitad "tune": elegir el umbral sobre todo el golden y luego
    # reportar sobre todo el golden es medirse con la regla que uno mismo
    # acaba de doblar.
    examples = filtrar_split(asignar_splits(examples), SPLIT_TUNE)
    if len(examples) < min_examples:
        log.info("ml_eval.golden_tuning_skipped", n=len(examples), min_required=min_examples)
        return None
    if len(examples) < MIN_TUNE_EXAMPLES:
        log.warning(
            "ml_eval.golden_tune_split_too_small",
            n=len(examples),
            min_recomendado=MIN_TUNE_EXAMPLES,
            hint=(
                "El umbral servido se está fijando sobre muy pocos ejemplos humanos; "
                "amplía el golden set con scripts/sample_golden_candidates.py."
            ),
        )

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
    out["n_tune"] = len(examples)
    out["tune_reliable"] = len(examples) >= MIN_TUNE_EXAMPLES
    log.info("ml_eval.golden_threshold_tuned", **out)
    return out


__all__ = [
    "MIN_HOLDOUT_EXAMPLES",
    "MIN_TUNE_EXAMPLES",
    "SPLIT_HOLDOUT",
    "SPLIT_TUNE",
    "GoldenEvalResult",
    "GoldenExample",
    "asignar_splits",
    "evaluate_classifier",
    "evaluate_probas",
    "filtrar_split",
    "load_golden_set",
    "metricas_operativas",
    "tune_threshold_on_golden",
]
