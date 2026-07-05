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


def main() -> int:
    if not REQUIREMENTS_IN.exists() or not REQUIREMENTS_TXT.exists():
        print("[check-requirements-sync] requirements.in o requirements.txt no existen.")
        return 1

    wanted = _names_from_in(REQUIREMENTS_IN)
    compiled = _names_from_compiled(REQUIREMENTS_TXT)

    missing = sorted(wanted - compiled)
    if missing:
        print(
            "[check-requirements-sync] requirements.txt está desactualizado — "
            "faltan paquetes que requirements.in declara:\n"
        )
        for name in missing:
            print(f"  - {name}")
        print("\nRecompila con: uv pip compile requirements.in -o requirements.txt")
        return 1

    print(
        f"[check-requirements-sync] OK — los {len(wanted)} paquetes de "
        "requirements.in están presentes en requirements.txt."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
