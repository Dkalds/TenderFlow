"""Rutas /api/v1/radar — triaje del Radar y bandeja «Próximas».

El descarte de señales vivía en ``React.useState``: el usuario triaba las 24
señales de la bandeja, recargaba, y volvían las 24 (invariante 2 de
``docs/frontend-data-invariants.md``). ``/radar/dismissals`` es su respaldo
server-side.

``/radar/proximas`` (T5) es la otra bandeja de la misma consola: las compras
que el órgano ya anunció pero que todavía no han salido a licitación. Vive aquí
y no en ``/licitaciones`` porque necesita una columna que el listado no publica
—``fecha_inicio``, la fecha prevista— y porque su universo es un juicio del
Radar, no un filtro más del catálogo.

CRUD simple sobre lecturas ya resueltas en ``db/``: llaman a ``db.*``
directamente sin capa de servicio intermedia, según ADR-024 (una capa que no
transforma nada no se añade).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from api.tenancy import resolve_organization_ctx
from db import radar_dismissals
from db.repositories.licitaciones import LicitacionRepository
from observability.logging import get_logger
from services.classification import ESTADOS_PRE_LICITACION
from shared.cache import invalidate_user_scoped
from shared.dto import RadarBanda, SafeStr

log = get_logger(__name__)

_lic_repo = LicitacionRepository()

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
    #: Vocabulario cerrado: un cliente no puede sembrar la tabla con etiquetas
    #: inventadas y volver inservible el análisis de «qué banda concentra los
    #: descartes», que es para lo que existe la columna. Se importa de
    #: ``shared.dto`` en vez de reescribir el ``Literal`` aquí — declararlo dos
    #: veces es lo que hacía indeterminista el enumerado del contrato; el
    #: porqué está en el comentario de ``RadarBanda``.
    banda: RadarBanda | None = None
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


# ── /radar/proximas — la bandeja «Próximas» (T5) ──────────────────────────

#: De dónde sale ``fecha_prevista``. Hoy tiene un solo valor, y ése es el
#: motivo de que exista: deja escrito en el contrato que la fecha **se lee** de
#: ``ProcurementProject/PlannedPeriod/cbc:StartDate`` y no se calcula. El
#: precedente es ``db/sql_fragments.FECHA_FIN_ORIGEN_SQL``, que nació porque el
#: 94 % del horizonte de renovaciones se estimaba y la UI lo presentaba como
#: fecha firme. Si algún día hay una segunda procedencia, el cliente podrá
#: distinguirlas en vez de enterarse por un cambio silencioso de significado.
FechaPrevistaOrigen = Literal["planned_period_start"]


class RadarProxima(BaseModel):
    """Una compra anunciada que todavía no ha salido a licitación.

    No lleva ``score`` ni ``band``: el scoring del Radar ordena expedientes con
    plazo vivo, y aquí no hay plazo al que presentarse. Puntuar estas filas
    exigiría inventar la dimensión que falta, que es justo lo que ADR-014
    prohíbe; la bandeja se ordena por fecha prevista y lo dice.
    """

    id_externo: str
    titulo: str | None = None
    organo_contratacion: str | None = None
    importe: float | None = None
    #: ``PRE`` o ``CPM``, en crudo. La etiqueta la pone el cliente con su propia
    #: tabla (``web/src/lib/estados.ts``), igual que en el resto de la API.
    estado: str | None = None
    fecha_publicacion: str | None = None
    #: Fecha prevista de la compra, o ``None`` cuando la fuente no la publica —
    #: que es el caso mayoritario. ``None`` significa «sin fecha» y no se
    #: sustituye por una estimación: ver :data:`FechaPrevistaOrigen`.
    fecha_prevista: str | None = None
    ccaa: str | None = None
    cpv: str | None = None
    url: str | None = None
    tecnologia: str | None = None


class RadarProximasResult(BaseModel):
    """La bandeja «Próximas» con su universo declarado.

    ``total`` y ``con_fecha_prevista`` son del universo entero, no de la página
    servida: sin ese denominador el cliente no puede decir «3 de 47 traen
    fecha» sin derivarlo de lo que le llegó, que es la fabricación de analítica
    que prohíbe ADR-014.
    """

    items: list[RadarProxima]
    #: Cuántos expedientes cumplen el filtro en total.
    total: int
    #: De esos ``total``, cuántos traen fecha prevista publicada.
    con_fecha_prevista: int
    limit: int
    offset: int
    #: Los códigos que definen la bandeja, tal como los aplicó el servidor. El
    #: cliente no los reescribe: si mañana el universo cambia, la cabecera de la
    #: pantalla cambia con él en vez de seguir prometiendo lo de ayer.
    estados: list[str]
    fecha_prevista_origen: FechaPrevistaOrigen = "planned_period_start"


@router.get(
    "/proximas",
    summary="Bandeja «Próximas»: anuncios previos y consultas preliminares abiertos",
    responses={
        200: {"description": "Compras anunciadas que aún no han salido a licitación"},
        401: {"description": "No autenticado"},
    },
)
async def get_proximas(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> RadarProximasResult:
    """Lista **sólo** ``PRE`` y ``CPM`` abiertos, con su fecha prevista si la hay.

    Los dos códigos salen de ``services.classification.ESTADOS_PRE_LICITACION``
    y no se teclean aquí. «Abierto» es el mismo juicio que en el resto del
    Radar (``shared.estados``): por exclusión de los terminales, no por lista
    blanca.

    **Esta bandeja está casi siempre vacía o muy corta, y eso es el dato.** El
    spike de T5 (``docs/plans/2026-09-spike-planes-anuales-placsp.md``) midió
    1.403 entradas del feed vivo de PLACSP: ``PRE`` es el 0,14 % y ``CPM`` ni
    siquiera está en la lista de estados de sindicación —el ``CPM`` de la base
    entra por las plataformas autonómicas vía la migración ``v91``—. Una
    respuesta con cero elementos no es un fallo del endpoint.
    """
    items, total, con_fecha = await run_db(
        _lic_repo.proximas,
        estados=ESTADOS_PRE_LICITACION,
        limit=limit,
        offset=offset,
    )
    return RadarProximasResult(
        items=[
            RadarProxima(
                id_externo=str(fila["id_externo"]),
                titulo=fila.get("titulo"),
                organo_contratacion=fila.get("organo_contratacion"),
                importe=fila.get("importe"),
                estado=fila.get("estado"),
                fecha_publicacion=fila.get("fecha_publicacion"),
                # El renombrado es el contrato: la columna se llama
                # `fecha_inicio` porque guarda el inicio de ejecución previsto,
                # y en esta bandeja se lee como «para cuándo está prevista la
                # compra». Es el mismo dato con el nombre que tiene aquí.
                fecha_prevista=fila.get("fecha_inicio"),
                ccaa=fila.get("ccaa"),
                cpv=fila.get("cpv"),
                url=fila.get("url"),
                tecnologia=fila.get("tecnologia"),
            )
            for fila in items
        ],
        total=total,
        con_fecha_prevista=con_fecha,
        limit=limit,
        offset=offset,
        estados=list(ESTADOS_PRE_LICITACION),
    )
