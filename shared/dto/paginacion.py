"""Contrato de paginación común: envelopes por offset y por cursor y sus topes."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

# ── Contrato de paginación común ───────────────────────────────────────────
#
# Los dos envelopes de abajo nacieron dentro de `api/routes/licitaciones.py` y
# vivían allí, en 1 de los 30 módulos de rutas: cada consumidor del cliente TS
# aprendía una forma distinta de paginar. Se mueven aquí —el módulo que ya es
# el contrato API↔web— para que las siguientes olas de rutas los reutilicen en
# vez de reinventar la forma.
#
# Conservan **el nombre exacto** que tenían en la ruta a propósito: FastAPI
# deriva de él el componente OpenAPI
# (`PaginatedResponse_LicitacionSummary_`, con el `LicitacionSummary` de la
# ruta,
# `CursorPaginatedResponse_LicitacionSummary_`) que `web/src/generated/api.d.ts`
# ya referencia. Rebautizarlos a `Paginated[T]` habría roto el cliente generado
# sin ganar nada: el idioma ya existía, solo estaba en el sitio equivocado.

_ItemT = TypeVar("_ItemT")

#: Tope de `limit` en los listados que adoptan este contrato de paginación. Es
#: parte del contrato (por encima el API responde 422), así que vive con los
#: DTOs y no en una ruta.
#:
#: **Universal desde 2026-09-06** (C8.5). Hasta entonces la adopción iba por olas
#: y dos rutas mantenían su tope heredado de ``le=1000``:
#: ``GET /competitive/renovaciones`` y ``GET /admin/users``. Bajarlas no fue una
#: limpieza sino un estrechamiento del contrato —un cliente que pidiera 800
#: empezó a recibir 422—, así que se hizo de forma deliberada y etiquetada, y
#: `scripts/check_api_breaking.py` lo señala como tal. El motivo por el que
#: renovaciones pedía 1000 había desaparecido antes: desde que ``order_by=score``
#: ordena en servidor, el front pide 200 y recibe el top-N real.
#:
#: Un tope propio en una ruta nueva es cómo vuelve a dispersarse el contrato:
#: ``tests/test_contrato_paginacion.py`` lo impide.
MAX_PAGE_LIMIT = 500

#: Página por defecto cuando el endpoint no tiene un motivo para otra cosa.
DEFAULT_PAGE_LIMIT = 50


class PaginatedResponse(BaseModel, Generic[_ItemT]):
    """Página de un listado con paginación por offset.

    ``total`` vale ``-1`` cuando el endpoint se invocó con ``with_total=false``:
    la página es válida pero el conteo no se calculó (evita el ``COUNT(*)``).
    """

    total: int
    limit: int
    offset: int
    items: list[_ItemT]
    deprecation_notice: str | None = None


class CursorPaginatedResponse(BaseModel, Generic[_ItemT]):
    """Página con paginación por cursor (recomendada para datasets grandes).

    No necesita ``COUNT(*)`` ni se descuadra con inserciones concurrentes, así
    que es la forma preferida para listados que crecen.
    """

    items: list[_ItemT]
    next_cursor: str | None = None
    has_more: bool = False
    limit: int


class CursorPaginatedResponseWithTotal(CursorPaginatedResponse[_ItemT], Generic[_ItemT]):
    """:class:`CursorPaginatedResponse` con un ``total`` opcional.

    Subclase y no un campo más en la base: las claves de la base están
    congeladas (``tests/test_contrato_paginacion.py``) porque el cliente
    generado ya las declara. ``total`` sólo llega cuando se pide
    (``with_total=true``) y es ``None`` si no: el cursor existe precisamente
    para no pagar un ``COUNT(*)`` en cada página. Lo usa el listado de
    licitaciones, que es el que sustituye al de offset en /detalle y necesita
    decir «de N» al pie.
    """

    total: int | None = None
