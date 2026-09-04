"""Entrenamiento del clasificador SAP — entrypoint del workflow de release.

Invocado por ``.github/workflows/train-model.yml``: seed de negativos →
entrenamiento → precompute de ``ml_proba``. Vivía como heredoc ``python -c``
dentro del YAML, fuera del alcance de ruff, mypy y los tests; aquí queda como
código normal.

El clasificador **multi-tecnología** tiene su propio entrypoint desde #263:
``scheduler/jobs/tech_training_run.py``, invocado por ``train-tech.yml``. Este
módulo llegó a tener un subcomando ``tech`` que hacía lo mismo; se retiró al
fusionar, porque el de allí aplica un gate de etiquetas circulares más estricto
—un suelo absoluto de etiquetas independientes— y tener dos caminos para
publicar el mismo artefacto es cómo se acaba publicando el peor de los dos.

No se registra en ``build_default_registry()``: el re-entrenamiento del
clasificador SAP es un job de release con artefacto versionado, distinto del
``ml_retrain_baja`` periódico de ``scheduler/jobs/ml_predicciones.py``.
"""

from __future__ import annotations

import os
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)


def run() -> dict[str, Any]:
    """Siembra negativos, entrena desde BD y precomputa ``ml_proba``.

    Returns:
        Las métricas devueltas por ``train_from_db``.

    Raises:
        RuntimeError: Si el entrenamiento devuelve un dict con ``error``.
    """
    from scraper.ml_training import precompute_ml_proba, seed_negatives, train_from_db

    # ``include_ti=True``: en serving el modelo SOLO puntúa licitaciones con
    # CPV 48/72 (``scraper.pipeline._ml_classify_entry`` descarta el resto
    # antes de parsear). Sembrando solo negativos no-TI, el separador más
    # fuerte que aprendía era el propio CPV — constante en el punto donde de
    # verdad decide. Los hard negatives TI son los que enseñan a distinguir
    # SAP de otro proveedor de TI.
    # ``spread_months=6``: con un solo mes, los negativos comparten ventana
    # temporal y vocabulario, otro atajo que el modelo aprende en vez de la
    # señal. Es exactamente lo que el docstring de
    # ``_collect_negatives_from_month`` dice querer evitar.
    seed_negatives(include_ti=True, spread_months=6)
    metrics = train_from_db()
    log.info("ml_training_metrics", **{k: v for k, v in metrics.items() if k != "error"})

    if "error" in metrics:
        raise RuntimeError(f"Training failed: {metrics['error']}")

    # ``force=True``, y solo si se promocionó: si el modelo cambió, dejar los
    # ``ml_proba`` viejos deja la superficie de serving y el test de drift de
    # predicciones mostrando los scores del modelo anterior. Y si el gate
    # rechazó, en este runner no hay artefacto que aplicar — ``precompute``
    # degradaría a ``skipped_no_model`` sin hacer nada útil.
    if promocionado(metrics):
        precompute_ml_proba(force=True)
    return metrics


def promocionado(metrics: dict[str, Any]) -> bool:
    """¿Pasó el gate de promoción y hay artefacto nuevo que publicar?

    ``train_from_db`` delega en ``services.ml.promotion.promote_if_better``,
    que **solo** escribe ``data/models/sap_classifier.pkl`` —el asset de la
    Release que descargan la API y los runners— si el candidato supera el
    gate. Un rechazo no es un error: es el mecanismo funcionando.
    """
    promocion = metrics.get("promotion") or {}
    return bool(promocion.get("activada"))


def _emitir_salida_github(metrics: dict[str, Any]) -> None:
    """Escribe el desenlace en ``$GITHUB_OUTPUT`` para que el workflow decida.

    Sin esto, ``train-model.yml`` no puede distinguir "el gate rechazó al
    candidato" de "el entrenamiento reventó": en ambos casos falta el
    ``.pkl``, y el paso de verificación moría con un ``ls: cannot access``
    que no explica nada.
    """
    destino = os.environ.get("GITHUB_OUTPUT")
    if not destino:
        return
    promocion = metrics.get("promotion") or {}
    motivos = "; ".join(str(m) for m in (promocion.get("motivos_rechazo") or []))
    golden = promocion.get("golden") or {}
    lineas = [
        f"promoted={'true' if promocionado(metrics) else 'false'}",
        f"version={promocion.get('version') or ''}",
        # Una sola línea: los outputs multilinea necesitan heredoc y estos
        # motivos son frases cortas.
        f"rejection_reasons={motivos.replace(chr(10), ' ')}",
        f"recall_no_keyword={golden.get('recall_no_keyword', '')}",
        f"n_train={metrics.get('n_train', '')}",
        f"n_test={metrics.get('n_test', '')}",
    ]
    with open(destino, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lineas) + "\n")


if __name__ == "__main__":
    import sys

    # Un solo camino: el clasificador SAP binario, que es lo que invoca
    # `train-model.yml`. El multi-etiqueta tiene su propio entrypoint desde
    # #263 (`scheduler/jobs/tech_training_run.py`, workflow `train-tech.yml`),
    # con un gate de etiquetas circulares más estricto que el que este módulo
    # llegó a tener: un suelo absoluto de etiquetas independientes, en vez de
    # fiarse del flag `labels_circulares`, que se apaga en cuanto UNA fila trae
    # etiqueta humana.
    try:
        _metrics = run()
    except RuntimeError as exc:
        log.error("ml_training_failed", error=str(exc), modelo="sap")
        sys.exit(1)

    _emitir_salida_github(_metrics)
    if not promocionado(_metrics):
        # Salida 0 a propósito: el entrenamiento terminó bien y el gate hizo
        # su trabajo. Marcar esto en rojo enseñaría a ignorar los rojos. El
        # workflow se encarga de que quede visible que NO se publicó nada.
        log.warning(
            "ml_training_no_promocionado",
            modelo="sap",
            motivos=(_metrics.get("promotion") or {}).get("motivos_rechazo"),
        )
