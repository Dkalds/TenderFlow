"""``train-predictivos.yml`` publica donde el resolvedor busca primero.

El workflow subía los artefactos a lo que fuera *latest*, y ``release.yml``
crea una *latest* nueva —sin assets de modelo— con cada tag ``v*``: publicar
software dejaba a ``ml-scoring`` sin artefactos. Ahora publica en una Release
de tag fijo que nunca pasa a *latest*, y el tag vive dos veces —en el YAML y en
``shared.release_assets.ML_MODELS_RELEASE_TAG`` (lo que consulta
``shared/model_artifacts.py``)—: estos tests impiden que diverjan en silencio.

También fijan la higiene de ``ALERT_MIN_LEVEL``: sin ``|| 'literal'`` en el
YAML, el default vigente es el de ``config/settings.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from shared.release_assets import ML_MODELS_RELEASE_TAG

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "train-predictivos.yml"
_SUBIDA = "Upload artifacts to release"


def _steps() -> list[dict[str, Any]]:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return [step for job in doc["jobs"].values() for step in job.get("steps", [])]


def _step(nombre: str) -> dict[str, Any]:
    return next(step for step in _steps() if step.get("name") == nombre)


def _script(nombre: str) -> str:
    """El ``run:`` con las continuaciones de línea ya unidas."""
    return str(_step(nombre)["run"]).replace("\\\n", " ")


def test_publica_en_la_release_que_el_resolvedor_consulta_primero() -> None:
    assert _step(_SUBIDA)["env"]["TAG"] == ML_MODELS_RELEASE_TAG


def test_la_release_fija_se_crea_sin_pasar_a_latest() -> None:
    crear = [linea for linea in _script(_SUBIDA).splitlines() if "gh release create" in linea]

    assert len(crear) == 1
    assert '"$TAG"' in crear[0]
    assert "--latest=false" in crear[0]


def test_el_destino_ya_no_se_resuelve_por_latest() -> None:
    """``gh release view`` sin tag resuelve *latest*: toda consulta lleva el tag."""
    vistas = [linea for linea in _script(_SUBIDA).splitlines() if "gh release view" in linea]

    assert vistas
    assert all('"$TAG"' in linea for linea in vistas)


def test_sube_con_clobber_y_verifica_nombre_a_nombre() -> None:
    script = _script(_SUBIDA)

    assert 'gh release upload "$TAG" $ARTEFACTOS --clobber' in script
    assert 'grep -Fqx "$nombre"' in script


def test_alert_min_level_solo_se_exporta_si_la_variable_existe() -> None:
    step = _step("Exportar overrides de repositorio definidos")

    assert step["env"]["IN_ALERT_MIN_LEVEL"] == "${{ vars.ALERT_MIN_LEVEL }}"
    assert 'if [ -n "${IN_ALERT_MIN_LEVEL:-}" ]; then' in step["run"]
    assert 'echo "ALERT_MIN_LEVEL=$IN_ALERT_MIN_LEVEL" >> "$GITHUB_ENV"' in step["run"]
    assert "ALERT_MIN_LEVEL" not in _step("Retrain predictive models")["env"]
    for paso in _steps():
        for valor in (paso.get("env") or {}).values():
            assert "||" not in str(valor)
