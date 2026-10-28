"""La versión de Python es una sola: la de ``.python-version``.

La imagen de producción, los workflows y el ``--python-version`` de los
lockfiles tienen que nombrar la misma menor. El PR #463 de Renovate («update
github-actions») cambió ``python-version: "3.13"`` por ``"3.14"`` en 29 pasos
de 17 workflows: para Renovate el ``with:`` de ``actions/setup-python`` es una
dependencia más del manager ``github-actions``. La matriz del job ``test`` es
una expresión y no la tocó, así que el PR pasó en verde con la suite en 3.13 y
el lint, los crons de scraping y los entrenamientos en 3.14.

Si este test falla en un PR de Renovate: ese PR no se fusiona tal cual. Subir
de menor es un cambio a mano en ``.python-version``, ``docker/Dockerfile.api``,
los workflows, ``pyproject.toml`` (suelo, ruff y mypy) y ``make lock``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERSION = (REPO / ".python-version").read_text(encoding="utf-8").strip()

# Literales sueltos y listas de matriz (`python-version: ["3.13"]`, el job `test`).
_PYTHON_VERSION_LITERAL = re.compile(r"""^\s*python-version:\s*["']?(\d[\d.]*)["']?\s*$""")
_PYTHON_VERSION_LISTA = re.compile(r"""^\s*python-version:\s*\[([^\]]*)\]\s*$""")
_FROM_PYTHON = re.compile(r"^FROM python:(\S+)")


def test_los_workflows_usan_la_version_de_python_version() -> None:
    encontrados: list[tuple[str, int, str]] = []
    for workflow in sorted((REPO / ".github" / "workflows").glob("*.yml")):
        for numero, linea in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
            if casa := _PYTHON_VERSION_LITERAL.match(linea):
                encontrados.append((workflow.name, numero, casa.group(1)))
            elif casa := _PYTHON_VERSION_LISTA.match(linea):
                encontrados += [
                    (workflow.name, numero, valor.strip().strip("\"'"))
                    for valor in casa.group(1).split(",")
                ]

    assert encontrados, "ningún workflow fija python-version: la regex ya no casa"
    distintos = [
        f"{nombre}:{numero} → {version}"
        for nombre, numero, version in encontrados
        if version != VERSION
    ]
    assert not distintos, f".python-version dice {VERSION}: {distintos}"


def test_la_imagen_base_es_un_parche_de_esa_version() -> None:
    lineas = (REPO / "docker" / "Dockerfile.api").read_text(encoding="utf-8").splitlines()
    etiquetas = [casa.group(1) for linea in lineas if (casa := _FROM_PYTHON.match(linea))]

    assert etiquetas, "docker/Dockerfile.api ya no parte de python:<versión>"
    for etiqueta in etiquetas:
        assert etiqueta.startswith(f"{VERSION}."), etiqueta


def test_renovate_no_propone_la_version_de_python_de_los_workflows() -> None:
    reglas = json.loads((REPO / "renovate.json").read_text(encoding="utf-8"))["packageRules"]

    (de_workflows,) = [
        regla
        for regla in reglas
        if regla.get("matchManagers") == ["github-actions"]
        and regla.get("matchDepNames") == ["python"]
    ]
    assert de_workflows["enabled"] is False

    (de_imagen,) = [
        regla
        for regla in reglas
        if regla.get("matchManagers") == ["dockerfile"]
        and regla.get("matchPackageNames") == ["python"]
    ]
    permitidas = re.compile(de_imagen["allowedVersions"].strip("/"))
    assert permitidas.search(f"{VERSION}.0")
    menor_siguiente = f"{VERSION.split('.')[0]}.{int(VERSION.split('.')[1]) + 1}.0"
    assert not permitidas.search(menor_siguiente)


def test_pyproject_comprueba_contra_la_version_que_se_despliega() -> None:
    """Suelo, ruff y mypy apuntan a la menor de producción.

    Hasta 2026-10 decían 3.11 con producción en 3.13: ningún módulo podía usar
    sintaxis de 3.12+ y mypy comprobaba contra un intérprete que no se desplegaba.
    """
    import tomllib

    datos = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert datos["project"]["requires-python"] == f">={VERSION}"
    assert datos["tool"]["ruff"]["target-version"] == "py" + VERSION.replace(".", "")
    assert datos["tool"]["mypy"]["python_version"] == VERSION
