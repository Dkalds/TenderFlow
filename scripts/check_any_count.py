#!/usr/bin/env python3
"""Ratchet: el número de ``Any`` en código de producción no sube.

mypy corre en modo ``strict`` sobre todo el árbol, pero ``strict`` no impide
escribir ``Any``: un ``dict[str, Any]`` pasa el gate y desactiva la
comprobación de cada acceso que lo atraviese. Medido el 2026-10-17 había 2.113
líneas con ``Any`` en producción, casi todas filas de repositorio devueltas
como ``dict[str, Any]`` que la ruta volvía a tipar a mano al construir el DTO
(ítem del backlog «strict con 2.113 Any»). Este gate no obliga a quitarlas de
golpe; impide que crezcan mientras se van tipando.

Qué cuenta
----------

* Cada uso de ``Any`` como nombre (``Any``) o atributo (``typing.Any``) en el
  AST de los ``.py`` versionados de ``PAQUETES`` —las capas de AGENTS.md §2—.
  Una mención en un comentario o docstring no cuenta: el comentario que
  justifica un ``Any`` es justo lo que se pide, y no tiene que pesar en contra.
* El ``import`` no cuenta (no es un uso), ni ``tests/`` ni ``scripts/``, que
  tienen su propio override en ``pyproject.toml``.

``LIMITE`` es la cifra congelada. Si el conteo la supera, falla. Si queda por
debajo, avisa para que el mismo PR la baje: un ratchet que no se aprieta deja
de medir nada.

Uso::

    python scripts/check_any_count.py           # falla si el conteo supera LIMITE
    python scripts/check_any_count.py --list    # conteo por fichero, de más a menos
"""

from __future__ import annotations

import argparse
import ast
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

#: Paquetes de producción (las capas de AGENTS.md §2).
PAQUETES: tuple[str, ...] = (
    "config",
    "observability",
    "shared",
    "llm",
    "db",
    "services",
    "scraper",
    "scheduler",
    "api",
    "mcp_server",
)

#: Usos de ``Any`` congelados. Solo baja: al tipar, actualizalo en el mismo PR.
LIMITE = 2163


def _ficheros() -> list[str]:
    """Ficheros ``.py`` versionados (o nuevos sin ignorar) de ``PAQUETES``."""
    git = shutil.which("git")
    if git is None:  # pragma: no cover - CI y pre-commit siempre lo tienen
        raise RuntimeError("Este gate necesita git en el PATH para enumerar el repo.")
    # argv fijo, sin shell: mismo criterio que scripts/check_layers.py.
    salida = subprocess.run(
        [git, "ls-files", "--cached", "--others", "--exclude-standard", "--", *PAQUETES],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(
        linea.strip()
        for linea in salida.splitlines()
        if linea.strip().endswith(".py") and (_ROOT / linea.strip()).is_file()
    )


def usos_de_any(fuente: str, ruta: str = "<fuente>") -> int:
    """Usos de ``Any`` (nombre o atributo) en el AST de ``fuente``."""
    arbol = ast.parse(fuente, filename=ruta)
    return sum(
        1
        for nodo in ast.walk(arbol)
        if (isinstance(nodo, ast.Name) and nodo.id == "Any")
        or (isinstance(nodo, ast.Attribute) and nodo.attr == "Any")
    )


def conteo_por_fichero() -> Counter[str]:
    conteo: Counter[str] = Counter()
    for ruta in _ficheros():
        n = usos_de_any((_ROOT / ruta).read_text(encoding="utf-8"), ruta)
        if n:
            conteo[ruta] = n
    return conteo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--list", action="store_true", help="conteo por fichero")
    args = parser.parse_args(argv)

    conteo = conteo_por_fichero()
    total = sum(conteo.values())
    if args.list:
        for ruta, n in conteo.most_common():
            print(f"{n:5d}  {ruta}")
        print(f"{total:5d}  TOTAL (límite {LIMITE})")
        return 0

    if total > LIMITE:
        print(
            f"{total} usos de `Any` en producción, por encima del límite congelado "
            f"({LIMITE}). Tipá la forma (TypedDict, dataclass, DTO) en vez de añadir "
            "`Any`; `python scripts/check_any_count.py --list` da el reparto por fichero.",
            file=sys.stderr,
        )
        return 1
    if total < LIMITE:
        print(
            f"Ratchet de Any OK: {total} usos (límite {LIMITE}). Bajó: actualizá "
            f"LIMITE a {total} en scripts/check_any_count.py en este mismo PR."
        )
        return 0
    print(f"Ratchet de Any OK: {total} usos (límite {LIMITE}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
