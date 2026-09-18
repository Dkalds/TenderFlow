"""Dependencia compartida de paginación por offset (`limit`/`offset`).

La mitad de sobre del contrato común ya estaba hecha —`PaginatedResponse` y
`CursorPaginatedResponse` viven en `shared/dto.py`—, pero cada ruta seguía
declarando sus dos `Query(...)` a mano, y así fue como el tope de página llegó
a tener cuatro valores distintos (100, 200, 500, 1000) antes de C8.5. Esta
dependencia es la otra mitad: una sola declaración de los dos parámetros, con
`MAX_PAGE_LIMIT` como tope único.

Lo único que varía por ruta es el **default** de `limit`, porque es de
producto (una bandeja de 25 filas, un hilo de 200 comentarios); el tope no:
una ruta que necesite otro tope está pidiendo otro contrato, y eso se decide en
`shared/dto.py`, no aquí.

Uso::

    from api.pagination import PageParams, pagina

    @router.get("/cosas")
    async def listar(page: PageParams = Depends(pagina())) -> ...:
        filas = repo.listar(limit=page.limit, offset=page.offset)

Los nombres de los parámetros HTTP (`limit`, `offset`) no cambian respecto a
las rutas que la adoptan: para el cliente es la misma petición.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Query

from shared.dto import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT


@dataclass(frozen=True, slots=True)
class PageParams:
    """Ventana pedida por el cliente, ya validada contra el contrato."""

    limit: int
    offset: int


def pagina(default_limit: int = DEFAULT_PAGE_LIMIT) -> Callable[[int, int], PageParams]:
    """Devuelve la dependencia `limit`/`offset` con el default de la ruta.

    Es una factoría y no una dependencia fija porque FastAPI lee el default del
    `Query` al registrar la ruta: un default distinto por ruta necesita una
    función distinta.
    """
    if not 1 <= default_limit <= MAX_PAGE_LIMIT:
        # Un default fuera del rango haría que la petición sin `limit` diera
        # 422: se falla al importar el router, no en la primera petición.
        raise ValueError(f"default_limit={default_limit} fuera de [1, {MAX_PAGE_LIMIT}]")

    def _page_params(
        limit: int = Query(
            default_limit,
            ge=1,
            le=MAX_PAGE_LIMIT,
            description=f"Tamaño de página (máx. {MAX_PAGE_LIMIT}).",
        ),
        offset: int = Query(0, ge=0, description="Filas a saltar desde el inicio."),
    ) -> PageParams:
        return PageParams(limit=limit, offset=offset)

    return _page_params
