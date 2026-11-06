"""Eventos de producto de la web, contados en Prometheus (``POST /telemetria/eventos``).

Vercel Web Analytics en el plan Hobby no guarda eventos personalizados, así que
los 23 del catálogo de ``web/src/lib/analytics.ts`` se perdían y no había con
qué decidir qué espacio de la consola sobra (Ola 3 del plan 2026-10). Esta ruta
los recibe y solo incrementa dos contadores: ``producto_eventos_total`` por
evento y ``producto_eventos_dimension_total`` por evento, propiedad y valor. No
escribe en base de datos ni guarda quién lo mandó.

Con sesión (o clave): mide el uso de la consola, que es lo que se quiere
decidir, y deja fuera al anónimo, que podría inflar los contadores sin coste.
El catálogo, el filtro de valores y el techo de series están en
``shared/eventos_producto.py``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from api.routes.dual_auth import require_any_auth
from observability.runtime_metrics import (
    producto_eventos_dimension_total,
    producto_eventos_total,
)
from shared.dto import EventoProductoIn
from shared.eventos_producto import PROPIEDADES, dimensiones
from shared.identity import Principal

router = APIRouter(tags=["telemetria"])


@router.post(
    "/telemetria/eventos",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Contar un evento de producto de la web (sin identificadores)",
    responses={422: {"description": "El evento no está en el catálogo"}},
)
async def post_evento_producto(
    body: EventoProductoIn,
    _ctx: Principal = Depends(require_any_auth),
) -> Response:
    if body.evento not in PROPIEDADES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Evento fuera del catálogo.",
        )
    producto_eventos_total.labels(evento=body.evento).inc()
    for propiedad, valor in dimensiones(body.evento, body.propiedades):
        producto_eventos_dimension_total.labels(
            evento=body.evento, propiedad=propiedad, valor=valor
        ).inc()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
