#!/usr/bin/env python3
"""Ratchet: ningún ``print()`` en código de producción fuera de un ``__main__``.

``scraper/``, ``services/`` y ``scheduler/`` escriben por ``structlog``
(``observability.logging.get_logger``): el log lleva nivel, contexto del run y
formato JSON en producción, y es lo que se lee en los runners de Actions. Un
``print()`` ahí se salta todo eso —sin nivel, sin ``run_id``, mezclado con la
salida de un CLI— y se acumularon 58 (medido el 2026-10-17): treinta del CLI que
vivía dentro de ``services/ml/sap_classifier.py`` y el resto en conectores que
ya tenían ``structlog`` al lado.

Qué cuenta
----------

* Toda llamada a ``print`` (el builtin, por nombre) en los ``.py`` versionados
  de ``PAQUETES``.
* Salvo dentro de un bloque ``if __name__ == "__main__":`` —el cuerpo de un
  programa, donde ``stdout`` es su interfaz—. Una función ``main()`` que se
  llama desde ese bloque **sí** cuenta: es importable, y quien la importa no
  espera que escriba por ``stdout``. Un CLI con salida para personas vive en
  ``scripts/`` (``scripts/ml_clasificadores.py``).

La lista ``CONGELADAS`` está vacía y solo puede seguir así: no hay deuda que
congelar. Si un día hace falta una excepción, va con su motivo, y una entrada
que ya no corresponde a nada también falla.

Uso::

    python scripts/check_prints.py           # falla ante un print() fuera de __main__
    python scripts/check_prints.py --list    # imprime los que hay hoy
"""

from __future__ import annotations

import argparse
import ast
import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

#: Paquetes vigilados.
PAQUETES: tuple[str, ...] = ("scraper", "services", "scheduler")

#: ``"fichero:línea"`` permitidos. Vacía a propósito (ver docstring).
CONGELADAS: frozenset[str] = frozenset()


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


def _es_bloque_main(nodo: ast.AST) -> bool:
    """``if __name__ == "__main__":`` (en cualquiera de los dos órdenes)."""
    if not isinstance(nodo, ast.If) or not isinstance(nodo.test, ast.Compare):
        return False
    test = nodo.test
    if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
        return False
    lados = [test.left, *test.comparators]
    nombres = {lado.id for lado in lados if isinstance(lado, ast.Name)}
    literales = {
        lado.value
        for lado in lados
        if isinstance(lado, ast.Constant) and isinstance(lado.value, str)
    }
    return nombres == {"__name__"} and literales == {"__main__"}


def prints_de(fuente: str, ruta: str) -> list[str]:
    """Los ``print()`` de ``fuente`` fuera de un bloque ``__main__``, como ``ruta:línea``."""
    arbol = ast.parse(fuente, filename=ruta)
    encontrados: list[str] = []

    def _visitar(nodo: ast.AST) -> None:
        if isinstance(nodo, ast.If) and _es_bloque_main(nodo):
            # El ``else`` de un ``if __name__ == "__main__"`` es código de
            # importación: ese sí se vigila.
            for sentencia in nodo.orelse:
                _visitar(sentencia)
            return
        if (
            isinstance(nodo, ast.Call)
            and isinstance(nodo.func, ast.Name)
            and nodo.func.id == "print"
        ):
            encontrados.append(f"{ruta}:{nodo.lineno}")
        for hijo in ast.iter_child_nodes(nodo):
            _visitar(hijo)

    _visitar(arbol)
    return encontrados


def encontrar() -> list[str]:
    hallados: list[str] = []
    for ruta in _ficheros():
        fuente = (_ROOT / ruta).read_text(encoding="utf-8")
        hallados.extend(prints_de(fuente, ruta))
    return hallados


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--list", action="store_true", help="imprime los print() de hoy")
    args = parser.parse_args(argv)

    hallados = encontrar()
    if args.list:
        for h in hallados:
            print(h)
        return 0

    nuevos = sorted(set(hallados) - CONGELADAS)
    fosiles = sorted(CONGELADAS - set(hallados))
    if nuevos:
        print(
            f'{len(nuevos)} print() fuera de un bloque `if __name__ == "__main__"` en '
            f"{', '.join(PAQUETES)}. Usá `observability.logging.get_logger(__name__)`, "
            "o mové el CLI a scripts/:",
            file=sys.stderr,
        )
        for n in nuevos:
            print(f"  - {n}", file=sys.stderr)
    if fosiles:
        print(
            "Entrada(s) de CONGELADAS que ya no corresponden a un print(): borralas.",
            file=sys.stderr,
        )
        for f in fosiles:
            print(f"  - {f}", file=sys.stderr)
    if nuevos or fosiles:
        return 1
    print(f"Ratchet de print() OK: ninguno fuera de __main__ en {', '.join(PAQUETES)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
