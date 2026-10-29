"""Los workflows que escriben licitaciones no arrancan contra una BD de otra generación.

Del 2026-10-26 al 10-28 ``scrape-daily.yml`` y ``scrape-bulk.yml`` corrieron con
el código de la fase B de identidad PLACSP contra una BD sin ``v164`` y salieron
en verde mientras escribían claves nuevas junto a las viejas (#577). Desde
entonces los tres carriles que escriben con el parser de PLACSP pasan antes por
``python -m db.schema_revision``, el mismo preflight que ``ml-scoring.yml``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

_WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
_PREFLIGHT = "python -m db.schema_revision"


def _steps(nombre: str) -> list[dict[str, Any]]:
    doc = yaml.safe_load((_WORKFLOWS / nombre).read_text(encoding="utf-8"))
    (job,) = doc["jobs"].values()
    steps: list[dict[str, Any]] = job["steps"]
    return steps


def _escribe(step: dict[str, Any]) -> bool:
    run = str(step.get("run", ""))
    return any(m in run for m in ("scraper.", "scheduler.run_update"))


@pytest.mark.parametrize("nombre", ["scrape-daily.yml", "scrape-bulk.yml", "reproceso-lotes.yml"])
def test_el_preflight_va_antes_del_primer_paso_que_escribe(nombre: str) -> None:
    steps = _steps(nombre)
    preflight = next(i for i, s in enumerate(steps) if str(s.get("run", "")).strip() == _PREFLIGHT)
    primero = next(i for i, s in enumerate(steps) if _escribe(s))
    assert preflight < primero


@pytest.mark.parametrize("nombre", ["scrape-daily.yml", "scrape-bulk.yml", "reproceso-lotes.yml"])
def test_ningun_paso_que_escribe_corre_si_el_preflight_falla(nombre: str) -> None:
    """Un ``if:`` con ``!cancelled()`` o ``always()`` corre aunque falle el preflight.

    Con ``if:`` así, el paso tiene que exigir el resultado del preflight; sin
    ``if:``, el ``success()`` implícito ya lo salta.
    """
    for step in _steps(nombre):
        if not _escribe(step):
            continue
        condicion = str(step.get("if", ""))
        if "cancelled()" in condicion or "always()" in condicion:
            assert "steps.schema.outcome == 'success'" in condicion, step["name"]
