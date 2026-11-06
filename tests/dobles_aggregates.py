"""Sustituir la conexión de lectura de ``db.repositories.aggregates``.

``aggregates`` es un paquete con un submódulo por familia de métodos, y cada uno
importa ``connect_read`` por su cuenta (``filtros`` también, para ``_lectura``).
Parchear el nombre en el paquete no surtiría efecto —el paquete ni lo
reexporta—: hay que hacerlo donde se usa. Un test que ejercite una sola familia
parchea su submódulo; los que recorren métodos de varias usan esto.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from types import ModuleType
from typing import Any
from unittest.mock import patch


def modulos_con_connect_read() -> list[ModuleType]:
    """Los submódulos de ``db.repositories.aggregates`` que abren conexión."""
    import db.repositories.aggregates as paquete

    modulos = [
        importlib.import_module(f"{paquete.__name__}.{info.name}")
        for info in pkgutil.iter_modules(paquete.__path__)
    ]
    return [m for m in modulos if hasattr(m, "connect_read")]


@contextmanager
def connect_read_de_aggregates(**kwargs: Any) -> Iterator[None]:
    """``patch.object(<submódulo>, "connect_read", **kwargs)`` en todos a la vez."""
    with ExitStack() as pila:
        for modulo in modulos_con_connect_read():
            pila.enter_context(patch.object(modulo, "connect_read", **kwargs))
        yield
