#!/usr/bin/env python3
"""
check_requirements_sync.py — Verifica que requirements.txt cubre requirements.in.

Motivación: requirements.txt es el lockfile que instala docker/Dockerfile.api
(``pip install -r requirements.txt``). requirements.in declara las dependencias
directas y se recompila a mano con ``uv pip compile requirements.in -o
requirements.txt``. Si alguien agrega una dependencia a requirements.in y
olvida recompilar, requirements.txt queda con un paquete faltante y el build
de producción revienta con ModuleNotFoundError (pasó con psycopg-pool y,
antes de eso, con uvicorn/redis — ver commits relacionados).

Este check NO compara versiones exactas (el lockfile puede tener versiones
más nuevas por parches transitivos; eso es esperado y no es un bug). Solo
verifica que el CONJUNTO de paquetes de primer nivel de requirements.in está
presente en requirements.txt.

Uso:
  python scripts/check_requirements_sync.py   # sale con 1 si falta algún paquete
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
REQUIREMENTS_IN = REPO_ROOT / "requirements.in"
REQUIREMENTS_TXT = REPO_ROOT / "requirements.txt"

# C3.1: el corte entre la imagen de la API y el plano de ingesta/ML. Los `.in`
# existen siempre; los `.txt` los produce `make lock` y pueden faltar en un
# entorno sin `uv` (el check lo dice en vez de fallar por ello).
REQUIREMENTS_API_IN = REPO_ROOT / "requirements-api.in"
REQUIREMENTS_API_TXT = REPO_ROOT / "requirements-api.txt"
REQUIREMENTS_PIPELINE_IN = REPO_ROOT / "requirements-pipeline.in"
REQUIREMENTS_PIPELINE_TXT = REPO_ROOT / "requirements-pipeline.txt"

#: Paquetes de `requirements.in` que el corte deja fuera a propósito.
#:
#: `requirements.in` sigue siendo el conjunto histórico y `requirements-api.in`
#: es un subconjunto suyo. Un paquete que no esté en ninguno de los dos hijos es
#: un olvido, y este check lo dice: es justo el error que convierte el corte en
#: un `ModuleNotFoundError` en el primer arranque.
SOLO_PIPELINE = frozenset({"lxml", "tenacity", "pybreaker"})

# PEP 503: normaliza nombres de paquete para comparar (case-insensitive,
# "-"/"_"/"." equivalentes). p.ej. "psycopg-pool" == "psycopg_pool" == "Psycopg.Pool".
_NORMALIZE_RE = re.compile(r"[-_.]+")


def _normalize(name: str) -> str:
    return _NORMALIZE_RE.sub("-", name).lower()


def _package_name(line: str) -> str | None:
    """Extrae el nombre de paquete de una línea de requirements (sin extras/specifiers)."""
    stripped = line.split("#", 1)[0].strip()
    if not stripped or stripped.startswith(("-r ", "-c ")):
        return None
    # Corta en el primer separador de extra/specifier/marker: [ , ==, >=, ;, espacio
    match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", stripped)
    return match.group(1) if match else None


def _names_from_in(path: Path) -> set[str]:
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        name = _package_name(line)
        if name:
            names.add(_normalize(name))
    return names


def _names_from_compiled(path: Path) -> set[str]:
    """Extrae nombres de paquete de un lockfile compilado (líneas ``pkg==version``).

    Ignora las líneas de comentario ``# via ...`` que uv/pip-compile intercala.
    """
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith((" ", "#", "\t")):
            continue
        name = _package_name(line)
        if name:
            names.add(_normalize(name))
    return names


def _comprueba_par(nombre_in: Path, nombre_txt: Path) -> int:
    """Todo paquete de un `.in` está en su `.txt` compilado."""
    if not nombre_in.exists():
        print(f"[check-requirements-sync] {nombre_in.name} no existe.")
        return 1
    if not nombre_txt.exists():
        # El `.txt` lo genera `make lock`, que necesita `uv`. En un entorno sin
        # él esto no es un fallo del repositorio: es un control no ejecutado, y
        # se dice en vez de darlo por verde.
        print(
            f"[check-requirements-sync] AVISO: falta {nombre_txt.name}; "
            f"no se pudo verificar. Generalo con `make lock`."
        )
        return 0

    wanted = _names_from_in(nombre_in)
    compiled = _names_from_compiled(nombre_txt)
    missing = sorted(wanted - compiled)
    if missing:
        print(
            f"[check-requirements-sync] {nombre_txt.name} está desactualizado — "
            f"faltan paquetes que {nombre_in.name} declara:\n"
        )
        for name in missing:
            print(f"  - {name}")
        print(f"\nRecompila con: uv pip compile {nombre_in.name} -o {nombre_txt.name}")
        return 1

    print(
        f"[check-requirements-sync] OK — los {len(wanted)} paquetes de "
        f"{nombre_in.name} están presentes en {nombre_txt.name}."
    )
    return 0


def _comprueba_corte() -> int:
    """El corte API/pipeline cubre `requirements.in` sin huecos ni sorpresas."""
    if not REQUIREMENTS_API_IN.exists() or not REQUIREMENTS_PIPELINE_IN.exists():
        print("[check-requirements-sync] falta requirements-api.in o -pipeline.in.")
        return 1

    historico = _names_from_in(REQUIREMENTS_IN)
    api = _names_from_in(REQUIREMENTS_API_IN)
    solo_pipeline = {_normalize(n) for n in SOLO_PIPELINE}

    sin_asignar = sorted(historico - api - solo_pipeline)
    if sin_asignar:
        print(
            "[check-requirements-sync] paquetes de requirements.in que el corte "
            "C3.1 no asigna a ningún plano:\n"
        )
        for name in sin_asignar:
            print(f"  - {name}")
        print(
            "\nAñadilos a requirements-api.in (si alguna ruta los importa, aunque "
            "sea de forma perezosa) o a SOLO_PIPELINE de este script."
        )
        return 1

    filtrados = sorted(api & solo_pipeline)
    if filtrados:
        print(
            "[check-requirements-sync] paquetes declarados a la vez en la API y "
            f"como solo-pipeline: {filtrados}"
        )
        return 1

    print(
        f"[check-requirements-sync] OK — el corte C3.1 asigna los "
        f"{len(historico)} paquetes: {len(api & historico)} a la API, "
        f"{len(solo_pipeline)} solo al pipeline."
    )
    return 0


def main() -> int:
    codigo = 0
    codigo |= _comprueba_par(REQUIREMENTS_IN, REQUIREMENTS_TXT)
    codigo |= _comprueba_par(REQUIREMENTS_API_IN, REQUIREMENTS_API_TXT)
    codigo |= _comprueba_par(REQUIREMENTS_PIPELINE_IN, REQUIREMENTS_PIPELINE_TXT)
    codigo |= _comprueba_corte()
    return codigo


if __name__ == "__main__":
    sys.exit(main())
