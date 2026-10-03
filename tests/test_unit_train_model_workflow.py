"""``train-model.yml`` sube el fichero cuyo sha256 quedó registrado.

Publicar un modelo son dos escrituras en sitios distintos: la fila de
``model_versions`` (ruta y sha256, ``services.ml.promotion.promote_if_better``)
y el asset de la Release (``gh release upload`` en el workflow). Si nombran
ficheros distintos, el registro pide un contenido que nadie publicó y
``resolve_active_artifact`` cae por ``ModelArtifactMismatch`` en todos los
runners — lo que pasó el 2026-09-29 por otro camino, el del reentrenamiento
automático, que activaba sin subir nada.

``tests/test_ml_promotion_gate.py`` ya fija la primera mitad (la ruta y el hash
registrados describen el fichero publicado). Estos fijan la segunda: el
workflow sube **ese** fichero, y solo cuando el gate lo publicó.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from scraper.ml_classifier import _MODEL_PATH
from scraper.ml_training import _MODEL_DIR

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "train-model.yml"
_SUBIDA = "Upload model to release"


def _steps() -> list[dict[str, Any]]:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return [step for job in doc["jobs"].values() for step in job.get("steps", [])]


def _step(nombre: str) -> dict[str, Any]:
    return next(step for step in _steps() if step.get("name") == nombre)


def _script(nombre: str) -> str:
    """El ``run:`` con las continuaciones de línea ya unidas."""
    return str(_step(nombre)["run"]).replace("\\\n", " ")


def test_el_entrenamiento_publica_el_fichero_que_sirven_los_runners() -> None:
    """``train_from_db`` publica en ``_MODEL_DIR/sap_classifier.pkl``.

    Es el nombre por el que ``resolve_active_artifact`` pedirá el asset desde
    otro runner (``Path(path).name``).
    """
    assert _MODEL_PATH.parent == _MODEL_DIR
    assert _MODEL_PATH.name == "sap_classifier.pkl"


def test_el_workflow_sube_ese_fichero_y_su_checksum() -> None:
    subida = next(linea for linea in _script(_SUBIDA).splitlines() if "gh release upload" in linea)

    assert f"data/models/{_MODEL_PATH.name}" in subida.split()
    assert f"data/models/{_MODEL_PATH.with_suffix('.sha256').name}" in subida.split()


def test_solo_sube_lo_que_el_gate_publico() -> None:
    """Un candidato rechazado no deja ``sap_classifier.pkl`` que subir."""
    assert _step(_SUBIDA)["if"] == "steps.train.outputs.promoted == 'true'"
