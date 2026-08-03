"""Mutation testing por muestreo: ¿los tests fallan cuando el código se rompe?

Por qué
-------
El porcentaje de cobertura mide qué líneas se ejecutan, no si alguna aserción
las vigila. Un test que llama a una función y comprueba que "no lanza" cubre
sus líneas y no detecta ninguna regresión. El repo ya tiene casos documentados
(``tests/test_TODO_review_tautologico.py``) y el propio corpus golden del
parser nació de descubrir, mutando el código a mano, que invertir la prioridad
de dos periodos no rompía ningún test.

mutmut altera el código (cambia operadores, constantes, condiciones) y vuelve a
ejecutar los tests. Un mutante **muerto** es un test que hizo su trabajo; un
mutante **superviviente** es código que puede romperse sin que nadie se entere.

Por qué muestreado
------------------
Mutar todo el proyecto con la suite completa es inviable: cada mutante paga el
arranque de Postgres y las migraciones. Este script muta uno o dos módulos por
ejecución y lanza **solo los tests que cubren ese módulo**, que es lo que hace
la señal utilizable en un job semanal.

``setup.cfg`` traía una sección ``[mutmut]`` con ``runner = pytest tests/`` (la
suite entera por mutante) y mutmut no estaba instalado en ningún flujo: la
configuración existía pero nadie la ejecutaba nunca.

Uso::

    python scripts/run_mutation_sample.py --list
    python scripts/run_mutation_sample.py --modules scraper/codice_parser.py
    python scripts/run_mutation_sample.py --week 31      # rotación determinista
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Módulo → tests que de verdad lo ejercitan. Un mapeo explícito y no un
# `pytest tests/` genérico: con los tests dirigidos, un mutante tarda segundos
# en vez de minutos, y un superviviente señala exactamente qué test falta.
OBJETIVOS: dict[str, tuple[str, ...]] = {
    "scraper/codice_parser.py": (
        "tests/test_codice_parser.py",
        "tests/test_codice_parser_golden.py",
    ),
    "scraper/filters.py": ("tests/test_filters.py",),
    "shared/geo.py": ("tests/test_shared_geo.py",),
    "shared/dates.py": ("tests/test_dates.py", "tests/test_property_dates.py"),
    "api/auth.py": ("tests/test_auth_core.py", "tests/test_api_keys.py"),
    "api/scopes.py": ("tests/test_api_scopes.py",),
    "services/dedupe.py": ("tests/test_dedupe.py", "tests/test_dedupe_quality.py"),
    "services/normalization.py": ("tests/test_normalize.py",),
}

# Por encima de esto, el módulo entra en el backlog: hay demasiado código que
# se puede romper sin que ningún test se entere.
MAX_PCT_SUPERVIVIENTES = 30.0


def _rotacion(semana: int, cuantos: int = 2) -> list[str]:
    """Elige módulos de forma determinista a partir del número de semana."""
    modulos = sorted(OBJETIVOS)
    inicio = (semana * cuantos) % len(modulos)
    seleccion = [modulos[(inicio + i) % len(modulos)] for i in range(cuantos)]
    return seleccion


def _mutmut_bin() -> str:
    """Ruta absoluta del ejecutable (ruff S607 no admite rutas parciales)."""
    ruta = shutil.which("mutmut")
    if ruta is None:
        raise SystemExit("mutmut no está instalado: pip install mutmut")
    return ruta


def _ejecutar_mutmut(modulo: str) -> dict[str, int]:
    """Corre mutmut sobre un módulo con sus tests dirigidos."""
    mutmut = _mutmut_bin()
    tests = " ".join(OBJETIVOS[modulo])
    comando = [
        mutmut,
        "run",
        "--paths-to-mutate",
        modulo,
        "--runner",
        f"python -m pytest -x -q --no-cov --no-header -p no:cacheprovider {tests}",
        "--tests-dir",
        "tests/",
    ]
    print(f"\n── {modulo} ──")
    print(f"   tests: {tests}")
    # mutmut sale != 0 cuando sobreviven mutantes: no es un error de ejecución.
    subprocess.run(comando, cwd=_ROOT, check=False)

    resultado = subprocess.run(
        [mutmut, "results"], cwd=_ROOT, check=False, capture_output=True, text=True
    )
    salida = resultado.stdout
    supervivientes = salida.count("survived")
    muertos = salida.count("killed")
    return {"supervivientes": supervivientes, "muertos": muertos}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modules", nargs="*", choices=sorted(OBJETIVOS), help="Módulos a mutar")
    parser.add_argument(
        "--week",
        type=int,
        help="Número de semana para la rotación determinista (sin --modules)",
    )
    parser.add_argument("--list", action="store_true", help="Lista los módulos configurados")
    parser.add_argument(
        "--report", default="mutation-report.json", help="Fichero de salida del resumen"
    )
    args = parser.parse_args()

    if args.list:
        print("Módulos configurados y sus tests dirigidos:\n")
        for modulo, tests in sorted(OBJETIVOS.items()):
            print(f"  {modulo}")
            for test in tests:
                print(f"      {test}")
        return 0

    modulos = args.modules or _rotacion(args.week if args.week is not None else 0)
    print(f"Mutando: {', '.join(modulos)}")

    resumen: dict[str, dict[str, int]] = {}
    for modulo in modulos:
        resumen[modulo] = _ejecutar_mutmut(modulo)

    print("\n── Resumen ──")
    problematicos: list[str] = []
    for modulo, datos in resumen.items():
        total = datos["supervivientes"] + datos["muertos"]
        pct = round(100.0 * datos["supervivientes"] / total, 1) if total else 0.0
        print(
            f"  {modulo:<34} muertos={datos['muertos']:>4} "
            f"supervivientes={datos['supervivientes']:>4} ({pct}%)"
        )
        if pct > MAX_PCT_SUPERVIVIENTES:
            problematicos.append(f"{modulo}: {pct}% de mutantes sobreviven")

    Path(args.report).write_text(json.dumps(resumen, indent=2), encoding="utf-8")
    print(f"\nReporte: {args.report}")

    if problematicos:
        print("\nMódulos por encima del umbral (candidatos a ítem de backlog):")
        for linea in problematicos:
            print(f"  {linea}")

    # Siempre 0: esto es un informe periódico, no un gate de PR. Un mutante que
    # sobrevive puede significar "falta un test" o "esa mutación es
    # equivalente"; decidirlo requiere criterio humano, así que la salida se
    # consume por el backlog y no bloqueando a nadie.
    return 0


if __name__ == "__main__":
    sys.exit(main())
