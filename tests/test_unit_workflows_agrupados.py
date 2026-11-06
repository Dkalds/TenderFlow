"""Los workflows agrupados encienden un solo job por opción, y cada opción tiene el suyo.

``operaciones-datos.yml`` y ``ml-entrenar.yml`` juntan cada uno varios workflows
de antes y eligen el job con un ``if:`` por entrada (``operacion``, ``modelo``) o
por el ``cron`` que disparó. Ese ``if:`` repite literales de ``on:``: una opción
nueva sin job, un job sin opción o un ``cron`` cambiado en un solo sitio dejan
una operación que no corre nunca, en verde.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

_WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def _doc(nombre: str) -> dict[Any, Any]:
    doc = yaml.safe_load((_WORKFLOWS / nombre).read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    return doc


def _disparadores(doc: dict[Any, Any]) -> dict[str, Any]:
    """El bloque ``on:``. PyYAML lee esa clave como el booleano ``True``."""
    disparadores = doc.get("on", doc.get(True))
    assert isinstance(disparadores, dict)
    return disparadores


@pytest.mark.parametrize(
    ("nombre", "entrada"),
    [("operaciones-datos.yml", "operacion"), ("ml-entrenar.yml", "modelo")],
)
def test_cada_opcion_enciende_exactamente_un_job(nombre: str, entrada: str) -> None:
    doc = _doc(nombre)
    opciones = _disparadores(doc)["workflow_dispatch"]["inputs"][entrada]["options"]
    condiciones = {job_id: str(job.get("if", "")) for job_id, job in doc["jobs"].items()}

    for opcion in opciones:
        jobs = [
            job_id for job_id, c in condiciones.items() if f"inputs.{entrada} == '{opcion}'" in c
        ]
        assert len(jobs) == 1, f"{opcion}: {jobs}"
    # Y ningún job queda fuera: todos dependen de una opción.
    assert all(f"inputs.{entrada} == '" in c for c in condiciones.values())


def test_cada_cron_de_ml_entrenar_enciende_exactamente_un_job() -> None:
    doc = _doc("ml-entrenar.yml")
    crons = [entrada["cron"] for entrada in _disparadores(doc)["schedule"]]

    for cron in crons:
        jobs = [
            job_id
            for job_id, job in doc["jobs"].items()
            if f"github.event.schedule == '{cron}'" in str(job.get("if", ""))
        ]
        assert len(jobs) == 1, f"{cron}: {jobs}"
    # El job SAP no se programa: lo lanzan una persona o el active learning.
    assert "github.event.schedule" not in str(doc["jobs"]["sap"]["if"])
