"""``train-model.yml`` sube el fichero cuyo sha256 quedó registrado, y activa después.

Publicar un modelo son dos escrituras en sitios distintos: la fila de
``model_versions`` (ruta y sha256, ``services.ml.promotion.promote_if_better``)
y el asset de la Release (``gh release upload`` en el workflow). Si nombran
ficheros distintos, o si la versión se activa sin que el asset esté subido, el
registro pide un contenido que nadie publicó y ``resolve_active_artifact`` cae
por ``ModelArtifactMismatch`` en todos los runners — lo que pasó el 2026-09-29
por otro camino, el del reentrenamiento automático, que activaba sin subir nada.

``tests/test_ml_promotion_gate.py`` fija la primera mitad (la ruta y el hash
registrados describen el fichero publicado). Estos fijan lo que vive en YAML,
donde no llega ningún otro test: que el workflow sube **ese** fichero, que la
activación va **después** de la subida, y que los dos workflows que rodean a
este —quien lo lanza y quien recalcula ``ml_proba``— tienen lo que necesitan.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from scraper.ml_classifier import _MODEL_PATH
from scraper.ml_training import _MODEL_DIR

_WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
WORKFLOW = _WORKFLOWS / "train-model.yml"
_ENTRENAMIENTO = "Train model"
_SUBIDA = "Upload model to release"
_ACTIVACION = "Activar la versión publicada"
_AUDITORIA = "Medir la discriminación del clasificador"


def _doc(ruta: Path) -> dict[Any, Any]:
    doc = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    return doc


def _disparadores(doc: dict[Any, Any]) -> dict[str, Any]:
    """El bloque ``on:``. PyYAML lee esa clave como el booleano ``True``."""
    disparadores = doc.get("on", doc.get(True))
    assert isinstance(disparadores, dict)
    return disparadores


def _steps(ruta: Path | None = None) -> list[dict[str, Any]]:
    doc = _doc(ruta or WORKFLOW)
    return [step for job in doc["jobs"].values() for step in job.get("steps", [])]


def _step(nombre: str, ruta: Path | None = None) -> dict[str, Any]:
    return next(step for step in _steps(ruta) if step.get("name") == nombre)


def _posicion(nombre: str) -> int:
    return [step.get("name") for step in _steps()].index(nombre)


def _script(nombre: str) -> str:
    """El ``run:`` con las continuaciones de línea ya unidas."""
    return str(_step(nombre)["run"]).replace("\\\n", " ")


# ---------------------------------------------------------------------------
# Qué se sube
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Cuándo se activa
# ---------------------------------------------------------------------------


def test_la_version_se_activa_despues_de_subir_el_artefacto() -> None:
    """Entrenar → subir → activar. Con otro orden, un fallo en medio deja
    activa una versión que nadie puede bajar."""
    assert _posicion(_ENTRENAMIENTO) < _posicion(_SUBIDA) < _posicion(_ACTIVACION)


def test_el_entrenamiento_no_activa() -> None:
    """Sin subcomando el entrypoint entrena con ``activar=False``; el que
    activa es ``activar``, y solo aparece en su paso."""
    assert str(_step(_ENTRENAMIENTO)["run"]).strip() == "python -m scheduler.jobs.ml_training_run"
    con_activar = [
        step["name"] for step in _steps() if "ml_training_run activar" in str(step.get("run", ""))
    ]
    assert con_activar == [_ACTIVACION]


def test_la_activacion_recibe_la_version_del_entrenamiento() -> None:
    paso = _step(_ACTIVACION)

    assert paso["if"] == "steps.train.outputs.promoted == 'true'"
    assert paso["env"]["VERSION"] == "${{ steps.train.outputs.version }}"
    # Por `env` y no interpolada en el script, como el resto del workflow.
    assert '--version "$VERSION"' in str(paso["run"])
    assert "${{" not in str(paso["run"])


def test_la_activacion_puede_leer_la_release_y_escribir_en_la_bd() -> None:
    env = _step(_ACTIVACION)["env"]

    assert env["GITHUB_TOKEN"] == "${{ github.token }}"
    assert env["DATABASE_URL"] == "${{ secrets.DATABASE_URL }}"
    assert env["ENV"] == "prod"


def test_la_auditoria_mide_despues_de_recalcular_ml_proba() -> None:
    """El ``precompute`` forzado vive ahora en la activación: medir antes daría
    la distribución del modelo anterior."""
    assert _posicion(_ACTIVACION) < _posicion(_AUDITORIA)


def test_dos_entrenamientos_no_corren_a_la_vez() -> None:
    """Lo lanzan una persona y el paso semanal: los dos sobre el mismo asset."""
    concurrencia = _doc(WORKFLOW)["concurrency"]

    assert concurrencia["group"] == "train-model"
    assert concurrencia["cancel-in-progress"] is False


# ---------------------------------------------------------------------------
# Quién lo lanza: el cierre de scrape-daily
# ---------------------------------------------------------------------------


def test_scrape_daily_puede_lanzar_el_entrenamiento() -> None:
    """``workflow_dispatch`` por la API pide ``actions: write``; sin él, 403.

    Y sigue sin poder publicar: ``contents`` se queda en lectura.
    """
    doc = _doc(_WORKFLOWS / "scrape-daily.yml")

    assert doc["permissions"] == {"contents": "read", "actions": "write"}


def test_el_cierre_exporta_el_token_con_el_que_se_lanza() -> None:
    cierre = _step("Cierre de la pasada (pasos post-ingesta)", _WORKFLOWS / "scrape-daily.yml")

    assert cierre["env"]["GITHUB_TOKEN"] == "${{ github.token }}"


def test_el_entrenamiento_se_puede_lanzar_por_dispatch() -> None:
    """El paso semanal lo pide por ``workflow_dispatch``: tiene que existir."""
    from scheduler.concept_drift import _WORKFLOW_ENTRENAMIENTO

    assert WORKFLOW.name == _WORKFLOW_ENTRENAMIENTO
    assert "workflow_dispatch" in _disparadores(_doc(WORKFLOW))


# ---------------------------------------------------------------------------
# rescore-ml-proba.yml
# ---------------------------------------------------------------------------

_RESCORE = _WORKFLOWS / "rescore-ml-proba.yml"


def test_el_rescore_solo_se_lanza_a_mano() -> None:
    """Reescribe una columna entera de producción: nunca por calendario."""
    assert list(_disparadores(_doc(_RESCORE))) == ["workflow_dispatch"]


def test_el_rescore_no_puede_publicar_nada() -> None:
    assert _doc(_RESCORE)["permissions"] == {"contents": "read"}


def test_el_rescore_corre_el_entrypoint_con_lo_que_necesita() -> None:
    paso = _step("Rescore", _RESCORE)

    assert str(paso["run"]).strip() == "python -m scheduler.jobs.ml_training_run rescore"
    assert paso["env"]["ENV"] == "prod"
    assert paso["env"]["DATABASE_URL"] == "${{ secrets.DATABASE_URL }}"
    # Sin token el artefacto no se baja de la Release y no hay modelo.
    assert paso["env"]["GITHUB_TOKEN"] == "${{ github.token }}"
