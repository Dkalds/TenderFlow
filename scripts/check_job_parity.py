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

- ``actions``  → su ``module`` debe aparecer en algún ``python -m`` de un
  workflow **programado** (con ``schedule:`` y ``cron:``).
- ``manual``   → su ``module`` debe aparecer en un workflow
  ``workflow_dispatch``-only. Es el caso legítimo de "no corre solo, y es
  a propósito": si el workflow desaparece, el job sigue siendo humo y el
  gate lo detecta igual.
- ``pipeline`` → su nombre debe estar cubierto por ``CANONICAL_STEPS``.
- ``loop``     → nada que verificar (solo corre en Docker Compose, y se
  considera una decisión explícita, no un olvido).

Desde S5 comprueba además **la cola de trabajo** (``services/jobs.py``), que es el
otro sitio donde un trabajo puede quedarse sin nadie que lo ejecute:

- Cada tipo de :data:`services.jobs.TIPOS_A_DEMANDA` debe tener su handler
  resoluble (``modulo:funcion``). Un tipo con handler roto se encolaría desde la
  API y giraría hasta agotar intentos, con el usuario mirando un spinner.
- La cola a demanda debe tener **consumidor declarado** en producción: un
  servicio de ``render.yaml`` con ``APP_PROFILE=worker`` o, desde que
  ``tenderflow-worker`` se retiró (2026-10-19), la propia API (ADR-028 §G):
  ``jobs_consumidor_en_api("prod")`` encendido por defecto y ``render.yaml`` sin
  un literal que lo apague. Sin consumidor, la cola no la vacía nadie — que es
  exactamente la clase de «job muerto» que este script existe para detectar.
- Los tipos programados (``TIPOS_PROGRAMADOS``) NO exigen worker: los consume el
  propio job de Actions dentro del cierre de la pasada (ADR-012).

Uso::

    python scripts/check_job_parity.py          # falla con exit 1 si hay huecos
    python scripts/check_job_parity.py --json   # salida legible por máquina
"""

from __future__ import annotations

import json
import os
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
    "watchlist_rules": "watchlist_notify",
}
# `ml_retrain_baja` salió de este mapa en 2026-08 al pasar a plane='actions'
# (`.github/workflows/train-predictivos.yml`): dejarlo apuntando a un paso que
# ya no existe en CANONICAL_STEPS solo serviría para enmascarar un revert.


_SCHEDULE_TRIGGER = re.compile(r"^\s*schedule:\s*$", re.MULTILINE)
_CRON_LINE = re.compile(r"^\s*-\s*cron:", re.MULTILINE)

_RENDER_YAML = _ROOT / "render.yaml"

# `- key: APP_PROFILE` seguido de su `value: worker`. Se busca con una expresión
# y no parseando YAML a propósito: este script corre en el gate y no debe
# depender de que PyYAML esté instalado en el entorno que lo lanza. El par
# key/value de un `envVars` de Render son dos líneas contiguas, así que una
# expresión sobre esas dos líneas es tan fiable como el parseo y no añade
# dependencia.
_APP_PROFILE_WORKER = re.compile(
    r"-\s*key:\s*APP_PROFILE\s*\n\s*value:\s*[\"']?worker[\"']?\s*$",
    re.MULTILINE,
)
# Lo mismo para el interruptor de ADR-028 §G: un `value:` literal que lo apague
# en el Blueprint dejaría la API sin consumir la cola en el siguiente despliegue.
_CONSUMIDOR_API_APAGADO = re.compile(
    r"-\s*key:\s*JOBS_CONSUMIDOR_EN_API\s*\n\s*value:\s*[\"']?(0|false|no|off)[\"']?\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def _modules_invoked_by_workflows() -> tuple[set[str], set[str]]:
    """(módulos en workflows CON schedule, módulos en workflows SIN schedule).

    La distinción importa: un workflow ``workflow_dispatch``-only satisfacía el
    chequeo antiguo aunque nadie lo dispare nunca — exactamente la clase de
    "job muerto en producción" que este script existe para detectar. Un job
    ``plane='actions'`` debe aparecer en un workflow *programado*; uno
    ``plane='manual'``, en uno *sin* schedule, que es donde declara vivir.
    """
    scheduled: set[str] = set()
    dispatch_only: set[str] = set()
    for wf in sorted(_WORKFLOWS_DIR.glob("*.yml")):
        text = wf.read_text(encoding="utf-8")
        found = _PYTHON_M.findall(text)
        if _SCHEDULE_TRIGGER.search(text) and _CRON_LINE.search(text):
            scheduled.update(found)
        else:
            dispatch_only.update(found)
    return scheduled, dispatch_only


def plano_worker_declarado() -> bool:
    """¿Hay en ``render.yaml`` un servicio con ``APP_PROFILE=worker``?

    No se verifica contra la API de Render —este script corre en CI sin
    credenciales—, así que lo que se afirma es que el Blueprint lo declara.
    """
    if not _RENDER_YAML.is_file():
        return False
    return bool(_APP_PROFILE_WORKER.search(_RENDER_YAML.read_text(encoding="utf-8")))


def api_consume_la_cola() -> bool:
    """¿La API de producción consume la cola a demanda? (ADR-028 §G)

    Dos condiciones: el valor por defecto de ``jobs_consumidor_en_api`` en
    ``prod`` —evaluado sin la variable, que es como arranca el servicio si nadie
    la define— y que ``render.yaml`` no la fije a un valor que la apague. Lo que
    el dashboard tenga puesto (``sync: false``) no se ve desde CI; eso lo dice
    el log ``api_consumidor_cola_arrancado`` de cada arranque.
    """
    from unittest.mock import patch

    from config.settings import jobs_consumidor_en_api

    with patch.dict(os.environ):
        os.environ.pop("JOBS_CONSUMIDOR_EN_API", None)
        por_defecto = jobs_consumidor_en_api("prod")
    if not por_defecto:
        return False
    if not _RENDER_YAML.is_file():
        return True
    return not _CONSUMIDOR_API_APAGADO.search(_RENDER_YAML.read_text(encoding="utf-8"))


def consumidor_de_la_cola() -> str:
    """Quién consume la cola a demanda en producción, o ``""`` si nadie."""
    if plano_worker_declarado():
        return "render.yaml (APP_PROFILE=worker)"
    if api_consume_la_cola():
        return "tenderflow-api (ADR-028 §G)"
    return ""


def check_cola() -> tuple[list[dict[str, Any]], list[str]]:
    """Paridad de la cola de trabajo: handler resoluble y consumidor declarado."""
    import importlib

    from services.jobs import TIPOS_A_DEMANDA, TIPOS_PROGRAMADOS

    consumidor = consumidor_de_la_cola()
    rows: list[dict[str, Any]] = []
    problems: list[str] = []

    for tipos, plano, exige_consumidor in (
        (TIPOS_A_DEMANDA, "cola", True),
        (TIPOS_PROGRAMADOS, "pipeline", False),
    ):
        for nombre, declarado in tipos.items():
            modulo_nombre, _, funcion_nombre = declarado.handler.partition(":")
            try:
                modulo = importlib.import_module(modulo_nombre)
            except Exception as exc:  # import roto: el handler no existe de facto
                problems.append(
                    f"{nombre}: el handler '{declarado.handler}' no se pudo importar ({exc})"
                )
            else:
                if not callable(getattr(modulo, funcion_nombre, None)):
                    problems.append(
                        f"{nombre}: el handler '{declarado.handler}' no existe — el job se "
                        "encolaría y giraría hasta agotar intentos"
                    )
            cubierto_por = ""
            if exige_consumidor and not consumidor:
                problems.append(
                    f"{nombre}: tipo a demanda sin consumidor — ningún servicio de "
                    "render.yaml declara APP_PROFILE=worker y la API no consume la "
                    "cola (JOBS_CONSUMIDOR_EN_API), así que en producción nadie la vacía"
                )
            elif exige_consumidor:
                cubierto_por = consumidor
            else:
                cubierto_por = "cierre de la pasada (Actions)"
            rows.append(
                {"job": nombre, "plane": plano, "cubierto_por": cubierto_por, "heavy": False}
            )

    return rows, problems


def check() -> tuple[list[dict[str, Any]], list[str]]:
    """Devuelve (filas de estado, lista de problemas)."""
    from scheduler.jobs import build_default_registry
    from scheduler.pipeline_runs import CANONICAL_STEPS

    scheduled, dispatch_only = _modules_invoked_by_workflows()
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
            elif job.module in dispatch_only:
                problems.append(
                    f"{job.name}: plane='actions' pero `python -m {job.module}` solo "
                    "aparece en workflows workflow_dispatch-only (sin schedule) — "
                    "job muerto salvo disparo manual. Si no correr solo es la "
                    "decisión, declararlo plane='manual'"
                )
            else:
                problems.append(
                    f"{job.name}: plane='actions' pero ningún workflow ejecuta "
                    f"`python -m {job.module}` — job muerto en producción"
                )
        elif job.plane == "manual":
            if not job.module:
                problems.append(f"{job.name}: plane='manual' sin `module` declarado")
            elif job.module in dispatch_only:
                cubierto_por = f"python -m {job.module} (workflow_dispatch)"
            else:
                problems.append(
                    f"{job.name}: plane='manual' pero ningún workflow "
                    f"workflow_dispatch-only ejecuta `python -m {job.module}` — "
                    "no hay forma de dispararlo ni a mano"
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

    # Los tipos de la cola van al final para no desplazar los índices del
    # registry, sobre los que ya hay tests que leen `rows[0]`.
    filas_cola, problemas_cola = check_cola()
    rows.extend(filas_cola)
    problems.extend(problemas_cola)

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
