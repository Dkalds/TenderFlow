"""Parte la suite en N trozos por fichero para correrlos en máquinas distintas.

Se carga con ``-p tests.particion`` y solo actúa si existe ``TF_PARTE=i/N``
(1 ≤ i ≤ N): deja en la sesión los ficheros de la parte ``i`` y deselecciona
el resto. Es lo que corre el job ``test-partes`` de ``.github/workflows/ci.yml``.

El reparto va por fichero, no por test: los fixtures de módulo se montan una
vez y un fichero no se reparte entre máquinas. Es un empaquetado voraz por
peso (de más pesado a más ligero, cada fichero a la parte que menos lleva),
con peso 1 por test ``unit`` y 30 por el resto: medido, ~10 ms frente a
~0,35 s. Los markers los pone ``pytest_collection_modifyitems`` de
``tests/conftest.py``; el hook de aquí es ``trylast`` para correr después.

Solo depende de los nodeid y sus markers, no del orden de colección ni de
``hash()``: cada worker de xdist colecciona por su cuenta y todos tienen que
llegar a la misma selección.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping

import pytest

VARIABLE = "TF_PARTE"
PESO_UNIT = 1
PESO_RESTO = 30

_FORMATO = re.compile(r"([0-9]+)/([0-9]+)")
_PARTE = pytest.StashKey[tuple[int, int]]()


def leer_parte(valor: str) -> tuple[int, int]:
    """``"i/N"`` → ``(i, N)``; cualquier otro valor es un error de uso."""
    casa = _FORMATO.fullmatch(valor)
    if casa is None or not 1 <= int(casa[1]) <= int(casa[2]):
        raise pytest.UsageError(f"{VARIABLE}={valor!r} no es válida: usa i/N con 1 <= i <= N")
    return int(casa[1]), int(casa[2])


def repartir(pesos: Mapping[str, int], partes: int) -> list[set[str]]:
    """Reparte los ficheros en ``partes`` grupos de peso parecido."""
    grupos: list[set[str]] = [set() for _ in range(partes)]
    cargas = [0] * partes
    # El nombre desempata los pesos iguales: sin él mandaría el orden de entrada.
    for fichero in sorted(pesos, key=lambda f: (-pesos[f], f)):
        destino = cargas.index(min(cargas))
        grupos[destino].add(fichero)
        cargas[destino] += pesos[fichero]
    return grupos


def _fichero(item: pytest.Item) -> str:
    return item.nodeid.split("::", 1)[0]


def pytest_configure(config: pytest.Config) -> None:
    # Se valida aquí y no al coleccionar: con xdist el error saldría una vez
    # por worker, y aquí sale una sola antes de arrancarlos.
    valor = os.environ.get(VARIABLE)
    if valor is not None:
        config.stash[_PARTE] = leer_parte(valor)


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _PARTE not in config.stash:
        return
    parte, partes = config.stash[_PARTE]
    pesos: dict[str, int] = {}
    for item in items:
        peso = PESO_UNIT if item.get_closest_marker("unit") else PESO_RESTO
        pesos[_fichero(item)] = pesos.get(_fichero(item), 0) + peso
    mios = repartir(pesos, partes)[parte - 1]
    fuera = [item for item in items if _fichero(item) not in mios]
    if fuera:
        config.hook.pytest_deselected(items=fuera)
        items[:] = [item for item in items if _fichero(item) in mios]
