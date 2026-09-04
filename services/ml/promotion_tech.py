"""Gate de promoción del clasificador multi-tecnología.

Gemelo de :mod:`services.ml.promotion` (que gobierna el binario SAP) y escrito
con **el mismo idioma**: una lista de ``motivos_rechazo`` en vez de un booleano,
el mismo :class:`~services.ml.promotion.ResultadoPromocion`, la versión
**siempre** registrada en ``model_versions`` y el artefacto que sirve
producción publicado **solo** si la lista sale vacía.

Por qué hacía falta
-------------------
``ML_TECH_ENABLED`` lleva en ``True`` desde el principio y ningún workflow
entrenaba ni publicaba el ``tech_classifier``: ``data/`` no está versionado ni
entra en la imagen, así que ``precompute_ml_tecnologias`` devolvía
``skipped_no_model`` en cada corrida mientras el paso de la pipeline salía en
verde. ``.github/workflows/train-tech-model.yml`` cierra ese hueco, y este
módulo es lo que impide que cerrarlo signifique publicar cualquier cosa.

El criterio decisivo es el mismo que el del SAP y por el mismo motivo
-------------------------------------------------------------------
Las etiquetas de entrenamiento salen de ``matches_technology()`` sobre el mismo
texto que ve el modelo siempre que no haya etiqueta humana o de LLM
disponible (``tech_classifier.circular_labels``). Con etiquetas circulares, un
micro-F1 de 0.98 mide cuánto **imita** el modelo al regex, no cuánta tecnología
detecta. Lo único que no se puede subir imitando el regex es
``recall_no_keyword`` sobre el golden set humano
(``tests/fixtures/golden_set_tech.jsonl``, medido por
:mod:`services.ml.eval_tech`): de los positivos humanos que las keywords NO
marcan, cuántos pesca el modelo. Ese es el que bloquea, con el mismo umbral
(:data:`~services.ml.promotion.MIN_RECALL_NO_KEYWORD`) y la misma tolerancia de
regresión que en el binario.

``labels_circulares`` **no** bloquea, igual que en el binario: el golden set es
una medición independiente y ya responde la pregunta. Sí viaja en el resultado
y en el registry, porque el resto de métricas hay que leerlas sabiéndolo.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from observability.logging import get_logger
from services.ml.promotion import (
    MIN_RECALL_NO_KEYWORD,
    TOLERANCIA_RECALL_NO_KEYWORD,
    ResultadoPromocion,
)

if TYPE_CHECKING:
    from services.ml.eval_tech import TechEvalResult

log = get_logger(__name__)

MODEL_NAME = "tech_classifier"

# Artefacto que sirve producción (el asset de la Release que descargan la API y
# los runners vía ``TechnologyClassifier.ensure_downloaded``).
ARTEFACTO_SERVIDO = Path("data/models/tech_classifier.pkl")


def evaluar_gate_tech(
    metrics: dict[str, Any],
    *,
    golden: TechEvalResult | None,
    golden_activo: TechEvalResult | None = None,
) -> list[str]:
    """Motivos por los que NO se debe promocionar. Lista vacía = pasa.

    Función pura, como ``services.ml.promotion.evaluar_gate``: se testea sin BD
    ni artefactos.
    """
    motivos: list[str] = []

    if metrics.get("error"):
        motivos.append(f"entrenamiento_con_error ({metrics['error']})")

    # Un artefacto en el que ninguna etiqueta llegó al tier ML es un pickle que
    # ejecuta el regex de keywords. Servir eso cuesta memoria y una descarga y
    # no aporta nada sobre `matches_technology()`, que es gratis — es el mismo
    # razonamiento que MIN_RECALL_NO_KEYWORD, aplicado a la forma del modelo.
    if int(metrics.get("n_models") or 0) <= 0:
        motivos.append(
            f"sin_modelos_ml (n_models={metrics.get('n_models')}, "
            f"n_rules_fallback={metrics.get('n_rules_fallback')}): "
            "el artefacto solo ejecutaría el filtro de keywords"
        )

    if not int(metrics.get("n_test") or 0):
        motivos.append("sin_test_split: las métricas publicadas no miden nada")

    if golden is None or golden.n == 0:
        motivos.append("sin_golden_set: no se puede medir el valor sobre las keywords")
        return motivos

    if golden.n_no_keyword_positive == 0:
        motivos.append(
            "golden_sin_zona_de_desacuerdo: no hay positivos humanos sin keyword "
            "en el golden set, así que recall_no_keyword no mide nada"
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

    return motivos


def _evaluar_en_golden(clf: Any) -> TechEvalResult | None:
    """Evalúa contra el golden set multi-label. ``None`` si no hay set usable."""
    from services.ml.eval_tech import evaluate_tech_classifier, load_golden_tech_set

    examples = load_golden_tech_set()
    if not examples:
        return None
    return evaluate_tech_classifier(clf, examples)


def promote_tech_if_better(
    clf: Any,
    metrics: dict[str, Any],
    *,
    name: str = MODEL_NAME,
    models_dir: Path | None = None,
    publicar_como: Path | None = None,
    notes: str | None = None,
) -> ResultadoPromocion:
    """Registra la versión y publica el artefacto **solo si** pasa el gate.

    Args:
        clf: ``TechnologyClassifier`` ya entrenado (se le pide ``save`` y
            ``predict_one``).
        metrics: Lo que devolvió ``clf.train()``.
        name: Nombre en el registry.
        models_dir: Directorio de los artefactos versionados.
        publicar_como: Ruta del artefacto que sirve producción. Solo se
            sobrescribe si el gate pasa; si no, el modelo anterior queda
            intacto.
        notes: Nota libre para el registry.
    """
    from db.model_registry import get_active, register_version

    activa = get_active(name)
    version = int(activa["version"]) + 1 if activa else 1
    destino_dir = models_dir or Path("data/models")
    destino_dir.mkdir(parents=True, exist_ok=True)
    guardado = Path(clf.save(destino_dir / f"{name}_v{version}.pkl"))
    sha = hashlib.sha256(guardado.read_bytes()).hexdigest()

    golden = _evaluar_en_golden(clf)
    golden_dict = golden.as_dict() if golden is not None else {}

    golden_activo: TechEvalResult | None = None
    if activa:
        try:
            from scraper.tech_classifier import TechnologyClassifier

            ruta_activa = Path(str(activa.get("path") or ""))
            if ruta_activa.exists():
                golden_activo = _evaluar_en_golden(TechnologyClassifier.load(ruta_activa))
        except Exception as exc:  # pragma: no cover — comparativa best-effort
            log.warning("promotion_tech.golden_activo_no_evaluable", error=str(exc))

    motivos = evaluar_gate_tech(metrics, golden=golden, golden_activo=golden_activo)
    debe_activar = not motivos

    register_version(
        name=name,
        path=str(guardado),
        sha256=sha,
        # ``golden_tech_*`` para que no se confundan con las métricas internas
        # del split (que miden imitación del regex cuando las etiquetas son
        # circulares) ni con las ``golden_holdout_*`` del binario SAP.
        metrics={
            **{k: v for k, v in metrics.items() if k != "per_tech"},
            **{f"golden_tech_{k}": v for k, v in golden_dict.items()},
        },
        n_samples=int(metrics.get("n_samples") or 0),
        notes=notes,
        activate=debe_activar,
    )

    if debe_activar:
        log.info("promotion_tech.activada", name=name, version=version, golden=golden_dict)
        if publicar_como is not None:
            publicar_como.parent.mkdir(parents=True, exist_ok=True)
            publicar_como.write_bytes(guardado.read_bytes())
            from shared.model_integrity import write_checksum

            write_checksum(publicar_como)
            log.info("promotion_tech.artefacto_publicado", path=str(publicar_como))
    else:
        log.warning(
            "promotion_tech.rechazada",
            name=name,
            version=version,
            motivos=motivos,
            golden=golden_dict,
            labels_circulares=metrics.get("labels_circulares"),
        )

    return ResultadoPromocion(
        registrada=True,
        activada=debe_activar,
        version=version,
        motivos_rechazo=motivos,
        golden=golden_dict,
    )


def entrenar_y_promocionar() -> dict[str, Any]:
    """Entrena desde la BD, evalúa en el golden y publica si pasa el gate.

    Es el cuerpo del workflow ``train-tech-model.yml``: vive aquí y no en un
    heredoc del YAML para que pase por ruff/mypy/tests como el resto del
    código, igual que ``scheduler.jobs.ml_training_run`` para el binario.
    """
    from scraper.tech_classifier import entrenar_tech

    clf, metrics = entrenar_tech()
    if "error" in metrics:
        log.error("promotion_tech.entrenamiento_fallido", **metrics)
        return {"metrics": metrics, "promotion": None}

    resultado = promote_tech_if_better(
        clf,
        metrics,
        publicar_como=ARTEFACTO_SERVIDO,
        notes="train-tech-model.yml",
    )
    return {"metrics": metrics, "promotion": resultado.as_dict()}


__all__ = [
    "ARTEFACTO_SERVIDO",
    "MODEL_NAME",
    "entrenar_y_promocionar",
    "evaluar_gate_tech",
    "promote_tech_if_better",
]
