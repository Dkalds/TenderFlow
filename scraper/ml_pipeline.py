"""Alias de compatibilidad de ``services.ml.classifier_pipeline``. No importar desde aquí.

El módulo se mudó a ``services/ml/`` para que servir una predicción no dependa
del paquete de ingesta. Este nombre se conserva por un único motivo:
los ``.pkl`` de los dos clasificadores guardan sus pipelines, y estos nombran
las clases y funciones que vivían aquí
(``scraper.ml_pipeline.SentenceEmbeddingTransformer``, entre otras).
Sin el alias, ``joblib.load`` de un artefacto ya publicado fallaría con
``ModuleNotFoundError`` hasta reentrenarlo.

Es un alias del módulo entero (y no una lista de reexportaciones) porque pickle
resuelve cualquier nombre que el artefacto guardara, también los privados. Se
retira cuando ningún artefacto servido nombre esta ruta; hasta entonces TID251
prohíbe importarlo desde código nuevo (``pyproject.toml``, ``banned-api``).
"""

from __future__ import annotations

import sys

if __name__ == "__main__":  # pragma: no cover - lo cubre un test por subproceso
    # ``python -m scraper.ml_pipeline`` sigue funcionando: ejecuta el módulo real.
    import runpy

    runpy.run_module("services.ml.classifier_pipeline", run_name="__main__")
else:
    from services.ml import classifier_pipeline as _destino

    sys.modules[__name__] = _destino
