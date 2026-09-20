"""``pliegos.yml`` propaga lo que necesita la pre-generación del resumen IA.

La fase existía en ``scheduler/jobs/documentos_embeddings.py`` y nunca podía
correr desde el cron: el workflow no pasaba ``RESUMEN_PREGEN_ENABLED`` ni
``REDIS_URL``, así que se quedaba en ``disabled`` o, encendida a mano, se
saltaba por falta de caché compartida. Estos tests fijan la propagación y que
el interruptor siga apagado por defecto (sin ``|| 'true'`` en el YAML: el
default es el del código).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "pliegos.yml"


def _steps() -> list[dict[str, Any]]:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return [step for job in doc["jobs"].values() for step in job.get("steps", [])]


def _step(nombre: str) -> dict[str, Any]:
    return next(step for step in _steps() if step.get("name") == nombre)


def test_el_batch_recibe_redis_de_los_secrets() -> None:
    env = _step("Run pliegos batch (fetch + chunk + embed)")["env"]
    assert env["REDIS_URL"] == "${{ secrets.REDIS_URL }}"
    assert env["REDIS_PASSWORD"] == "${{ secrets.REDIS_PASSWORD }}"


def test_resumen_pregen_solo_se_exporta_si_la_variable_existe() -> None:
    """Sin la variable de repo no se exporta nada: manda el default (apagado)."""
    step = _step("Exportar overrides de repositorio definidos")
    assert step["env"]["IN_RESUMEN_PREGEN_ENABLED"] == "${{ vars.RESUMEN_PREGEN_ENABLED }}"
    script = step["run"]
    assert 'if [ -n "${IN_RESUMEN_PREGEN_ENABLED:-}" ]; then' in script
    assert 'echo "RESUMEN_PREGEN_ENABLED=$IN_RESUMEN_PREGEN_ENABLED" >> "$GITHUB_ENV"' in script
    assert "||" not in step["env"]["IN_RESUMEN_PREGEN_ENABLED"]


def test_el_default_del_codigo_es_apagado() -> None:
    from config.settings_resumen import ResumenPregenSettings

    assert ResumenPregenSettings.model_fields["RESUMEN_PREGEN_ENABLED"].default is False
