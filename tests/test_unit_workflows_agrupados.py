"""Los workflows agrupados encienden un solo job por opción, y cada opción tiene el suyo.

``operaciones-datos.yml`` y ``ml-entrenar.yml`` juntan cada uno varios workflows
de antes y eligen el job con un ``if:`` por entrada (``operacion``, ``modelo``) o
por el ``cron`` que disparó. Ese ``if:`` repite literales de ``on:``: una opción
nueva sin job, un job sin opción o un ``cron`` cambiado en un solo sitio dejan
una operación que no corre nunca, en verde.

Y los ``cron`` de ML se fijan contra la ventana del carril de ingesta: se
comprueba con el ``timeout-minutes`` real de ``scrape-daily.yml``, no con el
que recuerde un comentario.
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
    # El grupo de concurrencia también elige el modelo por el literal del cron.
    assert f"github.event.schedule == '{crons[0]}'" in doc["concurrency"]["group"]


def _minutos_del_dia(cron: str) -> list[int]:
    """Minutos del día UTC en que arranca un cron ``M H …`` con ``H`` fija o ``*/N``."""
    minuto, hora = cron.split()[:2]
    horas = range(0, 24, int(hora[2:])) if hora.startswith("*/") else [int(hora)]
    return [h * 60 + int(minuto) for h in horas]


def test_los_cron_de_ml_no_caen_dentro_de_una_pasada_de_scrape() -> None:
    """Cada cron de ML, con el techo de su job, cabe en un hueco entre pasadas de ingesta.

    El hueco se calcula con el ``timeout-minutes`` real de ``scrape-daily``: los
    comentarios que fijaban estos horarios contaban 120 min cuando ya eran 155,
    y el cron de las 06:47 caía dentro de la pasada de las 04:23.
    """
    scrape = _doc("scrape-daily.yml")
    duracion_scrape = scrape["jobs"]["scrape"]["timeout-minutes"]
    pasadas = [m for e in _disparadores(scrape)["schedule"] for m in _minutos_del_dia(e["cron"])]

    programados: list[tuple[str, str, int]] = []
    for nombre in ("ml-scoring.yml", "ml-entrenar.yml"):
        doc = _doc(nombre)
        # Si algún job elige por el cron, solo corre el suyo; si no, corren todos.
        por_cron = any(
            "github.event.schedule" in str(j.get("if", "")) for j in doc["jobs"].values()
        )
        for entrada in _disparadores(doc)["schedule"]:
            cron = entrada["cron"]
            jobs = [
                job
                for job in doc["jobs"].values()
                if not por_cron or f"github.event.schedule == '{cron}'" in str(job.get("if", ""))
            ]
            programados += [(nombre, cron, job["timeout-minutes"]) for job in jobs]
    assert programados

    for nombre, cron, duracion in programados:
        for inicio in _minutos_del_dia(cron):
            for pasada in pasadas:
                # Dos intervalos en un día circular: uno arranca dentro del otro.
                solapa = (inicio - pasada) % 1440 < duracion_scrape or (
                    pasada - inicio
                ) % 1440 < duracion
                assert not solapa, (
                    f"{nombre} '{cron}' pisa la pasada de las {pasada // 60}:{pasada % 60:02d}"
                )
