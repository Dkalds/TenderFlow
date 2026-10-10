"""Los `.pkl` publicados antes de la mudanza a ``services/ml/`` siguen cargando.

Los clasificadores se serializan con ``joblib.dump(self)``, así que cada
artefacto guarda la ruta del módulo donde vivía su clase. Los que están en la
Release y en el almacén se escribieron con ``scraper.ml_classifier``,
``scraper.tech_classifier`` y ``scraper.ml_pipeline``; los alias de ``scraper/``
existen para que pickle siga resolviendo esos nombres. Si alguien borra un
alias antes de reentrenar, este test es lo que falla — y no ``ml_scoring`` en
producción.
"""

from __future__ import annotations

import importlib
import pickle
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

#: (ruta que nombran los artefactos viejos, módulo real, un nombre que guardan)
_ALIAS = [
    ("scraper.ml_classifier", "services.ml.sap_classifier", "SAPClassifier"),
    ("scraper.tech_classifier", "services.ml.tech_classifier", "TechnologyClassifier"),
    ("scraper.ml_pipeline", "services.ml.classifier_pipeline", "SentenceEmbeddingTransformer"),
    # Un nombre privado: pickle guarda funciones por su ruta, sean públicas o no.
    ("scraper.ml_pipeline", "services.ml.classifier_pipeline", "_augment_text"),
]


@pytest.mark.parametrize(("viejo", "nuevo", "nombre"), _ALIAS)
def test_un_pickle_con_la_ruta_vieja_resuelve_al_modulo_nuevo(
    viejo: str, nuevo: str, nombre: str
) -> None:
    """Protocolo 0 a mano: ``c<módulo>\\n<nombre>\\n.`` es un GLOBAL y nada más."""
    referencia = f"c{viejo}\n{nombre}\n.".encode()

    resuelto = pickle.loads(referencia)  # noqa: S301 - bytes escritos en esta línea

    assert resuelto is getattr(importlib.import_module(nuevo), nombre)


@pytest.mark.parametrize(("viejo", "nuevo"), sorted({(v, n) for v, n, _ in _ALIAS}))
def test_el_alias_es_el_mismo_modulo_y_no_una_copia(viejo: str, nuevo: str) -> None:
    """Dos objetos módulo distintos tendrían dos ``_MODEL_PATH`` que parchear."""
    assert importlib.import_module(viejo) is importlib.import_module(nuevo)


def test_un_clasificador_nuevo_se_serializa_con_la_ruta_nueva() -> None:
    """Lo que se entrene desde hoy ya no depende del alias."""
    from services.ml.sap_classifier import SAPClassifier
    from services.ml.tech_classifier import TechnologyClassifier

    assert SAPClassifier.__module__ == "services.ml.sap_classifier"
    assert TechnologyClassifier.__module__ == "services.ml.tech_classifier"


def test_python_m_con_la_ruta_vieja_ejecuta_el_cli_real() -> None:
    """``python -m scraper.ml_classifier`` no puede volverse un no-op silencioso."""
    proceso = subprocess.run(
        [sys.executable, "-m", "scraper.ml_classifier", "comando-inexistente"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert proceso.returncode == 1
    assert "Comando desconocido" in proceso.stdout
