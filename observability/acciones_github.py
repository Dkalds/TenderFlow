"""Anotaciones de GitHub Actions (``::warning``/``::error``/``::notice``).

Las *workflow commands* no son un log: son un protocolo que el runner lee de la
salida del proceso y convierte en anotaciones del resumen del run. Por eso no
pueden pasar por ``structlog`` (el renderer JSON las rompería), y por eso
tampoco son un ``print()`` cualquiera: ``scripts/check_prints.py`` prohíbe
``print`` en ``scraper/``, ``services/`` y ``scheduler/`` fuera de un
``__main__``, y este módulo es el sitio único que conoce la sintaxis.

Fuera de Actions la línea sale igual, a ``stderr``: quien corre el CLI a mano
la ve, y no se mezcla con lo que el programa escriba por ``stdout``.

Referencia: https://docs.github.com/actions/using-workflows/workflow-commands-for-github-actions
"""

from __future__ import annotations

import sys
from typing import Literal, TextIO

Nivel = Literal["notice", "warning", "error"]


def _escapar_propiedad(valor: str) -> str:
    # Las propiedades (`title=`) terminan en `,` o `::`; el mensaje, en el salto
    # de línea. Los escapes son los que documenta GitHub.
    return (
        valor.replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
        .replace(":", "%3A")
        .replace(",", "%2C")
    )


def _escapar_mensaje(valor: str) -> str:
    return valor.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def anotar(nivel: Nivel, titulo: str, mensaje: str, *, salida: TextIO | None = None) -> None:
    """Emite ``::<nivel> title=<titulo>::<mensaje>`` en una línea."""
    destino = salida if salida is not None else sys.stderr
    destino.write(f"::{nivel} title={_escapar_propiedad(titulo)}::{_escapar_mensaje(mensaje)}\n")
    destino.flush()
