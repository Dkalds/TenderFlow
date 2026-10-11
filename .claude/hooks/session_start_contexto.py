"""SessionStart: dice con qué entorno arranca la sesión y qué trabajo hay en curso.

Dos cosas que cada sesión redescubría a mano, y a veces mal:

* **El entorno del checkout.** Un worktree nuevo no trae ``.venv``, ``.env`` ni
  ``web/node_modules``; sin saberlo, un agente corre los controles con el
  Python del sistema, carga ``settings`` con ``ENV=prod`` o da la suite por no
  ejecutable cuando la parte sin BD sí corre.
* **El trabajo ajeno.** Con varias sesiones en paralelo, dos acababan haciendo
  el mismo arreglo en ramas distintas. La lista de PR abiertos y de ramas con
  commits recientes cuesta dos comandos, y nadie los lanzaba antes de empezar.

Además siembra el grafo de graphify en un worktree nuevo copiándolo del
checkout principal: ``graphify-out/`` no se versiona, y el hook ``post-checkout``
de graphify solo reconstruye el grafo donde ya existe uno.

Es **best-effort y no bloqueante**, como ``session_start_pg.py``: cada
comprobación tiene su plazo, y un fallo se traduce en una línea menos, nunca en
una sesión que no arranca.
"""

import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

# Raíz por defecto: el checkout que aloja este fichero. `main` la cambia por la
# del `cwd` que manda el cliente, porque en un worktree de Claude Code los
# hooks se lanzan desde el checkout principal y esta sería la de otro árbol.
ROOT = pathlib.Path(__file__).resolve().parents[2]

# Una rama cuenta como «viva» si tiene un commit en este plazo.
HORAS_RAMA_VIVA = 48
MAX_RAMAS = 12
MAX_PRS = 15
# Autores de PR que no son trabajo de una sesión.
BOTS = ("dependabot", "renovate")
ARTEFACTOS_DEL_GRAFO = ("graph.json", "GRAPH_REPORT.md")


def raiz_del_checkout(*pistas: str) -> pathlib.Path:
    """El checkout donde trabaja la sesión, que no siempre aloja este fichero.

    En un worktree de Claude Code los hooks se lanzan desde el checkout
    principal (`$CLAUDE_PROJECT_DIR`), así que la raíz deducida de `__file__`
    es la de otro árbol. Las pistas —el `cwd` que manda el cliente, la ruta que
    se edita— dicen cuál es el de verdad: el primer ancestro con `.git`
    (directorio en el checkout principal, fichero en un worktree).
    """
    for pista in pistas:
        if not pista:
            continue
        inicio = pathlib.Path(pista)
        if not inicio.is_absolute():
            continue
        for candidato in (inicio, *inicio.parents):
            if (candidato / ".git").exists():
                return candidato
    return ROOT


def run(cmd: list[str], timeout: float) -> str:
    """Salida de *cmd*, o cadena vacía si falla, no existe o tarda demasiado."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def checkout_principal() -> pathlib.Path | None:
    """Raíz del checkout principal si este es un worktree enlazado; si no, ``None``."""
    comun = run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], 5)
    if not comun:
        return None
    principal = pathlib.Path(comun).parent
    try:
        if principal.resolve() == ROOT.resolve():
            return None
    except OSError:
        return None
    return principal


def python_del_venv(base: pathlib.Path) -> pathlib.Path | None:
    for rel in (".venv/Scripts/python.exe", ".venv/bin/python"):
        candidato = base / rel
        if candidato.is_file():
            return candidato
    return None


def sembrar_grafo(principal: pathlib.Path | None) -> str:
    """Copia el grafo del checkout principal a un worktree que no tiene ninguno."""
    destino = ROOT / "graphify-out"
    if (destino / "graph.json").is_file():
        return ""
    if principal is None or shutil.which("graphify") is None:
        return ""
    origen = principal / "graphify-out"
    if not (origen / "graph.json").is_file():
        return ""
    destino.mkdir(exist_ok=True)
    for nombre in ARTEFACTOS_DEL_GRAFO:
        if (origen / nombre).is_file():
            shutil.copy2(origen / nombre, destino / nombre)
    return (
        "Grafo: copiado del checkout principal (puede ir unos commits por detrás); "
        "`graphify update .` lo pone al día."
    )


def dependencias_en_el_python_del_sistema() -> bool:
    """¿El Python que lanza el hook ya tiene el proyecto instalado? (sesiones remotas)"""
    return all(importlib.util.find_spec(nombre) is not None for nombre in ("fastapi", "pytest"))


def env_definido() -> bool:
    """¿Alguien fija ``ENV``? Sin ella, ``config.settings`` asume producción."""
    if os.environ.get("ENV"):
        return True
    try:
        lineas = (ROOT / ".env").read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    return any(linea.strip().startswith("ENV=") for linea in lineas)


def entorno(principal: pathlib.Path | None) -> list[str]:
    lineas: list[str] = []
    propio = python_del_venv(ROOT)
    if propio is None:
        heredado = python_del_venv(principal) if principal else None
        if heredado is not None:
            lineas.append(
                f"Python: este checkout no tiene `.venv`; el del checkout principal es "
                f"`{heredado.as_posix()}`. Su `pip install -e` apunta al principal: lanzá los "
                'scripts con `PYTHONPATH="$PWD"` o importarán el código de allí. Puede ir '
                "desfasado respecto al lock (un rojo en un módulo que no tocaste suele ser eso)."
            )
        elif not dependencias_en_el_python_del_sistema():
            lineas.append(
                "Python: no hay `.venv` y a este Python le faltan las dependencias: "
                "`pip install -r requirements.txt -r requirements-dev.txt` y "
                '`pip install -e ".[pliegos]"` antes de lint, typecheck o tests.'
            )
    if not env_definido():
        lineas.append(
            "`ENV` no está definida (ni en el entorno ni en `.env`), así que `config.settings` "
            "arranca en `prod` y aborta pidiendo `SIGNING_KEY`. Prefijá `ENV=dev` (lo que usa "
            "CI) en tests y scripts."
        )
    if (ROOT / "web/package.json").is_file() and not (ROOT / "web/node_modules").is_dir():
        lineas.append(
            "Frontend: falta `web/node_modules`; `npm ci` en `web/` antes de lint o tests."
        )
    if (ROOT / "scripts/dev/wsl_run.sh").is_file() and shutil.which("wsl.exe"):
        lineas.append(
            "WSL: `bash scripts/dev/wsl_run.sh <comando>` ejecuta con los pines del lock y "
            "Postgres de tests (p. ej. `bash scripts/dev/wsl_run.sh make check`)."
        )
    return lineas


def prs_abiertos() -> list[str] | None:
    """Los PR abiertos que no son de un bot. ``None`` si no se pudo consultar."""
    if shutil.which("gh") is None:
        return None
    crudo = run(
        [
            "gh",
            "pr",
            "list",
            "--state",
            "open",
            "--limit",
            "40",
            "--json",
            "number,title,headRefName,author",
        ],
        8,
    )
    if not crudo:
        return None
    try:
        prs = json.loads(crudo)
    except json.JSONDecodeError:
        return None
    lineas = []
    for pr in prs:
        autor = str((pr.get("author") or {}).get("login") or "")
        rama = str(pr.get("headRefName") or "")
        if any(bot in autor or rama.startswith(bot) for bot in BOTS):
            continue
        lineas.append(f"#{pr.get('number')} {pr.get('title')} ({rama})")
    return lineas[:MAX_PRS]


def ramas_vivas() -> list[str]:
    """Ramas locales, salvo la actual, con un commit dentro del plazo."""
    actual = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], 5)
    # `--no-merged`: fuera las ramas cuya punta ya está en master (recién creadas
    # o fusionadas sin squash); su último commit es de master, no trabajo propio.
    hay_origen = run(["git", "rev-parse", "--verify", "-q", "origin/master"], 5)
    base = "origin/master" if hay_origen else "HEAD"
    crudo = run(
        [
            "git",
            "for-each-ref",
            "--sort=-committerdate",
            f"--no-merged={base}",
            "--format=%(refname:short)\t%(committerdate:unix)\t%(subject)",
            "refs/heads",
        ],
        8,
    )
    limite = time.time() - HORAS_RAMA_VIVA * 3600
    lineas = []
    for fila in crudo.splitlines():
        partes = fila.split("\t", 2)
        if len(partes) != 3 or not partes[1].isdigit():
            continue
        rama, fecha, asunto = partes
        if rama in (actual, "master", "main") or int(fecha) < limite:
            continue
        lineas.append(f"{rama}: {asunto[:90]}")
    return lineas[:MAX_RAMAS]


def trabajo_en_curso() -> list[str]:
    lineas: list[str] = []
    prs = prs_abiertos()
    if prs is None:
        lineas.append("PR abiertos: no se pudieron consultar (`gh pr list` antes de empezar).")
    elif prs:
        lineas.append("PR abiertos: " + "; ".join(prs) + ".")
    ramas = ramas_vivas()
    if ramas:
        lineas.append(
            f"Ramas con commits en las últimas {HORAS_RAMA_VIVA} h: " + "; ".join(ramas) + "."
        )
    if lineas:
        lineas.append(
            "Si tu tarea toca lo mismo que alguno de esos, decíselo al usuario antes de empezar."
        )
    return lineas


def emit(message: str) -> None:
    """Devuelve contexto al agente por el protocolo de hooks."""
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": message,
                }
            }
        )
    )


def main() -> None:
    global ROOT
    try:
        entrada = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except ValueError:
        entrada = {}
    ROOT = raiz_del_checkout(str(entrada.get("cwd") or ""))
    principal = checkout_principal()
    bloques: list[str] = []
    lineas = entorno(principal)
    grafo = sembrar_grafo(principal)
    if grafo:
        lineas.append(grafo)
    if lineas:
        bloques.append("Entorno de este checkout:\n" + "\n".join(f"- {x}" for x in lineas))
    lineas = trabajo_en_curso()
    if lineas:
        bloques.append(
            "Trabajo en curso (para no duplicar):\n" + "\n".join(f"- {x}" for x in lineas)
        )
    if bloques:
        emit("\n\n".join(bloques))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # un hook nunca debe romper el arranque de la sesión
        pass
