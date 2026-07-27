"""Entrenamiento del clasificador SAP — entrypoint del workflow de release.

Invocado por ``.github/workflows/train-model.yml``. La secuencia (seed de
negativos → entrenamiento → precompute de ``ml_proba``) vivía como heredoc
``python -c`` en el YAML, fuera del alcance de ruff/mypy/tests; aquí queda
como código normal del proyecto.

No se registra en ``build_default_registry()``: el re-entrenamiento del
clasificador SAP es un job de release con artefacto versionado, distinto del
``ml_retrain_baja`` periódico de ``scheduler/jobs/ml_predicciones.py``.
"""

from __future__ import annotations

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

    seed_negatives()
    metrics = train_from_db()
    log.info("ml_training_metrics", **{k: v for k, v in metrics.items() if k != "error"})

    if "error" in metrics:
        raise RuntimeError(f"Training failed: {metrics['error']}")

    precompute_ml_proba(force=False)
    return metrics


if __name__ == "__main__":
    import sys

    try:
        run()
    except RuntimeError as exc:
        log.error("ml_training_failed", error=str(exc))
        sys.exit(1)
