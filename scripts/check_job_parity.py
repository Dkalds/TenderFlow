#!/usr/bin/env python3
"""Verifica que todo job del registry tiene un plano de ejecución real (ADR-012).

ADR-012 declara "un solo plano de orquestación por entorno", pero era una
afirmación documental sin verificación. El resultado fue que varios jobs
(``digest_daily``, ``retention_cleanup``, ``drift_report``, ``ml_retrain_baja``)
vivían solo en el registry del plano APScheduler —que no es el plano activo en
producción— y por tanto **nunca se ejecutaban**. El caso de ``digest_daily`` era
además un bug visible: quien elegía digest diario o semanal no recibía email.

Este script convierte esa afirmación en invariante verificado. Por cada job de
``build_default_registry()`` comprueba, según su ``plane``:

- ``actions``  → su ``module`` debe aparecer en algún ``python -m`` de
  ``.github/workflows/*.yml``.
- ``pipeline`` → su nombre debe estar cubierto por ``CANONICAL_STEPS``.
- ``loop``     → nada que verificar (solo corre en Docker Compose, y se
  considera una decisión explícita, no un olvido).

Uso::

    python scripts/check_job_parity.py          # falla con exit 1 si hay huecos
    python scripts/check_job_parity.py --json   # salida para docs/_Dashboard.md
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOWS_DIR = _ROOT / ".github" / "workflows"

# `python -m paquete.modulo` dentro de un `run:` de workflow.
_PYTHON_M = re.compile(r"python\s+-m\s+([\w.]+)")

# Jobs del registry cuyo trabajo lo hace un paso de la pipeline canónica con
# otro nombre. Mapea nombre-de-job → nombre-de-paso, para no exigir que ambos
# vocabularios coincidan literalmente.
_ALIAS_PIPELINE: dict[str, str] = {
    "digest_daily": "digests",
    "drift_report": "drift_checks",
    "ml_retrain_baja": "ml_retrain",
    "watchlist_rules": "watchlist_notify",
}


_SCHEDULE_TRIGGER = re.compile(r"^\s*schedule:\s*$", re.MULTILINE)
_CRON_LINE = re.compile(r"^\s*-\s*cron:", re.MULTILINE)


def _modules_invoked_by_workflows() -> tuple[set[str], set[str]]:
    """(módulos en workflows CON schedule, módulos en cualquier workflow).

    La distinción importa: un workflow ``workflow_dispatch``-only satisfacía el
    chequeo antiguo aunque nadie lo dispare nunca — exactamente la clase de
    "job muerto en producción" que este script existe para detectar. Un job
    ``plane='actions'`` debe aparecer en un workflow *programado*.
    """
    scheduled: set[str] = set()
    anywhere: set[str] = set()
    for wf in sorted(_WORKFLOWS_DIR.glob("*.yml")):
        text = wf.read_text(encoding="utf-8")
        found = _PYTHON_M.findall(text)
        anywhere.update(found)
        if _SCHEDULE_TRIGGER.search(text) and _CRON_LINE.search(text):
            scheduled.update(found)
    return scheduled, anywhere


def check() -> tuple[list[dict[str, Any]], list[str]]:
    """Devuelve (filas de estado, lista de problemas)."""
    from scheduler.jobs import build_default_registry
    from scheduler.pipeline_runs import CANONICAL_STEPS

    scheduled, anywhere = _modules_invoked_by_workflows()
    steps = set(CANONICAL_STEPS)

    rows: list[dict[str, Any]] = []
    problems: list[str] = []

    for job in build_default_registry():
        cubierto_por = ""
        if job.plane == "actions":
            if not job.module:
                problems.append(f"{job.name}: plane='actions' sin `module` declarado")
            elif job.module in scheduled:
                cubierto_por = f"python -m {job.module}"
            elif job.module in anywhere:
                problems.append(
                    f"{job.name}: plane='actions' pero `python -m {job.module}` solo "
                    "aparece en workflows workflow_dispatch-only (sin schedule) — "
                    "job muerto salvo disparo manual"
                )
            else:
                problems.append(
                    f"{job.name}: plane='actions' pero ningún workflow ejecuta "
                    f"`python -m {job.module}` — job muerto en producción"
                )
        elif job.plane == "pipeline":
            step = _ALIAS_PIPELINE.get(job.name, job.name)
            if step not in steps:
                problems.append(
                    f"{job.name}: plane='pipeline' pero '{step}' no está en "
                    f"CANONICAL_STEPS — job muerto en producción"
                )
            else:
                cubierto_por = f"CANONICAL_STEPS[{step}]"
        else:  # loop
            cubierto_por = "solo docker-compose (decisión explícita)"

        rows.append(
            {
                "job": job.name,
                "plane": job.plane,
                "cubierto_por": cubierto_por,
                "heavy": job.heavy,
            }
        )

    return rows, problems


def main(argv: list[str]) -> int:
    rows, problems = check()

    if "--json" in argv:
        print(json.dumps({"jobs": rows, "problems": problems}, indent=2, ensure_ascii=False))
        return 1 if problems else 0

    width = max(len(r["job"]) for r in rows)
    for r in rows:
        print(f"  {r['job']:<{width}}  {r['plane']:<9}  {r['cubierto_por']}")

    if problems:
        print(f"\n{len(problems)} job(s) sin plano de ejecución real:", file=sys.stderr)
        for p in problems:
            print(f"  ✗ {p}", file=sys.stderr)
        return 1

    print(f"\n{len(rows)} jobs, todos con plano de ejecución verificado.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
