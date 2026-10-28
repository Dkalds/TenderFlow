#!/usr/bin/env python3
"""Corre los gates y ratchets de ``scripts/check_*.py`` en un solo paso.

Había una veintena de gates repartidos entre pasos de ``ci.yml``, targets
sueltos del Makefile y tests ``tests/test_unit_ratchet_*.py``, y la lista de
qué corre dónde no estaba escrita en ningún sitio. Esta es esa lista: cada
``scripts/check_*.py`` aparece en exactamente uno de tres grupos, y
``tests/test_unit_run_gates.py`` falla si aparece un script nuevo sin
clasificar.

* ``STDLIB`` — solo biblioteca estándar (y ``git``): corre en cualquier
  checkout, sin ``.venv``. Es ``make gates``.
* ``DEPS`` — importan la app o el scheduler: necesitan las dependencias del
  proyecto, no Postgres. Es ``make gates-deps``.
* ``FUERA`` — no se corren aquí, cada uno con su motivo (necesitan un artefacto
  de otro paso, la red o la base de datos).

No es fail-fast: corre todos los del grupo, en orden, y al final resume cuáles
fallaron; sale con 1 si alguno falló. La salida de cada gate se ve tal cual.

Uso::

    python scripts/run_gates.py              # grupo stdlib (make gates)
    python scripts/run_gates.py --deps       # grupo deps (make gates-deps)
    python scripts/run_gates.py --list       # tabla de los tres grupos (markdown)
"""

from __future__ import annotations

import argparse
import io
import os
import subprocess  # nosec B404 -- argv fijo de scripts del repo, sin shell
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

#: Se sustituye por un fichero temporal donde ``export_openapi.py`` deja el
#: esquema para los dos gates de contrato que lo leen.
OPENAPI = "{openapi}"

_DEV = {"ENV": "dev"}
_DEV_API = {"ENV": "dev", "APP_PROFILE": "api"}


@dataclass(frozen=True)
class Gate:
    """Un paso: el script, sus argumentos y el entorno que añade."""

    script: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    que: str = ""

    @property
    def nombre(self) -> str:
        return " ".join((self.script, *self.args))


# Orden: primero los de arquitectura del código Python, luego frontend, luego
# documentación y configuración; `check_agent_docs` el último porque es el más
# lento y el que más ruido da al fallar.
STDLIB: tuple[Gate, ...] = (
    Gate("check_layers.py", que="imports hacia abajo entre capas (ratchet)"),
    Gate("check_prints.py", que="ningún `print()` fuera de un `__main__`"),
    Gate("check_any_count.py", que="usos de Any en producción (ratchet)"),
    Gate("check_user_key_ratchet.py", que="identidad derivada del correo (ratchet, ADR-030)"),
    Gate("check_analytics_unbounded.py", que="analítica sin cota (ADR-023)"),
    Gate("check_public_surface.py", ("--strict",), que="superficie anónima sin NIF ni analítica"),
    Gate("check_frontend_invariants.py", ("--strict",), que="integridad analítica (ADR-014)"),
    Gate("check_inline_styles.py", que="estilos inline del frontend (ratchet)"),
    Gate("check_title_attrs.py", que="title nativo en el frontend (ratchet)"),
    Gate("check_ortografia_ui.py", que="tildes del copy de la UI"),
    Gate("check_casos_uso.py", que="cada caso de uso tiene recorrido"),
    Gate("check_env_parity.py", env=_DEV, que="settings ↔ render.yaml ↔ .env.example"),
    Gate("check_requirements_sync.py", que="requirements.txt cubre requirements.in"),
    Gate("check_backlog_freshness.py", que="frescura del backlog (informe)"),
    Gate("check_agent_docs.py", que="instrucciones, skills, commands y hooks"),
)

DEPS: tuple[Gate, ...] = (
    Gate("check_job_parity.py", env=_DEV, que="todo job tiene plano (ADR-012)"),
    Gate("check_api_surface.py", env=_DEV_API, que="operación nueva con motivo (AGENTS.md §0)"),
    Gate("check_api_convencion.py", env=_DEV_API, que="paginación y errores (ratchet)"),
    Gate("export_openapi.py", (OPENAPI,), env=_DEV, que="exporta el esquema de los dos siguientes"),
    Gate("check_openapi_contract.py", ("--spec", OPENAPI), que="respuestas opacas (ratchet)"),
    Gate("check_contract_fixtures.py", ("--openapi", OPENAPI), que="fixtures del frontend"),
)

#: Gates que este runner no ejecuta, y por qué. El sitio donde sí corren es su
#: paso de ``ci.yml`` o su target del Makefile.
FUERA: dict[str, str] = {
    "check_api_breaking.py": "compara el OpenAPI de la base con el de la PR (api-contract-compat)",
    "check_bundle_budget.py": "necesita el build de producción de web/ (job frontend)",
    "check_coverage_per_module.py": "necesita coverage.xml de la suite (job test)",
    "check_follows_paridad.py": "mide contra una base de datos real; es un informe, no un gate",
    "check_npm_audit.py": "necesita npm y la red (job audit)",
    "check_security_alerts.py": "consulta la API de GitHub; informe",
}


def _argv(gate: Gate, openapi: Path) -> list[str]:
    args = [str(openapi) if a == OPENAPI else a for a in gate.args]
    return [sys.executable, str(_ROOT / "scripts" / gate.script), *args]


def correr(gates: tuple[Gate, ...]) -> list[tuple[Gate, int, float]]:
    """Ejecuta cada gate en orden, sin cortar en el primer fallo."""
    resultados: list[tuple[Gate, int, float]] = []
    # Este checkout delante en PYTHONPATH: en un worktree, el `pip install -e .`
    # del .venv compartido apunta al checkout principal, y un gate de DEPS
    # importaría su `services/` en vez del que se está comprobando.
    pythonpath = os.pathsep.join(filter(None, (str(_ROOT), os.environ.get("PYTHONPATH"))))
    with tempfile.TemporaryDirectory(prefix="tenderflow-gates-") as tmp:
        openapi = Path(tmp) / "openapi.json"
        for gate in gates:
            print(f"\n── {gate.nombre}", flush=True)
            inicio = time.monotonic()
            proceso = subprocess.run(  # nosec B603 -- argv fijo, sin shell
                _argv(gate, openapi),
                cwd=_ROOT,
                env={**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": pythonpath, **gate.env},
                check=False,
            )
            resultados.append((gate, proceso.returncode, time.monotonic() - inicio))
    return resultados


def resumen(resultados: list[tuple[Gate, int, float]]) -> int:
    fallidos = [(g, rc) for g, rc, _ in resultados if rc != 0]
    print("\n── Resumen")
    for gate, rc, segundos in resultados:
        estado = "OK   " if rc == 0 else f"FALLA (exit {rc})"
        print(f"  {estado}  {gate.nombre}  [{segundos:.1f}s]")
    if fallidos:
        print(f"\n{len(fallidos)} de {len(resultados)} gates fallaron.", file=sys.stderr)
        return 1
    print(f"\n{len(resultados)} gates en verde.")
    return 0


def tabla() -> str:
    """Los tres grupos en markdown, para el playbook."""
    filas = ["| Grupo | Script | Qué comprueba |", "|---|---|---|"]
    for grupo, gates in (("`make gates`", STDLIB), ("`make gates-deps`", DEPS)):
        filas += [f"| {grupo} | `{g.nombre}` | {g.que} |" for g in gates]
    filas += [f"| fuera | `{script}` | {motivo} |" for script, motivo in sorted(FUERA.items())]
    return "\n".join(filas)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deps", action="store_true", help="corre el grupo que importa la app")
    parser.add_argument("--list", action="store_true", help="imprime la tabla de grupos y sale")
    args = parser.parse_args(argv)
    # En Windows sin PYTHONUTF8 la consola es cp1252 y no sabe pintar «──» ni «↔».
    for flujo in (sys.stdout, sys.stderr):
        if isinstance(flujo, io.TextIOWrapper):
            flujo.reconfigure(encoding="utf-8")

    if args.list:
        print(tabla())
        return 0
    return resumen(correr(DEPS if args.deps else STDLIB))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
