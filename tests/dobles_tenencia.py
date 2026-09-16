"""Dobles del ámbito de tenencia (ADR-034) para los tests de servicio.

Vive en un módulo y no en una fixture de ``conftest.py`` porque la mitad de los
usos están en funciones auxiliares de cada fichero —``_correr(...)``,
``_entorno(...)``— que pytest no inyecta.

Y vive en **un** sitio porque antes había seis copias idénticas: el día que la
firma de ``alcance_resuelto`` cambie, una copia con la firma vieja es un test
en verde tapando un servicio roto.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any


def alcance_doble(
    resolucion: Callable[..., tuple[int, str]],
) -> Callable[..., Any]:
    """Sustituto de ``alcance_resuelto`` que cede lo que devuelva ``resolucion``.

    Context manager, como el real: además de resolver, acota el bloque con el
    ámbito de tenencia y lo suelta al salir. Un doble que devolviera la tupla a
    secas haría pasar el test sin ejercitar la forma ``with ... as (org, rol)``
    que el servicio usa.
    """

    @contextmanager
    def _cm(
        user_id: int, organization_id: int | None = None, *, write: bool = False
    ) -> Iterator[tuple[int, str]]:
        yield resolucion(user_id, organization_id, write=write)

    return _cm


def alcance_fijo(organization_id: int = 7, rol: str = "owner") -> Callable[..., Any]:
    """El caso corriente: siempre la misma organización y el mismo rol."""
    return alcance_doble(lambda *_a, **_k: (organization_id, rol))
