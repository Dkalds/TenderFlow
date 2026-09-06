"""Rutas /api/v1/radar — estado de triaje del Radar, persistido por usuario.

El descarte de señales vivía en ``React.useState``: el usuario triaba las 24
señales de la bandeja, recargaba, y volvían las 24 (invariante 2 de
``docs/frontend-data-invariants.md``). Estas rutas son su respaldo server-side.

CRUD simple sobre una tabla user-scoped: llaman a ``db.*`` directamente sin
capa de servicio intermedia, según ADR-024 (una capa que no transforma nada no
se añade).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from api.tenancy import resolve_organization_ctx
from db import radar_dismissals
from observability.logging import get_logger
from shared.cache import invalidate_user_scoped
from shared.dto import SafeStr

log = get_logger(__name__)

router = APIRouter(prefix="/radar", tags=["radar"])


def _user_key(ctx: dict[str, Any]) -> str:
    """Clave opaca y estable por usuario (la adjunta ``require_any_auth``)."""
    return str(ctx["user_key"])


async def _organizacion_activa(ctx: dict[str, Any]) -> int | None:
    """La organización desde la que el usuario pospone, o ``None``.

    Sólo hace falta para `posponer`: es lo que permite entregar el
    recordatorio, porque la campana lee `user_notifications` siempre con
    ámbito de organización y una alerta sin él no la ve nadie.

    Devuelve ``None`` —y el job no avisa, pero el aplazamiento sí oculta la
    señal— cuando la sesión no tiene usuario detrás (llamadas con API key) o
    cuando la resolución falla. Es la degradación correcta: posponer sin
    recordatorio sigue siendo útil; reventar el descarte porque no se pudo
    resolver una organización, no.
    """
    user_id = ctx.get("user_id")
    if user_id is None:
        return None
    try:
        resuelta = await resolve_organization_ctx(ctx, None)
    except Exception as exc:  # degradar, nunca romper el descarte por la organización
        log.warning("radar_dismissal_org_unresolved", error=str(exc)[:200])
        return None
    organization_id = resuelta.get("organization_id")
    return int(organization_id) if organization_id is not None else None


async def _resultado(user_key: str) -> RadarDismissalsResult:
    """La respuesta de las tres rutas: una sola lectura, no dos.

    `list_detalle` ya trae el id, así que pedir además `list_ids` sería una
    segunda consulta para derivar una columna que ya está en la mano — y dos
    consultas separadas pueden además discrepar si un descarte vence entre
    ellas.
    """
    filas = await run_db(radar_dismissals.list_detalle, user_key)
    detalle = [RadarDismissal(**fila) for fila in filas]
    return RadarDismissalsResult(ids=[d.id_externo for d in detalle], detalle=detalle)


def _invalidar_ranking(user_key: str) -> None:
    """Tira la caché del scoring de este usuario tras cambiar sus descartes.

    El Radar pide el ranking con ``exclude_dismissed=true`` y la respuesta se
    cachea 300 s: sin invalidar, descartar una señal la dejaría en pantalla
    hasta que expirase el TTL, y el hueco no lo ocuparía la siguiente.
    """
    invalidate_user_scoped("analytics", "scoring", user_key)


#: Vocabulario cerrado de bandas. Lo fija `_band()` en
#: `services/analytics/scoring.py`; aquí se valida para que un cliente no pueda
#: sembrar la tabla con etiquetas inventadas y volver inservible el análisis de
#: «qué banda concentra los descartes», que es para lo que existe la columna.
BANDAS_SCORE = ("Caliente", "Atractiva", "Tibia", "Descarte")


class RadarDismissalBody(BaseModel):
    """Cuerpo del descarte de una señal.

    ``score`` y ``banda`` son los que el usuario tenía **en pantalla** al
    descartar, y por eso los manda el cliente en vez de recalcularlos aquí: el
    score se computa en vivo sobre el universo del día y el perfil del usuario,
    así que recalcularlo en el servidor daría un número distinto del que motivó
    la decisión — que es justo el dato que se quiere conservar (revisión `v93`).

    Son opcionales a propósito: descartar es la acción, medir es el efecto
    secundario. Un cliente antiguo o una llamada por API siguen pudiendo
    descartar sin mandarlos, y la fila queda con `NULL`, que significa «no se
    supo» y no se rellena con nada inventado.
    """

    # `SafeStr` y no `str`: `id_externo` acaba en una columna de texto de
    # Postgres, que rechaza el byte NUL con un `DataError`. Sin esto la ruta
    # devolvía 500 ante un byte NUL que puede mandar cualquier cliente, en vez
    # del 422 con la ruta del campo que sí se puede corregir. Lo destapó el
    # fuzzer de contrato; el mismo precedente que `/licitaciones/bulk-get`.
    id_externo: SafeStr = Field(max_length=120)
    score: int | None = Field(default=None, ge=0, le=100)
    banda: Literal["Caliente", "Atractiva", "Tibia", "Descarte"] | None = None
    # F5.6 — qué clase de «quitar de la bandeja» pidió el usuario.
    #
    # `descartar` es el de siempre y no caduca. `silenciar` y `posponer`
    # necesitan `dias`; las dos ocultan la señal hasta esa fecha y sólo
    # `posponer` deja un recordatorio ese día. Son tres verbos y no un booleano
    # `permanente` porque la telemetría las separa: silenciar mide desinterés,
    # posponer mide trabajo aplazado.
    accion: Literal["descartar", "silenciar", "posponer"] = "descartar"
    # Tope de un año: por encima, «silenciar» es «descartar» con más pasos, y
    # una fecha a diez años vista sólo sirve para que la fila nunca caduque sin
    # que nadie lo haya decidido así. Mínimo 1: silenciar cero días es no hacer
    # nada, y aceptarlo dejaría una fila que ya nació vencida.
    dias: int | None = Field(default=None, ge=1, le=365)

    @model_validator(mode="after")
    def _coherencia_accion_dias(self) -> RadarDismissalBody:
        """`dias` es obligatorio para caducar, y prohibido para no caducar.

        Sin esto, `POST {accion: "silenciar"}` sin `dias` escribiría un
        descarte permanente que el usuario cree temporal — el peor de los dos
        fallos posibles, porque no se nota hasta que la señal no vuelve.
        """
        if self.accion == "descartar":
            if self.dias is not None:
                raise ValueError("`dias` no aplica a `descartar`: el descarte no caduca")
        elif self.dias is None:
            raise ValueError(f"`{self.accion}` necesita `dias`")
        return self


class RadarDismissal(BaseModel):
    """Un descarte vigente, con lo que hace falta para pintarlo."""

    id_externo: str
    #: ISO-8601. `None` = descarte permanente (el de v76).
    hasta: str | None = None
    accion: str | None = None
    score: int | None = None
    banda: str | None = None


class RadarDismissalsResult(BaseModel):
    """``id_externo`` que el usuario tiene descartados, recientes primero.

    ``ids`` sólo trae los **vigentes**: un silenciado que venció ya no está,
    porque a efectos del Radar ha vuelto a la bandeja. ``detalle`` es aditivo y
    lleva la fecha y la acción de cada uno, para que la consola pueda decir
    «silenciada hasta el 6 de octubre» en vez de sólo «descartada».
    """

    ids: list[str]
    detalle: list[RadarDismissal] = Field(default_factory=list)


@router.get("/dismissals", summary="Listar las señales descartadas por el usuario")
async def get_dismissals(
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> RadarDismissalsResult:
    return await _resultado(_user_key(ctx))


@router.post(
    "/dismissals",
    status_code=status.HTTP_201_CREATED,
    summary="Descartar una señal del Radar",
)
async def post_dismissal(
    body: RadarDismissalBody,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> RadarDismissalsResult:
    hasta = (
        (datetime.now(UTC) + timedelta(days=body.dias)).isoformat()
        if body.dias is not None
        else None
    )
    await run_db(
        radar_dismissals.add,
        _user_key(ctx),
        body.id_externo,
        score=body.score,
        banda=body.banda,
        hasta=hasta,
        organization_id=await _organizacion_activa(ctx) if body.accion == "posponer" else None,
        # `descartar` no escribe acción: la fila queda como las de v76, y así
        # `accion IS NULL` sigue significando exactamente «permanente».
        accion=None if body.accion == "descartar" else body.accion,
    )
    log.info(
        "radar_dismissal_created",
        id_externo=body.id_externo,
        accion=body.accion,
        dias=body.dias,
    )
    _invalidar_ranking(_user_key(ctx))
    return await _resultado(_user_key(ctx))


@router.delete(
    # ``:path`` y no el conversor por defecto: hay ``id_externo`` de PLACSP
    # con barras (p.ej. ``PA-S 2026/000058``). Con ``[^/]+`` este DELETE no
    # casaba y devolvía 404 antes del handler, así que esas señales quedaban
    # descartadas para siempre: el POST recibe el id en el body y sí las
    # acepta, de modo que se podían descartar pero nunca deshacer.
    "/dismissals/{id_externo:path}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deshacer el descarte de una señal",
)
async def delete_dismissal(
    id_externo: str,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> None:
    ok = await run_db(radar_dismissals.remove, _user_key(ctx), id_externo)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La señal no estaba descartada.",
        )
    _invalidar_ranking(_user_key(ctx))
