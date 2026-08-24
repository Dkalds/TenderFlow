"""Gate de promoción único para el clasificador SAP.

Motivación
----------
Coexistían dos caminos de reentrenamiento con garantías opuestas:

- ``scheduler.concept_drift.maybe_retrain_classifier`` (semanal, disparado por
  feedback) tenía gate de tres métricas y registraba la versión.
- ``scraper.ml_training.train_from_db`` —el que produce el asset de la Release
  que descargan la API y todos los runners, o sea **el modelo que realmente se
  sirve**— guardaba el ``.pkl`` si el entrenamiento no lanzaba ``error``, sin
  gate, sin fila en ``model_versions`` y sin sha registrado. Su propio docstring
  lo admitía. Un entrenamiento con datos degradados se promocionaba solo, y no
  había versión anterior registrada a la que volver.

Este módulo concentra la decisión para que ambos caminos pasen por la misma
puerta.

Qué mide el gate
----------------
El gate anterior comparaba ``f1``/``pr_auc``/``brier`` del candidato contra los
del modelo activo. Dos problemas:

1. **Cada modelo mide sobre su propio test set.** Los splits se recalculan en
   cada reentrenamiento sobre un dataset que crece, así que la comparación no
   era entre modelos sino entre conjuntos de evaluación distintos. Ahora la
   comparación decisiva se hace sobre el **golden set humano** (mitad
   ``holdout``), que es fijo, y ambos candidatos se evalúan sobre él.

2. **Gateaba sobre la imitación del filtro de keywords.** Las etiquetas del
   test split derivan de ``raw_keywords``, así que un modelo que reproduce el
   regex saca un f1 excelente sin aportar nada. La métrica que sí mide el valor
   incremental —``recall_no_keyword``, los SAP reales que las keywords no
   marcan— se calculaba y se guardaba, pero no bloqueaba. Ahora bloquea: un
   modelo que no supera el mínimo no se promociona, porque servir el regex es
   más barato que servir un pickle que hace lo mismo.

Además se exige ``metrics_reliable``: con un test de diez filas, un f1 a cuatro
decimales no es una medición y no puede decidir una promoción.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from observability.logging import get_logger

if TYPE_CHECKING:
    from services.ml_eval import GoldenEvalResult

log = get_logger(__name__)

# Tolerancias de regresión sobre las métricas del test split. Son un guardarraíl
# secundario: la decisión principal la toma el golden set.
TOLERANCIA_F1 = 0.02
TOLERANCIA_PR_AUC = 0.03
TOLERANCIA_BRIER = 0.05
# Un modelo que no pesca NADA que las keywords no pesquen ya no aporta nada
# sobre `matches_sap()`, que es gratis y no hay que reentrenar.
MIN_RECALL_NO_KEYWORD = 0.05
# Cuánto puede empeorar el recall incremental respecto al modelo activo.
TOLERANCIA_RECALL_NO_KEYWORD = 0.05


class _ClasificadorEvaluable(Protocol):
    """Lo que el gate necesita de un clasificador para evaluarlo."""

    def predict(
        self, text: str, *, cpv: str | None = ..., importe: float | None = ...
    ) -> tuple[bool, float]: ...


@dataclass
class ResultadoPromocion:
    """Qué decidió el gate y por qué."""

    registrada: bool
    activada: bool
    version: int | None
    motivos_rechazo: list[str] = field(default_factory=list)
    golden: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "registrada": self.registrada,
            "activada": self.activada,
            "version": self.version,
            "motivos_rechazo": self.motivos_rechazo,
            **({"golden": self.golden} if self.golden else {}),
        }


def evaluar_en_golden(clf: _ClasificadorEvaluable) -> GoldenEvalResult | None:
    """Evalúa el clasificador sobre la mitad ``holdout`` del golden set.

    Devuelve ``None`` si no hay golden set utilizable — en ese caso el gate no
    puede pronunciarse sobre el valor incremental y lo dice en los motivos.
    """
    from services.ml_eval import SPLIT_HOLDOUT, evaluate_classifier, load_golden_set

    examples = load_golden_set()
    if not examples:
        return None
    resultado = evaluate_classifier(clf, examples, split=SPLIT_HOLDOUT)
    if resultado.n == 0:
        return None
    return resultado


def _motivos_regresion(
    nuevas: dict[str, Any],
    previas: dict[str, Any],
) -> list[str]:
    """Comprueba que el candidato no regresa respecto al activo (guardarraíl)."""
    motivos: list[str] = []

    old_f1 = float(previas.get("f1") or 0.0)
    new_f1 = float(nuevas.get("f1") or 0.0)
    if old_f1 > 0.0 and new_f1 < old_f1 - TOLERANCIA_F1:
        motivos.append(f"f1 {new_f1:.4f} < {old_f1:.4f} - {TOLERANCIA_F1}")

    old_pr = previas.get("pr_auc")
    if old_pr is not None:
        new_pr = float(nuevas.get("pr_auc") or 0.0)
        if new_pr < float(old_pr) - TOLERANCIA_PR_AUC:
            motivos.append(f"pr_auc {new_pr:.4f} < {float(old_pr):.4f} - {TOLERANCIA_PR_AUC}")

    old_brier = previas.get("brier")
    if old_brier is not None:
        new_brier = float(nuevas.get("brier") or 1.0)
        if new_brier > float(old_brier) + TOLERANCIA_BRIER:
            motivos.append(f"brier {new_brier:.4f} > {float(old_brier):.4f} + {TOLERANCIA_BRIER}")

    return motivos


def evaluar_gate(
    metrics: dict[str, Any],
    *,
    metricas_activas: dict[str, Any] | None,
    golden: GoldenEvalResult | None,
    golden_activo: GoldenEvalResult | None = None,
) -> list[str]:
    """Devuelve la lista de motivos por los que NO se debe promocionar.

    Lista vacía = el candidato pasa. Es una función pura: se puede testear sin
    BD ni artefactos.
    """
    motivos: list[str] = []

    if not metrics.get("metrics_reliable", False):
        motivos.append(
            f"metricas_no_fiables (n_test={metrics.get('n_test')}, "
            f"n_positive_test={metrics.get('n_positive_test')})"
        )

    if metrics.get("split_strategy") not in ("temporal", "grouped_random"):
        motivos.append(f"split_desconocido ({metrics.get('split_strategy')!r})")

    if golden is None:
        motivos.append("sin_golden_set: no se puede medir el valor sobre las keywords")
    else:
        if golden.n_no_keyword_positive == 0:
            motivos.append(
                "golden_sin_zona_de_desacuerdo: no hay positivos humanos sin keyword "
                "en el holdout, así que recall_no_keyword no mide nada"
            )
        elif golden.recall_no_keyword < MIN_RECALL_NO_KEYWORD:
            motivos.append(
                f"recall_no_keyword {golden.recall_no_keyword:.4f} < {MIN_RECALL_NO_KEYWORD} "
                "(el modelo no aporta sobre el filtro de keywords)"
            )
        if golden_activo is not None and golden_activo.n_no_keyword_positive > 0:
            caida = golden_activo.recall_no_keyword - golden.recall_no_keyword
            if caida > TOLERANCIA_RECALL_NO_KEYWORD:
                motivos.append(
                    f"recall_no_keyword cae {caida:.4f} respecto al activo "
                    f"({golden_activo.recall_no_keyword:.4f} -> {golden.recall_no_keyword:.4f})"
                )

    if metricas_activas:
        motivos.extend(_motivos_regresion(metrics, metricas_activas))

    return motivos


def promote_if_better(
    clf: Any,
    metrics: dict[str, Any],
    *,
    name: str = "sap_classifier",
    n_feedbacks: int | None = None,
    notes: str | None = None,
    models_dir: Path | None = None,
    publicar_como: Path | None = None,
) -> ResultadoPromocion:
    """Registra la versión y la activa **solo si** pasa el gate.

    La versión se registra SIEMPRE (aunque no pase): es lo que permite ver el
    histórico y hacer rollback. Lo que el gate decide es la *activación* y la
    publicación del artefacto que sirve producción.

    Args:
        clf: ``SAPClassifier`` ya entrenado (se le pide ``save`` y ``predict``).
        metrics: Métricas devueltas por ``clf.train()``.
        name: Nombre en el registry.
        n_feedbacks: Feedbacks humanos que dispararon el reentrenamiento.
        notes: Nota libre para el registry.
        models_dir: Directorio de los artefactos versionados.
        publicar_como: Ruta del artefacto que sirve producción (el que
            descargan API y runners). Solo se sobrescribe si el gate pasa; si
            no, el modelo anterior queda intacto.
    """
    from db.model_registry import get_active, register_version

    activa = get_active(name)
    version = int(activa["version"]) + 1 if activa else 1
    destino_dir = models_dir or Path("data/models")
    destino_dir.mkdir(parents=True, exist_ok=True)
    ruta_version = destino_dir / f"{name}_v{version}.pkl"
    guardado = Path(clf.save(ruta_version))
    sha = hashlib.sha256(guardado.read_bytes()).hexdigest()

    golden = evaluar_en_golden(clf)
    golden_dict = golden.as_dict() if golden is not None else {}

    golden_activo: GoldenEvalResult | None = None
    if activa:
        try:
            from scraper.ml_classifier import SAPClassifier

            ruta_activa = Path(str(activa.get("path") or ""))
            if ruta_activa.exists():
                golden_activo = evaluar_en_golden(SAPClassifier.load(ruta_activa))
        except Exception as exc:  # pragma: no cover — comparativa best-effort
            log.warning("promotion.golden_activo_no_evaluable", error=str(exc))

    motivos = evaluar_gate(
        metrics,
        metricas_activas=(activa or {}).get("metrics") if activa else None,
        golden=golden,
        golden_activo=golden_activo,
    )
    debe_activar = not motivos

    n_samples = int(metrics.get("n_train") or 0) + int(metrics.get("n_test") or 0)
    register_version(
        name=name,
        path=str(guardado),
        sha256=sha,
        # ``golden_holdout_*`` y no ``golden_*``: train() ya guarda
        # ``golden_*`` con las métricas de la mitad "tune" (donde se eligió
        # el umbral). Mezclarlas sería volver a confundir el conjunto donde
        # se ajusta con el conjunto donde se reporta.
        metrics={**metrics, **{f"golden_holdout_{k}": v for k, v in golden_dict.items()}},
        n_samples=n_samples,
        n_feedbacks=n_feedbacks,
        notes=notes,
        activate=debe_activar,
    )

    if debe_activar:
        log.info("promotion.activada", name=name, version=version, golden=golden_dict)
        if publicar_como is not None:
            publicar_como.parent.mkdir(parents=True, exist_ok=True)
            publicar_como.write_bytes(guardado.read_bytes())
            _escribir_checksum(publicar_como)
            log.info("promotion.artefacto_publicado", path=str(publicar_como))
    else:
        log.warning(
            "promotion.rechazada",
            name=name,
            version=version,
            motivos=motivos,
            golden=golden_dict,
        )

    return ResultadoPromocion(
        registrada=True,
        activada=debe_activar,
        version=version,
        motivos_rechazo=motivos,
        golden=golden_dict,
    )


def _escribir_checksum(path: Path) -> None:
    """Regenera el ``.sha256`` co-ubicado del artefacto publicado."""
    from shared.model_integrity import write_checksum

    write_checksum(path)


__all__ = [
    "MIN_RECALL_NO_KEYWORD",
    "ResultadoPromocion",
    "evaluar_en_golden",
    "evaluar_gate",
    "promote_if_better",
]
