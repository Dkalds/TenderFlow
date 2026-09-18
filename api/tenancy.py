"""Frontera de tenencia — resuelve la organización activa como dependency.

``resolve_organization`` (services/organizations.py) ya sabe caer a la
organización personal del usuario cuando no se especifica ninguna; el bug
histórico no era esa función, sino que 6 de los 7 route files que aceptan
``organization_id`` solo la invocaban dentro de ``if organization_id is not
None:`` -- omitirlo (el default del cliente) saltaba la resolución entera y
dejaba pasar ``None`` hasta el repositorio, que en ese caso cae a una query
sin filtro de organización. ``services/pursuits.py`` es el único sitio que ya
lo hacía bien: resuelve siempre, nunca solo "si el cliente lo mandó". Este
módulo es ese mismo patrón, empaquetado para las rutas GET/DELETE (query
param, vía ``require_organization``) y POST/PUT (organization_id en el body,
vía ``resolve_organization_ctx`` llamado explícitamente con ese valor).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Depends, HTTPException, Query, status

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from services.organizations import resolve_organization
from shared.tenant_context import set_organization


async def resolve_organization_ctx(
    ctx: dict[str, Any],
    organization_id: int | None,
    *,
    write: bool = False,
) -> dict[str, Any]:
    """Resuelve la organización (o la personal por defecto) y valida el rol.

    Traduce el rechazo de dominio (sin membresía, o viewer intentando
    escribir) a HTTP 403. Devuelve ``ctx`` enriquecido con
    ``organization_id``/``organization_role`` ya resueltos -- nunca ``None``.

    Además deja la organización resuelta en ``shared.tenant_context`` para el
    resto de la petición: cada transacción que abra ``db/connection.py`` a
    partir de aquí emite ``SET LOCAL app.organization_id`` y las políticas
    RLS de ``v128`` actúan de respaldo del filtro de los repositorios
    (ADR-034). La resolución en sí corre **antes** de fijar el ámbito, sin
    respaldo: lee ``organization_memberships``, que está fuera de las
    políticas precisamente para poder resolver membresías entre
    organizaciones.

    No se guarda el token ni se restaura al salir: la dependency y el handler
    corren en la tarea de asyncio de la petición, que nace con una copia del
    contexto y muere con la respuesta, así que el valor no puede filtrarse a
    otra petición. Y no hay un único punto de salida donde restaurarlo — esta
    función se usa como dependency (GET/DELETE) y llamada a mano desde
    handlers POST/PUT.
    """
    try:
        resolved_id, role = await run_db(
            resolve_organization, int(ctx["user_id"]), organization_id, write=write
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    set_organization(resolved_id)
    return {**ctx, "organization_id": resolved_id, "organization_role": role}


def require_organization(*, write: bool = False) -> Callable[..., Awaitable[dict[str, Any]]]:
    """Dependency para rutas GET/DELETE: ``organization_id`` viaja en la query.

    Para POST/PUT donde ``organization_id`` viaja en el body del request,
    usar ``resolve_organization_ctx`` directamente dentro del handler con
    ``body.organization_id`` -- una dependency no puede ver un campo de un
    modelo Pydantic que FastAPI resuelve por separado.
    """

    async def _dependency(
        organization_id: int | None = Query(
            default=None,
            ge=1,
            description="Organización activa; por defecto la personal del usuario.",
        ),
        ctx: dict[str, Any] = Depends(require_any_auth),
    ) -> dict[str, Any]:
        return await resolve_organization_ctx(ctx, organization_id, write=write)

    _dependency.__name__ = f"require_organization_write_{write}"
    return _dependency
