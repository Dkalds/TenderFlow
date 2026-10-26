#!/usr/bin/env python3
"""
check_requirements_sync.py — Verifica que requirements.txt cubre requirements.in.

Motivación: requirements.txt es el lockfile del CI y de los runners (y hasta
2026-09-18 lo era de docker/Dockerfile.api, que ahora instala
requirements-api.txt; ver C3.1 abajo). requirements.in declara las dependencias
directas y se recompila a mano con ``uv pip compile requirements.in -o
requirements.txt``. Si alguien agrega una dependencia a requirements.in y
olvida recompilar, requirements.txt queda con un paquete faltante y el build
de producción revienta con ModuleNotFoundError (pasó con psycopg-pool y,
antes de eso, con uvicorn/redis — ver commits relacionados).

Este check NO compara versiones exactas (el lockfile puede tener versiones
más nuevas por parches transitivos; eso es esperado y no es un bug). Solo
verifica que el CONJUNTO de paquetes de primer nivel de requirements.in está
presente en requirements.txt.

Además (2026-10) comprueba que ``pyproject.toml`` no vuelve a tener su propia
lista de ``dependencies``: las lee de ``requirements.in`` (``[tool.setuptools.dynamic]``),
y ``requirements.in`` tiene que seguir siendo legible para setuptools. Antes eran
dos listas escritas a mano que no coincidían.

Uso:
  python scripts/check_requirements_sync.py   # sale con 1 si falta algún paquete
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
REQUIREMENTS_IN = REPO_ROOT / "requirements.in"
REQUIREMENTS_TXT = REPO_ROOT / "requirements.txt"

# C3.1: el corte entre la imagen de la API y el plano de ingesta/ML. Los `.in`
# existen siempre; los `.txt` los produce `make lock` y pueden faltar en un
# entorno sin `uv` (el check lo dice en vez de fallar por ello).
REQUIREMENTS_API_IN = REPO_ROOT / "requirements-api.in"
REQUIREMENTS_API_TXT = REPO_ROOT / "requirements-api.txt"
REQUIREMENTS_PIPELINE_IN = REPO_ROOT / "requirements-pipeline.in"
REQUIREMENTS_PIPELINE_TXT = REPO_ROOT / "requirements-pipeline.txt"
# El servidor MCP interno (mcp_server/) es un tercer plano: hereda el cono de la
# API y añade `mcp`. Mismo trato que los otros hijos.
REQUIREMENTS_MCP_IN = REPO_ROOT / "requirements-mcp.in"
REQUIREMENTS_MCP_TXT = REPO_ROOT / "requirements-mcp.txt"

#: Paquetes de `requirements.in` que el corte deja fuera a propósito.
#:
#: `requirements.in` sigue siendo el conjunto histórico y `requirements-api.in`
#: es un subconjunto suyo. Un paquete que no esté en ninguno de los dos hijos es
#: un olvido, y este check lo dice: es justo el error que convierte el corte en
#: un `ModuleNotFoundError` en el primer arranque.
#:
#: scikit-learn, statsmodels y networkx entraron el 2026-09-18: la API los
#: usaba en caminos de request que ahora degradan sin ellos (ver la cabecera de
#: requirements-api.in). tenacity y pybreaker salieron el 2026-10-01: la API
#: descarga pliegos para la ficha bajo demanda, y sin ellos esa extracción
#: moría en el import de `scraper/resilience.py`. joblib entró el 2026-10, al
#: pasar `requirements.in` a ser también las dependencias del paquete: llega con
#: scikit-learn y solo lo importan los modelos de `services/ml/`.
SOLO_PIPELINE = frozenset({"lxml", "scikit-learn", "joblib", "statsmodels", "networkx"})

#: Paquetes de `requirements.in` que solo instala el proceso MCP
#: (`requirements-mcp.in`). Siguen en `requirements.in` para que el lock que
#: prueba el CI los pine y los hijos salgan con las mismas versiones, pero la
#: imagen de la API no los trae.
SOLO_MCP = frozenset({"mcp"})

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


def _pines(path: Path) -> dict[str, str]:
    """``{paquete normalizado: versión}`` de un lockfile compilado."""
    pines: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith((" ", "#", "\t")):
            continue
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==([^\s;\\]+)", line)
        if match:
            pines[_normalize(match.group(1))] = match.group(2)
    return pines


def _comprueba_pines_coherentes() -> int:
    """Los hijos del corte fijan las mismas versiones que `requirements.txt`.

    El CI prueba con `requirements.txt`; la imagen de la API instala
    `requirements-api.txt`. Si un pin difiere, producción corre una versión
    que ningún test ejercitó — o, en el caso de un bump de seguridad aplicado
    solo al lock histórico, la imagen expuesta a internet se queda sin el
    parche. `make lock` los compila con `--constraint requirements.txt`, así
    que un desajuste significa que alguien tocó un lockfile y no los otros.
    """
    if not REQUIREMENTS_TXT.exists():
        return 0
    referencia = _pines(REQUIREMENTS_TXT)
    codigo = 0
    for hijo in (REQUIREMENTS_API_TXT, REQUIREMENTS_PIPELINE_TXT, REQUIREMENTS_MCP_TXT):
        if not hijo.exists():
            continue
        distintos = sorted(
            f"{nombre} {version} (requirements.txt: {referencia[nombre]})"
            for nombre, version in _pines(hijo).items()
            if nombre in referencia and referencia[nombre] != version
        )
        if distintos:
            print(
                f"[check-requirements-sync] {hijo.name} fija versiones distintas "
                "de requirements.txt:\n"
            )
            for linea in distintos:
                print(f"  - {linea}")
            print("\nRecompila todos con `make lock`.")
            codigo = 1
    if codigo == 0:
        print(
            "[check-requirements-sync] OK — los pines del corte C3.1 coinciden con requirements.txt."
        )
    return codigo


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
    solo_mcp = {_normalize(n) for n in SOLO_MCP}

    sin_asignar = sorted(historico - api - solo_pipeline - solo_mcp)
    if sin_asignar:
        print(
            "[check-requirements-sync] paquetes de requirements.in que el corte "
            "C3.1 no asigna a ningún plano:\n"
        )
        for name in sin_asignar:
            print(f"  - {name}")
        print(
            "\nAñadilos a requirements-api.in (si alguna ruta los importa, aunque "
            "sea de forma perezosa) o a SOLO_PIPELINE / SOLO_MCP de este script."
        )
        return 1

    filtrados = sorted(api & (solo_pipeline | solo_mcp))
    if filtrados:
        print(
            "[check-requirements-sync] paquetes declarados a la vez en la API y "
            f"como solo-pipeline: {filtrados}"
        )
        return 1

    # Declarar fuera no basta: una dependencia transitiva nueva de la API
    # podría volver a traer scikit-learn al lockfile sin que nadie lo escriba
    # en un `.in`. Lo que cuenta es lo que la imagen instala.
    if REQUIREMENTS_API_TXT.exists():
        colados = sorted(_names_from_compiled(REQUIREMENTS_API_TXT) & (solo_pipeline | solo_mcp))
        if colados:
            print(
                "[check-requirements-sync] requirements-api.txt instala paquetes "
                f"que el corte deja solo al pipeline: {colados}"
            )
            return 1

    print(
        f"[check-requirements-sync] OK — el corte C3.1 asigna los "
        f"{len(historico)} paquetes: {len(api & historico)} a la API, "
        f"{len(solo_pipeline)} solo al pipeline, {len(solo_mcp)} solo al MCP."
    )
    return 0


def _comprueba_pyproject() -> int:
    """`pyproject.toml` toma sus `dependencies` de `requirements.in`, y solo de ahí.

    Hasta 2026-10 las declaraba a mano y no coincidían con `requirements.in`
    (faltaban httpx, uvicorn, starlette, pypdf, mcp…): dos fuentes de verdad, y
    `pip install -e .` pedía otra cosa que el lock. Ahora `[project]` las
    declara `dynamic` y `[tool.setuptools.dynamic]` las lee del fichero, que por
    eso tiene que seguir en el formato que setuptools entiende: sin `-r`, `-c`,
    `-e` ni opciones, y sin comentarios al final de una línea.
    """
    datos = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    proyecto = datos.get("project", {})
    errores: list[str] = []
    if "dependencies" in proyecto:
        errores.append(
            "[project] declara `dependencies` a mano: es una segunda lista. "
            "Las dependencias van en requirements.in."
        )
    if "dependencies" not in proyecto.get("dynamic", []):
        errores.append('[project] no declara `dynamic = ["dependencies"]`.')
    dinamico = datos.get("tool", {}).get("setuptools", {}).get("dynamic", {})
    fichero = dinamico.get("dependencies", {}).get("file")
    if fichero != [REQUIREMENTS_IN.name]:
        errores.append(
            "[tool.setuptools.dynamic] dependencies tiene que ser "
            f'{{ file = ["{REQUIREMENTS_IN.name}"] }} (es: {fichero!r}).'
        )

    for numero, linea in enumerate(REQUIREMENTS_IN.read_text(encoding="utf-8").splitlines(), 1):
        limpia = linea.strip()
        if not limpia or limpia.startswith("#"):
            continue
        if limpia.startswith("-"):
            errores.append(
                f"{REQUIREMENTS_IN.name}:{numero}: `{limpia}` es una opción de pip; "
                "setuptools no la entiende al leer las dependencias del paquete."
            )
        elif "#" in limpia:
            errores.append(
                f"{REQUIREMENTS_IN.name}:{numero}: comentario al final de la línea; "
                "setuptools lo leería como parte del especificador. Subilo a su propia línea."
            )

    if errores:
        print(
            "[check-requirements-sync] pyproject.toml y requirements.in no son una sola fuente:\n"
        )
        for error in errores:
            print(f"  - {error}")
        return 1
    print(
        "[check-requirements-sync] OK — pyproject.toml lee sus dependencias de "
        f"{REQUIREMENTS_IN.name}."
    )
    return 0


def main() -> int:
    codigo = 0
    codigo |= _comprueba_pyproject()
    codigo |= _comprueba_par(REQUIREMENTS_IN, REQUIREMENTS_TXT)
    codigo |= _comprueba_par(REQUIREMENTS_API_IN, REQUIREMENTS_API_TXT)
    codigo |= _comprueba_par(REQUIREMENTS_PIPELINE_IN, REQUIREMENTS_PIPELINE_TXT)
    codigo |= _comprueba_par(REQUIREMENTS_MCP_IN, REQUIREMENTS_MCP_TXT)
    codigo |= _comprueba_corte()
    codigo |= _comprueba_pines_coherentes()
    return codigo


if __name__ == "__main__":
    sys.exit(main())
