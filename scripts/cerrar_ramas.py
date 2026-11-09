"""Inventario y limpieza de worktrees y ramas locales cuyo trabajo ya está en master.

Cada sesión de agente abre un worktree y una rama `agente/*`, pero nada los
cierra tras el merge: el 2026-11-09 había 96 worktrees y 141 ramas locales, y
``session_start_contexto.py`` anunciaba como «trabajo en curso» ramas ya
mergeadas. ``git branch --merged`` no sirve aquí porque los PR se integran
con squash: la rama nunca es ancestro de master. Por eso se cruza con los PR
de GitHub (``gh``): una rama está integrada si su punta es ancestro de la
cabeza de un PR mergeado **en master** con ese nombre, o —solo si no tiene
worktree— de ``origin/master``. Un worktree sin commits propios puede ser una
sesión recién abierta: se informa aparte y no se toca.

Sin argumentos solo lista, y guarda lo listado como integrado en
``<git-common-dir>/cerrar-ramas.json``. Con ``--borrar`` quita solo lo que esa
lista aprobó y sigue integrado, sin ``--force``: un worktree con cambios o
ficheros sin seguir se conserva, pero los **ignorados** (``.env*``, ``data/*``,
``node_modules``) se van con él. Borrar ramas requiere OK del usuario
(AGENTS.md §6); el comando ``/cerrar`` lo pide entre las dos pasadas. Las
ramas remotas no se tocan.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

INTEGRADA = "integrada"
SUCIA = "integrada, pero con cambios sin commitear"
SIN_COMMITS = "worktree sin commits propios (¿sesión recién abierta?)"
POSTERIOR = "PR mergeado, pero con commits locales posteriores"
ABIERTO = "PR abierto"
CERRADO = "PR cerrado sin merge"
SIN_PR = "sin PR y fuera de master"
ORDEN = (INTEGRADA, SUCIA, SIN_COMMITS, POSTERIOR, ABIERTO, CERRADO, SIN_PR)


@dataclass(frozen=True)
class Rama:
    nombre: str | None  # None: worktree en HEAD separado
    punta: str
    worktree: Path | None


@dataclass(frozen=True)
class PR:
    numero: int
    estado: str  # MERGED, CLOSED u OPEN, como lo da `gh`
    cabeza: str
    base: str


def git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],  # noqa: S607 -- git del PATH, argumentos fijos
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def leer_worktrees(porcelain: str) -> list[Rama]:
    """Los worktrees de `git worktree list --porcelain`, sin el principal."""
    ramas: list[Rama] = []
    for bloque in porcelain.strip().split("\n\n")[1:]:
        campos = dict(linea.partition(" ")[::2] for linea in bloque.splitlines())
        if "prunable" in campos:  # su carpeta ya no existe: lo limpia `git worktree prune`
            continue
        rama = campos.get("branch", "").removeprefix("refs/heads/") or None
        ramas.append(Rama(rama, campos.get("HEAD", ""), Path(campos["worktree"])))
    return ramas


def clasificar(
    rama: Rama,
    prs: list[PR],
    contenida_en: Callable[[str, str], bool],
    sucia: Callable[[Rama], bool],
) -> str:
    """El estado de una rama. ``contenida_en(a, b)``: a es ancestro de b (o b misma)."""
    por_pr = any(
        pr.estado == "MERGED" and pr.base == "master" and contenida_en(rama.punta, pr.cabeza)
        for pr in prs
    )
    if por_pr or contenida_en(rama.punta, "origin/master"):
        if rama.worktree and sucia(rama):
            return SUCIA
        return INTEGRADA if por_pr or not rama.worktree else SIN_COMMITS
    estados = {pr.estado for pr in prs}
    if "OPEN" in estados:
        return ABIERTO
    if "MERGED" in estados:
        return POSTERIOR
    if "CLOSED" in estados:
        return CERRADO
    return SIN_PR


def prs_por_rama() -> dict[str, list[PR]]:
    r = subprocess.run(
        [  # noqa: S607 -- gh del PATH, argumentos fijos
            "gh",
            "pr",
            "list",
            "--state",
            "all",
            "--limit",
            "5000",
            "--json",
            "number,state,headRefName,headRefOid,baseRefName",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if r.returncode != 0:
        print(
            f"aviso: `gh pr list` falló ({r.stderr.strip()}); solo cuenta lo que ya es ancestro de master",
            file=sys.stderr,
        )
        return {}
    prs: dict[str, list[PR]] = {}
    for pr in json.loads(r.stdout):
        prs.setdefault(pr["headRefName"], []).append(
            PR(pr["number"], pr["state"], pr["headRefOid"], pr["baseRefName"])
        )
    return prs


def inventario(raiz: Path) -> dict[str, list[Rama]]:
    git("fetch", "origin", "master", "--quiet", cwd=raiz)
    porcelain = git("worktree", "list", "--porcelain", cwd=raiz).stdout
    principal = Path(porcelain.split("\n", 1)[0].removeprefix("worktree "))
    actual = git("rev-parse", "--show-toplevel", cwd=raiz).stdout.strip()
    en_principal = git("branch", "--show-current", cwd=principal).stdout.strip()

    ramas = [
        w
        for w in leer_worktrees(porcelain)
        if w.worktree and w.worktree.resolve() != Path(actual).resolve()
    ]
    con_worktree = {w.nombre for w in ramas} | {
        git("branch", "--show-current", cwd=Path(actual)).stdout.strip()
    }
    for linea in git(
        "for-each-ref", "refs/heads", "--format=%(refname:short) %(objectname)", cwd=raiz
    ).stdout.splitlines():
        nombre, punta = linea.split(" ")
        if nombre not in con_worktree and nombre not in {"master", en_principal}:
            ramas.append(Rama(nombre, punta, None))

    prs = prs_por_rama()

    def contenida_en(a: str, b: str) -> bool:
        return git("merge-base", "--is-ancestor", a, b, cwd=raiz).returncode == 0

    def sucia(rama: Rama) -> bool:
        r = git("status", "--porcelain", cwd=rama.worktree)
        return r.returncode != 0 or bool(r.stdout.strip())

    grupos: dict[str, list[Rama]] = {estado: [] for estado in ORDEN}
    for rama in ramas:
        grupos[clasificar(rama, prs.get(rama.nombre or "", []), contenida_en, sucia)].append(rama)
    return grupos


def clave(rama: Rama) -> str:
    return f"{rama.nombre or ''}|{rama.worktree or ''}"


def aprobadas(integradas: list[Rama], listadas: set[str]) -> list[Rama]:
    """Lo que se puede borrar: integrado ahora y ya mostrado al usuario en la pasada anterior."""
    return [rama for rama in integradas if clave(rama) in listadas]


def borrar(raiz: Path, ramas: list[Rama]) -> int:
    fallos = 0
    for rama in ramas:
        if rama.worktree:
            # Sin longpaths, Windows no borra los node_modules hondos («Filename too long»).
            r = git("-c", "core.longpaths=true", "worktree", "remove", str(rama.worktree), cwd=raiz)
            if r.returncode != 0:
                fallos += 1
                print(f"  no se pudo quitar {rama.worktree}: {r.stderr.strip()}")
                continue
        if rama.nombre:
            r = git("branch", "-D", rama.nombre, cwd=raiz)
            if r.returncode != 0:
                fallos += 1
                print(f"  no se pudo borrar {rama.nombre}: {r.stderr.strip()}")
    git("worktree", "prune", cwd=raiz)
    return fallos


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0] if __doc__ else None)
    parser.add_argument(
        "--borrar", action="store_true", help="quita los worktrees y ramas integrados y limpios"
    )
    args = parser.parse_args(argv)
    raiz = Path.cwd()
    lista = (
        raiz / git("rev-parse", "--git-common-dir", cwd=raiz).stdout.strip() / "cerrar-ramas.json"
    )

    grupos = inventario(raiz)
    for estado in ORDEN:
        print(f"\n## {estado} ({len(grupos[estado])})")
        for rama in grupos[estado]:
            donde = f"  [{rama.worktree}]" if rama.worktree else ""
            print(f"- {rama.nombre or '(HEAD separado ' + rama.punta[:8] + ')'}{donde}")

    if not args.borrar:
        lista.write_text(json.dumps([clave(r) for r in grupos[INTEGRADA]]), encoding="utf-8")
        print(f"\n{len(grupos[INTEGRADA])} se pueden borrar. Repetí con --borrar para quitarlas.")
        return 0
    if not lista.exists():
        print("\nFalta el inventario aprobado: corré primero sin --borrar.")
        return 2
    objetivo = aprobadas(grupos[INTEGRADA], set(json.loads(lista.read_text(encoding="utf-8"))))
    nuevas = len(grupos[INTEGRADA]) - len(objetivo)
    fallos = borrar(raiz, objetivo)
    lista.unlink()
    print(f"\nBorradas {len(objetivo) - fallos} de {len(objetivo)} aprobadas.")
    if nuevas:
        print(f"{nuevas} integradas que no estaban en el inventario aprobado se dejaron.")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
