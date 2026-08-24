"""Evaluación honesta del clasificador multi-tecnología contra un golden set.

Motivación
----------
Gemelo multi-label de :mod:`services.ml_eval`, que hace lo mismo para el
clasificador SAP binario. El problema es el mismo y aquí es más grave:

La columna ``licitaciones.tecnologia`` que etiqueta el dataset de
entrenamiento la producen los conectores con
``matches_technology(titulo, descripcion)`` (``scraper/connectors/pscp.py``,
``ted.py``, ``regional_rss.py``) — un regex de keywords aplicado **al mismo
texto** que ve el modelo. Cuando ``scraper.tech_classifier`` no encuentra una
etiqueta independiente y cae a esa columna (avisa con
``tech_classifier.circular_labels``), ``Y[:, j] == 1`` es una función
determinista y perfectamente aprendible del input: cada F1 y cada PR-AUC de
``per_tech`` mide cuánto **imita** el modelo al regex, no cuánta tecnología
detecta. Un 0.98 ahí es compatible con un modelo que no aporta nada.

Lo único que mide el valor real —pescar licitaciones de una tecnología que las
keywords pierden— son etiquetas **humanas** independientes. Este módulo carga
un golden set JSONL multi-label y reporta, **por etiqueta**:

  - precision / recall / F1 y el soporte humano;
  - **``recall_no_keyword``**: de los positivos humanos que el regex NO marca,
    cuántos pesca el modelo. Un modelo que sólo replica las keywords lo tiene
    en 0 por etiqueta, por bien que se vea su F1.

Y agregados sobre **todas** las etiquetas (micro-F1 y macro-F1), más el número
de etiquetas sin soporte en el golden set: un macro-F1 que promedia sólo las
etiquetas con datos es un promedio de los aprobados, y saber cuántas se han
quedado fuera es parte del resultado.

Uso típico::

    from scraper.tech_classifier import TechnologyClassifier
    from services.ml.eval_tech import evaluate_tech_classifier, load_golden_tech_set

    clf = TechnologyClassifier.load()
    result = evaluate_tech_classifier(clf, load_golden_tech_set())
    print(result.macro_f1_all_labels)
    print(result.per_label["SAP"].recall_no_keyword)  # ¿pescamos SAP sin keyword?
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from config.keywords import TECH_LABELS
from observability.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

log = get_logger(__name__)

# Raíz del repo (este archivo vive en services/ml/).
_REPO_ROOT = Path(__file__).resolve().parents[2]

_DEFAULT_GOLDEN_TECH_PATH = "tests/fixtures/golden_set_tech.jsonl"

_VALID_LABELS: frozenset[str] = frozenset(TECH_LABELS)


@dataclass(frozen=True)
class GoldenTechExample:
    """Un ejemplo del golden set multi-label con etiquetas humanas.

    Attributes:
        labels: Tecnologías que un humano ve en el texto. Lista vacía = el
            humano revisó el caso y no hay ninguna (verdadero negativo, no
            "sin etiquetar"): son los ejemplos que sostienen la precisión.
        keyword_labels: Tecnologías que ``matches_technology`` detectaría sobre
            el mismo texto. Es la referencia contra la que se mide el valor
            incremental del modelo; se deriva al cargar salvo que el JSONL la
            fije explícitamente (para conservar lo que el regex hacía el día
            del etiquetado).
    """

    id: str
    titulo: str
    descripcion: str
    labels: list[str] = field(default_factory=list)
    keyword_labels: list[str] = field(default_factory=list)
    cpv: str | None = None
    importe: float | None = None
    note: str = ""

    @property
    def text(self) -> str:
        """Texto combinado título + descripción (sin tokens estructurales)."""
        return f"{self.titulo} {self.descripcion}".strip()


@dataclass
class TechLabelMetrics:
    """Métricas de una tecnología contra las etiquetas humanas."""

    label: str
    support: int  # positivos humanos de esta etiqueta en el golden set
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float
    # De los positivos humanos que las keywords NO marcan, cuántos pesca el
    # modelo. Es la única cifra que no puede subir imitando al regex.
    recall_no_keyword: float
    n_no_keyword_positive: int
    n_no_keyword_caught: int

    def as_dict(self) -> dict[str, Any]:
        """Serializa a dict plano (para logging/registry/API)."""
        return {
            "label": self.label,
            "support": self.support,
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "recall_no_keyword": round(self.recall_no_keyword, 4),
            "n_no_keyword_positive": self.n_no_keyword_positive,
            "n_no_keyword_caught": self.n_no_keyword_caught,
        }


@dataclass
class TechEvalResult:
    """Resultado de evaluar el multi-label contra el golden set."""

    n: int
    n_con_etiqueta: int  # ejemplos con ≥ 1 tecnología humana
    n_labels: int
    n_labels_sin_soporte: int
    micro_precision: float
    micro_recall: float
    micro_f1: float
    # Macro sobre TODAS las etiquetas del universo, incluidas las que no tienen
    # ni un positivo humano (cuentan como 0). Es la cifra pesimista honesta.
    macro_f1_all_labels: float
    # Macro sólo sobre las que tienen soporte: útil, pero es un promedio de las
    # etiquetas que sí tienen datos. Las dos juntas, nunca una sola.
    macro_f1_labels_con_soporte: float
    recall_no_keyword: float
    n_no_keyword_positive: int
    n_no_keyword_caught: int
    per_label: dict[str, TechLabelMetrics] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Serializa a dict plano (para logging/registry/API)."""
        return {
            "n": self.n,
            "n_con_etiqueta": self.n_con_etiqueta,
            "n_labels": self.n_labels,
            "n_labels_sin_soporte": self.n_labels_sin_soporte,
            "micro_precision": round(self.micro_precision, 4),
            "micro_recall": round(self.micro_recall, 4),
            "micro_f1": round(self.micro_f1, 4),
            "macro_f1_all_labels": round(self.macro_f1_all_labels, 4),
            "macro_f1_labels_con_soporte": round(self.macro_f1_labels_con_soporte, 4),
            "recall_no_keyword": round(self.recall_no_keyword, 4),
            "n_no_keyword_positive": self.n_no_keyword_positive,
            "n_no_keyword_caught": self.n_no_keyword_caught,
            **self.extra,
        }

    def as_rows(self) -> list[dict[str, Any]]:
        """Desglose por etiqueta ordenado por soporte descendente."""
        return [
            m.as_dict()
            for m in sorted(self.per_label.values(), key=lambda m: (-m.support, m.label))
        ]


class _MultiLabelClassifier(Protocol):
    """Interfaz mínima del clasificador multi-tecnología.

    La cumple ``scraper.tech_classifier.TechnologyClassifier`` sin adaptador.
    """

    labels: list[str]

    def predict_one(
        self, text: str, *, cpv: str | None = ..., importe: float | None = ...
    ) -> dict[str, Any]: ...


def _default_golden_tech_path() -> Path:
    """Resuelve la ruta del golden set multi-label (relativa al repo).

    ``ML_GOLDEN_TECH_SET_PATH`` no existe todavía en ``config/settings.py``; se
    lee con ``getattr`` para que añadirla más adelante no requiera tocar este
    módulo (el binario usa ``ML_GOLDEN_SET_PATH`` con el mismo patrón).
    """
    from config import settings

    raw = str(getattr(settings, "ML_GOLDEN_TECH_SET_PATH", _DEFAULT_GOLDEN_TECH_PATH))
    p = Path(raw)
    return p if p.is_absolute() else _REPO_ROOT / p


def _normalize_labels(raw: Any, *, campo: str, lineno: int) -> list[str]:  # Any: JSON crudo
    """Normaliza una lista de tecnologías del JSONL y valida contra TECH_LABELS.

    Una etiqueta desconocida es un error, no un valor a descartar en silencio:
    un ``"SALEFORCE"`` mal escrito convertiría un positivo humano en un
    negativo y bajaría el recall medido sin que nadie lo note.
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        items = [p for p in (chunk.strip() for chunk in raw.split(",")) if p]
    elif isinstance(raw, list):
        items = [str(p).strip() for p in raw if str(p).strip()]
    else:
        raise ValueError(f"Golden set tech: '{campo}' debe ser lista o CSV en línea {lineno}")
    out: list[str] = []
    for item in items:
        upper = item.upper()
        if upper not in _VALID_LABELS:
            raise ValueError(
                f"Golden set tech: tecnología desconocida '{item}' en '{campo}', línea {lineno}. "
                f"Válidas: {sorted(_VALID_LABELS)}"
            )
        if upper not in out:
            out.append(upper)
    return out


def keyword_labels_for(titulo: str, descripcion: str) -> list[str]:
    """Tecnologías que ``matches_technology`` detecta sobre este texto.

    Es la definición operativa de "lo que las keywords ya pescan", así que se
    calcula llamando al filtro real en vez de replicarlo: si mañana se añade
    una keyword, el golden set mide el valor incremental contra el filtro
    nuevo, no contra una copia congelada.
    """
    from scraper.filters import matches_technology

    _matched, by_tech = matches_technology(titulo, descripcion)
    return sorted(t for t in by_tech if t in _VALID_LABELS)


def load_golden_tech_set(path: str | Path | None = None) -> list[GoldenTechExample]:
    """Carga el golden set multi-label. Tolera líneas vacías y comentarios (``#``).

    Args:
        path: Ruta al JSONL. Si es ``None``, ``ML_GOLDEN_TECH_SET_PATH`` o el
            default ``tests/fixtures/golden_set_tech.jsonl``.

    Returns:
        Lista de :class:`GoldenTechExample`. Vacía si el fichero no existe.

    Raises:
        ValueError: JSON inválido, falta ``titulo``/``labels``, o una etiqueta
            fuera de ``TECH_LABELS``.
    """
    target = Path(path) if path is not None else _default_golden_tech_path()
    if not target.exists():
        log.warning("eval_tech.golden_set_missing", path=str(target))
        return []

    examples: list[GoldenTechExample] = []
    for lineno, raw_line in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Golden set tech: JSON inválido en línea {lineno}: {exc}") from exc
        if "titulo" not in obj or "labels" not in obj:
            raise ValueError(f"Golden set tech: faltan campos 'titulo'/'labels' en línea {lineno}")
        titulo = str(obj.get("titulo", ""))
        descripcion = str(obj.get("descripcion", ""))
        importe_raw = obj.get("importe")
        keyword_labels = (
            _normalize_labels(obj["keyword_labels"], campo="keyword_labels", lineno=lineno)
            if obj.get("keyword_labels") is not None
            else keyword_labels_for(titulo, descripcion)
        )
        examples.append(
            GoldenTechExample(
                id=str(obj.get("id", f"line-{lineno}")),
                titulo=titulo,
                descripcion=descripcion,
                labels=_normalize_labels(obj["labels"], campo="labels", lineno=lineno),
                keyword_labels=keyword_labels,
                cpv=str(obj["cpv"]) if obj.get("cpv") is not None else None,
                importe=float(importe_raw) if importe_raw is not None else None,
                note=str(obj.get("note", "")),
            )
        )
    log.info("eval_tech.golden_set_loaded", path=str(target), n=len(examples))
    return examples


def _f1(precision: float, recall: float) -> float:
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def evaluate_tech_predictions(
    y_true: Sequence[Iterable[str]],
    y_pred: Sequence[Iterable[str]],
    *,
    keyword_labels: Sequence[Iterable[str]] | None = None,
    labels: Sequence[str] | None = None,
) -> TechEvalResult:
    """Núcleo puro de evaluación a partir de conjuntos de etiquetas.

    Separado de :func:`evaluate_tech_classifier` para poder testearlo sin un
    modelo, igual que ``services.ml_eval.evaluate_probas``. Se calcula con
    conteos explícitos (sin sklearn) porque la definición de cada cifra tiene
    que poder leerse aquí: el universo de etiquetas es un parámetro, no lo que
    aparezca en los datos, y de eso depende ``macro_f1_all_labels``.

    Args:
        y_true: Etiquetas humanas por ejemplo.
        y_pred: Etiquetas predichas por el modelo.
        keyword_labels: Lo que ``matches_technology`` detectaría. Si es
            ``None``, ``recall_no_keyword`` sale 0 sobre 0 ejemplos.
        labels: Universo de etiquetas. Por defecto ``TECH_LABELS``.
    """
    universo = list(labels) if labels is not None else list(TECH_LABELS)
    trues = [set(s) for s in y_true]
    preds = [set(s) for s in y_pred]
    kws: list[set[str]] | None = [set(s) for s in keyword_labels] if keyword_labels else None

    per_label: dict[str, TechLabelMetrics] = {}
    tp_total = fp_total = fn_total = 0
    nokw_pos_total = nokw_caught_total = 0

    for label in universo:
        tp = fp = fn = 0
        nokw_pos = nokw_caught = 0
        for i, (t, p) in enumerate(zip(trues, preds, strict=False)):
            en_true = label in t
            en_pred = label in p
            if en_true and en_pred:
                tp += 1
            elif en_pred:
                fp += 1
            elif en_true:
                fn += 1
            if en_true and kws is not None and i < len(kws) and label not in kws[i]:
                nokw_pos += 1
                if en_pred:
                    nokw_caught += 1
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        per_label[label] = TechLabelMetrics(
            label=label,
            support=tp + fn,
            tp=tp,
            fp=fp,
            fn=fn,
            precision=precision,
            recall=recall,
            f1=_f1(precision, recall),
            recall_no_keyword=(nokw_caught / nokw_pos) if nokw_pos else 0.0,
            n_no_keyword_positive=nokw_pos,
            n_no_keyword_caught=nokw_caught,
        )
        tp_total += tp
        fp_total += fp
        fn_total += fn
        nokw_pos_total += nokw_pos
        nokw_caught_total += nokw_caught

    micro_p = tp_total / (tp_total + fp_total) if (tp_total + fp_total) else 0.0
    micro_r = tp_total / (tp_total + fn_total) if (tp_total + fn_total) else 0.0
    con_soporte = [m for m in per_label.values() if m.support > 0]
    macro_all = sum(m.f1 for m in per_label.values()) / len(per_label) if per_label else 0.0
    macro_con_soporte = sum(m.f1 for m in con_soporte) / len(con_soporte) if con_soporte else 0.0
    return TechEvalResult(
        n=len(trues),
        n_con_etiqueta=sum(1 for t in trues if t),
        n_labels=len(per_label),
        n_labels_sin_soporte=len(per_label) - len(con_soporte),
        micro_precision=micro_p,
        micro_recall=micro_r,
        micro_f1=_f1(micro_p, micro_r),
        macro_f1_all_labels=macro_all,
        macro_f1_labels_con_soporte=macro_con_soporte,
        recall_no_keyword=(nokw_caught_total / nokw_pos_total) if nokw_pos_total else 0.0,
        n_no_keyword_positive=nokw_pos_total,
        n_no_keyword_caught=nokw_caught_total,
        per_label=per_label,
    )


def evaluate_tech_classifier(
    clf: _MultiLabelClassifier,
    examples: list[GoldenTechExample] | None = None,
    *,
    labels: Sequence[str] | None = None,
) -> TechEvalResult:
    """Evalúa un clasificador multi-tecnología entrenado contra el golden set.

    Args:
        clf: Clasificador con ``predict_one(text, cpv=, importe=)`` que
            devuelve ``{"predicted": [label, ...], ...}``. Se usan las
            etiquetas ya umbralizadas por el modelo, no sus scores: lo que se
            mide es lo que el usuario recibe.
        examples: Golden set ya cargado. Si ``None``, se carga del fichero.
        labels: Universo de etiquetas. Por defecto ``clf.labels``.

    Returns:
        :class:`TechEvalResult`, con ``per_label[...].recall_no_keyword`` como
        la cifra que de verdad dice si el modelo aporta sobre las keywords.
    """
    if examples is None:
        examples = load_golden_tech_set()
    universo = list(labels) if labels is not None else list(getattr(clf, "labels", TECH_LABELS))
    if not examples:
        log.warning("eval_tech.no_examples")
        return evaluate_tech_predictions([], [], labels=universo)

    y_true: list[list[str]] = []
    y_pred: list[list[str]] = []
    kw: list[list[str]] = []
    for ex in examples:
        out = clf.predict_one(ex.text, cpv=ex.cpv, importe=ex.importe)
        y_pred.append([str(lbl) for lbl in out.get("predicted", [])])
        y_true.append(list(ex.labels))
        kw.append(list(ex.keyword_labels))

    result = evaluate_tech_predictions(y_true, y_pred, keyword_labels=kw, labels=universo)
    log.info("eval_tech.evaluated", **result.as_dict())
    return result


__all__ = [
    "GoldenTechExample",
    "TechEvalResult",
    "TechLabelMetrics",
    "evaluate_tech_classifier",
    "evaluate_tech_predictions",
    "keyword_labels_for",
    "load_golden_tech_set",
]
