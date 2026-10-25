"""API colaborativa de oportunidades.

Las rutas de organizaciones viven en :mod:`api.routes.organizations`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote, unquote

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from pydantic import BaseModel, Field

from api.concurrency import run_db
from api.pagination import PageParams, pagina
from api.routes.dual_auth import require_any_auth
from observability.logging import get_logger
from services.carga_equipo import CargaEquipo, carga_del_equipo
from services.cartera import (
    CarteraNoEncontradaError,
    CarteraResumen,
    ContratoCartera,
    ContratoEvento,
    FechaFinInvalidaError,
    FechaFinManualIn,
    PrepararRenovacionIn,
    RenovacionInvalidaError,
    RenovacionPreparada,
    cartera_de_usuario,
    eventos_de_contrato,
    fijar_fecha_fin,
    preparar_renovacion,
    resumen_de_usuario,
)
from services.direccion import (
    CuadroDireccion,
    FeedActividad,
    actividad_de_organizacion,
    cuadro_de_direccion,
)
from services.kit_presentacion import KitPresentacion
from services.organizations import (
    OrganizationAccessError,
    OrganizationPermissionError,
)
from services.pursuit_comments import (
    PursuitCommentNotFoundError,
    add_comment,
    delete_comment,
    list_comments,
)
from services.pursuits import (
    PesosPropuestos,
    PesosPropuestosAplicados,
    PursuitConflictError,
    PursuitNotFoundError,
    PursuitTransitionError,
    PursuitValidationError,
    apply_weights_proposal,
    asignar_kit_de_pursuit,
    create_pursuit,
    ficha_pdf,
    get_agenda,
    get_metrics,
    get_pursuit,
    get_weights_proposal,
    kit_de_pursuit,
    list_pursuits,
    marcar_kit_de_pursuit,
    update_pursuit,
)
from shared.dto import (
    PipelineAgendaResponse,
    PursuitCommentCreate,
    PursuitCommentListResponse,
    PursuitCommentOut,
    PursuitCreate,
    PursuitDetail,
    PursuitListResponse,
    PursuitMetrics,
    PursuitPlazo,
    PursuitStatus,
    PursuitSummary,
    PursuitUpdate,
)

log = get_logger(__name__)
router = APIRouter(tags=["pursuits"])


# ── DTOs de captura: tareas, go/no-go y «mi baja» (C6) ──────────────────────
#
# Van arriba, junto al router, y no al lado de sus rutas: los `response_model`
# se evalúan al importar el módulo, así que una clase declarada después de la
# ruta que la usa rompe el import con un NameError.


class PursuitTaskCreate(BaseModel):
    """Alta de una tarea. `vence` es `YYYY-MM-DD` o ausente."""

    titulo: str = Field(..., min_length=1, max_length=300)
    responsable_user_id: int | None = Field(default=None, ge=1)
    vence: str | None = Field(default=None, max_length=10)


class PursuitTaskPatch(BaseModel):
    """Cambios sobre una tarea. Ausente = no tocar.

    `limpiar_responsable` y `limpiar_vence` existen porque `null` ya significa
    «no tocar»: sin ellos, quitarle la fecha a una tarea sería imposible, o bien
    no mandarla la borraría sin querer.
    """

    titulo: str | None = Field(default=None, min_length=1, max_length=300)
    responsable_user_id: int | None = Field(default=None, ge=1)
    vence: str | None = Field(default=None, max_length=10)
    estado: str | None = Field(
        default=None, description="pendiente | en_curso | hecha | descartada"
    )
    limpiar_responsable: bool = False
    limpiar_vence: bool = False


class PursuitTaskOut(BaseModel):
    id: int
    pursuit_id: int
    organization_id: int
    titulo: str
    responsable_user_id: int | None = None
    responsable_name: str | None = None
    vence: str | None = None
    estado: str
    created_at: str
    updated_at: str


class PursuitAttachmentOut(BaseModel):
    """Un adjunto propio. **Nunca** lleva la `blob_key`.

    La clave del objeto es una coordenada interna del bucket: publicarla
    invitaría a construir URLs a mano contra el almacen, que es justo lo que el
    enlace firmado de `GET /pursuits/adjuntos/{id}/enlace` evita.
    """

    id: int
    pursuit_id: int
    organization_id: int
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    uploaded_by_user_id: int | None = None
    uploaded_by_name: str | None = None
    #: Opt-in del RAG por adjunto (C6.3). `false` mientras nadie lo levante.
    indexable: bool = False
    created_at: str


class PursuitAttachmentLink(BaseModel):
    """Ruta firmada de descarga y el instante en que deja de valer (epoch)."""

    path: str
    expira_en: int


class PursuitAttachmentIndexableIn(BaseModel):
    indexable: bool


class TipoAdjuntoOut(BaseModel):
    """Un tipo de la lista blanca y las extensiones que le corresponden."""

    content_type: str
    extensiones: list[str]


class PursuitAttachmentPolicy(BaseModel):
    """Lo que la consola necesita saber antes de ofrecer «Subir adjunto».

    Sale de las mismas constantes con las que el servidor valida la subida: la
    pantalla no lleva su propia copia de la lista blanca ni del tope, y un
    entorno sin almacén lo dice aquí en vez de con un 503 tras enviar el fichero.
    """

    almacen_disponible: bool
    max_bytes: int
    tipos: list[TipoAdjuntoOut]


class GoNoGoCriterioOut(BaseModel):
    criterio: str
    etiqueta: str
    invertido: bool
    peso: float | None = None
    puntuacion: int | None = None
    motivo: str | None = None
    author_name: str | None = None


class GoNoGoWeightsOut(BaseModel):
    organization_id: int
    umbral: float
    criterios: list[GoNoGoCriterioOut]


class GoNoGoWeightsIn(BaseModel):
    """Pesos por criterio. Los ausentes conservan su valor guardado."""

    pesos: dict[str, float]


class GoNoGoScoreIn(BaseModel):
    criterio: str
    puntuacion: int = Field(..., ge=1, le=5)
    motivo: str | None = Field(default=None, max_length=1000)


class GoNoGoScoreOut(BaseModel):
    pursuit_id: int
    organization_id: int
    criterios: list[GoNoGoCriterioOut]
    total: float
    umbral: float
    recomendacion: str
    criterios_puntuados: int
    completa: bool
    decision: str | None = None
    discrepa: bool


class MiBajaSegmento(BaseModel):
    segmento: str
    clave: str
    n: int
    baja_propia_pct: float | None = None
    baja_mercado_pct: float | None = None
    contratos_mercado: int
    suficiente: bool
    delta_pct: float | None = None


class MiBajaOut(BaseModel):
    organization_id: int
    base: str
    ofertas_consideradas: int
    segmentos: list[MiBajaSegmento]


@router.post(
    "/pursuits",
    response_model=PursuitSummary,
    status_code=status.HTTP_201_CREATED,
)
async def post_pursuit(
    body: PursuitCreate,
    idempotency_key: str | None = Header(
        default=None,
        alias="X-Idempotency-Key",
        max_length=200,
    ),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PursuitSummary:
    """Abre una oportunidad; reintentar la misma licitación no duplica.

    Abrirla es la señal de demanda más fuerte que existe, así que si el
    expediente no tiene ficha del pliego se encola su extracción
    (``PLIEGO_FACTS_ON_PURSUIT``): quien acaba de comprometerse abrirá la
    pestaña Pliego hoy, no cuando el lote nocturno llegue a ese expediente.
    """
    try:
        pursuit, created = await run_db(
            create_pursuit,
            int(ctx["user_id"]),
            body,
            idempotency_key=idempotency_key,
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if created:
        await _lanzar_ficha_si_falta(pursuit.licitacion_id, pursuit.organization_id, ctx)
    return pursuit


async def _lanzar_ficha_si_falta(
    licitacion_id: str, organization_id: int, ctx: dict[str, Any]
) -> None:
    """Encola la extracción de la ficha si no existe. Nunca falla la creación.

    Va por la cola (ADR-028) y no por ``BackgroundTasks``, por tres motivos que
    se veían en producción: la tarea en el proceso de la API moría con cada
    despliegue; ``…/ficha-pliego/estado`` mira la cola, así que la pestaña
    Pliego ofrecía «Extraer ficha» mientras la extracción corría, y un clic la
    encolaba otra vez; y un fallo que no fuera «sin páginas» no dejaba fila, ni
    reintento, ni rastro fuera del log (``No module named 'pybreaker'``, el
    2026-09-28, fue exactamente eso). Encolar es idempotente por expediente.
    """
    from config import settings

    if not settings.PLIEGO_FACTS_ON_PURSUIT:
        return
    try:
        from services.jobs import TIPO_FICHA_PLIEGO, enqueue
        from services.rag.fact_sheet import get_fact_sheet

        if await run_db(get_fact_sheet, licitacion_id) is not None:
            return
        raw_subject = ctx.get("user_key")
        budget_subject = raw_subject if isinstance(raw_subject, str) and raw_subject else None
        job_id = await run_db(
            enqueue,
            TIPO_FICHA_PLIEGO,
            {
                "licitacion_id": licitacion_id,
                "model": settings.PLIEGO_FACTS_MODEL,
                "budget_subject": budget_subject,
            },
            organization_id=organization_id,
        )
        log.info(
            "pursuit_fact_sheet_extraction_encolada", licitacion_id=licitacion_id, job_id=job_id
        )
    except Exception as exc:
        log.warning(
            "pursuit_fact_sheet_extraction_skipped",
            licitacion_id=licitacion_id,
            error=str(exc)[:200],
        )


@router.get("/pursuits", response_model=PursuitListResponse)
async def get_pursuits(
    organization_id: int | None = Query(default=None, ge=1),
    pursuit_status: PursuitStatus | None = Query(default=None, alias="status"),
    responsible_user_id: int | None = Query(default=None, ge=1),
    q: str | None = Query(
        default=None,
        max_length=200,
        description=(
            "Texto en el título del expediente, su referencia o el nombre del "
            "responsable; sin distinguir acentos ni mayúsculas."
        ),
    ),
    etiqueta: int | None = Query(
        default=None, ge=1, description="Sólo oportunidades con esta etiqueta de la organización."
    ),
    plazo: PursuitPlazo | None = Query(
        default=None,
        description=(
            "Plazo de presentación del expediente, sobre oportunidades abiertas y "
            "sin presentar: `vencido` (el día ya pasó), `7d` o `30d` (vence de hoy "
            "a dentro de N días, inclusive)."
        ),
    ),
    page: PageParams = Depends(pagina(50)),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PursuitListResponse:
    """Lista únicamente opportunities de una organización autorizada.

    Los filtros van en el `WHERE` y el `total` es el del conjunto filtrado: el
    tablero los usa en vez de filtrar la página que ya tiene, que con más de una
    página escondía lo que no había llegado.
    """
    try:
        return await run_db(
            list_pursuits,
            int(ctx["user_id"]),
            organization_id=organization_id,
            status=pursuit_status,
            responsible_user_id=responsible_user_id,
            q=q,
            etiqueta_id=etiqueta,
            plazo=plazo,
            limit=page.limit,
            offset=page.offset,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/pursuits/metrics", response_model=PursuitMetrics)
async def get_pursuit_metrics(
    organization_id: int | None = Query(default=None, ge=1),
    period_from: datetime | None = Query(default=None),
    period_to: datetime | None = Query(default=None),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PursuitMetrics:
    """Calcula funnel, win-rate, importe y tiempo de decisión."""
    try:
        return await run_db(
            get_metrics,
            int(ctx["user_id"]),
            organization_id=organization_id,
            period_from=period_from,
            period_to=period_to,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/pursuits/agenda", response_model=PipelineAgendaResponse)
async def get_pursuits_agenda(
    organization_id: int | None = Query(default=None, ge=1),
    solo_mios: bool = Query(
        default=False,
        description="Limita pursuits y tareas a los que el usuario es responsable",
    ),
    tecnologia: str | None = Query(
        default=None,
        max_length=500,
        description="Uno o varios códigos separados por comas (OR): `SAP,Oracle`",
    ),
    ccaa: str | None = Query(
        default=None,
        max_length=500,
        description="Una o varias CCAA separadas por comas (OR)",
    ),
    incluir_mercado: bool = Query(
        default=False,
        description=(
            "Fusiona también las renovaciones del mercado (`kind=renovacion`): "
            "contratos ajenos que vencen en el horizonte. No son compromisos de "
            "la organización y por eso no entran por defecto."
        ),
    ),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PipelineAgendaResponse:
    """Agenda de compromisos: fusión, orden y bandas calculados en backend.

    Cada fila lleva una sola fecha y dice de qué clase es (`due_kind`): plazo
    de presentación (`pursuit`, `senal`), vencimiento de una tarea (`tarea`),
    inicio de la ventana de relicitación o fin efectivo de un contrato propio
    (`contrato`). Las renovaciones del mercado sólo entran con
    `incluir_mercado=true`.

    `banda` es el tramo en el que va la fila: su `urgencia`, salvo cuando el
    plazo ya no obliga (`plazo_pasado`: pasó sin oferta; `en_resolucion`: la
    oferta está presentada). `contadores` son los de la franja, y cada fila
    declara en `cuenta_en` en cuáles cuenta.

    Sin caché compartida: la respuesta es por usuario/organización (incluye el
    triaje de señales del propio usuario).
    """
    try:
        return await run_db(
            get_agenda,
            int(ctx["user_id"]),
            user_key=str(ctx["user_key"]),
            organization_id=organization_id,
            solo_mios=solo_mios,
            tecnologia=tecnologia,
            ccaa=ccaa,
            incluir_mercado=incluir_mercado,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/pursuits/weights-proposal", response_model=PesosPropuestos)
async def get_pursuits_weights_proposal(
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PesosPropuestos:
    """Propone un ajuste de los pesos del Radar a partir de lo ganado y perdido.

    Compara, dimensión a dimensión, el desglose del score que tenían las
    oportunidades ganadas frente al de las perdidas: la dimensión que valía más
    en las ganadas sube y la que valía más en las perdidas baja, en una
    redistribución que sigue sumando 100.

    Sólo cuentan las oportunidades cerradas cuyo desglose quedó sellado al
    abrirlas. Por debajo del mínimo devuelve `estado: "insuficiente"` con su
    base, y ninguna propuesta: un ajuste sobre cuatro cierres no es evidencia.

    Es una propuesta. No se aplica sola.
    """
    try:
        return await run_db(
            get_weights_proposal,
            int(ctx["user_id"]),
            user_key=str(ctx["user_key"]),
            organization_id=organization_id,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get(
    "/pursuits/cartera",
    summary="Contratos ganados que siguen en ejecución (F4.3)",
    responses={403: {"description": "No perteneces a esa organización"}},
)
async def get_cartera(
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> list[ContratoCartera]:
    """La cartera, con la ventana de relicitación de cada contrato.

    Se declara siempre de dónde sale la fecha de fin (`fecha_fin_origen`): una
    publicada por la fuente y una derivada de la duración no valen lo mismo en
    la pantalla donde se decide cuándo preparar una renovación.
    """

    try:
        return await run_db(
            cartera_de_usuario, int(ctx["user_id"]), organization_id=organization_id
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get(
    "/pursuits/cartera/resumen",
    response_model=CarteraResumen,
    summary="Agregados de la cartera: vivos, importe en ejecución y vencimientos a seis meses",
    responses={403: {"description": "No perteneces a esa organización"}},
)
async def get_cartera_resumen(
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> CarteraResumen:
    """Los totales de la cartera, calculados en backend (ADR-014).

    Mismo ámbito y permisos que `GET /pursuits/cartera`: quien puede leer la
    cartera puede leer sus totales. Un contrato cuenta como vivo si no tiene
    fecha de fin o si ésta no ha pasado; `sin_renovacion_preparada` es, de los
    que vencen en seis meses, cuántos no tienen todavía oportunidad de
    renovación.
    """
    try:
        return await run_db(
            resumen_de_usuario, int(ctx["user_id"]), organization_id=organization_id
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get(
    "/pursuits/cartera/{cartera_id}/eventos",
    response_model=list[ContratoEvento],
    summary="Eventos del contrato vigente de una entrada de cartera",
    responses={
        403: {"description": "No perteneces a esa organización"},
        404: {"description": "El contrato no está en la cartera de la organización"},
    },
)
async def get_cartera_eventos(
    cartera_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> list[ContratoEvento]:
    """Qué le pasó al contrato después de ganarlo, del más antiguo al más nuevo.

    Son los eventos de `contrato_eventos` (los mismos de los que la cartera
    cuenta las prórrogas): adjudicación, formalización, modificaciones de
    importe, prórrogas, anulación. `importe_delta_eur` sólo viene en las
    modificaciones de importe.
    """
    try:
        return await run_db(
            eventos_de_contrato,
            int(ctx["user_id"]),
            cartera_id,
            organization_id=organization_id,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except CarteraNoEncontradaError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch(
    "/pursuits/cartera/{cartera_id}",
    response_model=ContratoCartera,
    summary="Poner a mano la fecha de fin de un contrato en cartera",
    responses={
        403: {"description": "No perteneces a esa organización o no puedes escribir"},
        404: {"description": "El contrato no está en la cartera de la organización"},
        422: {"description": "La fecha no puede ser el fin de ese contrato"},
    },
)
async def patch_cartera_fecha_fin(
    cartera_id: int,
    body: FechaFinManualIn,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> ContratoCartera:
    """Fija la fecha de fin que la fuente no publicó, con origen `manual`.

    Devuelve el contrato como queda, con su ventana de relicitación ya
    calculada sobre la fecha nueva. La resincronización diaria no pisa una
    fecha puesta por aquí: quien la corrige a mano sabe algo que la fuente no
    dijo.
    """
    try:
        return await run_db(
            fijar_fecha_fin,
            int(ctx["user_id"]),
            cartera_id,
            body.fecha_fin,
            organization_id=organization_id,
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except CarteraNoEncontradaError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FechaFinInvalidaError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/pursuits/cartera/{cartera_id}/renovacion",
    response_model=RenovacionPreparada,
    summary="Preparar la renovación de un contrato en cartera (F4.3)",
    responses={
        403: {"description": "No perteneces a esa organización o no puedes escribir"},
        404: {"description": "El contrato no está en la cartera de la organización"},
        422: {"description": "El expediente no sirve como relicitación"},
    },
)
async def post_cartera_renovacion(
    cartera_id: int,
    body: PrepararRenovacionIn,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> RenovacionPreparada:
    """Crea la oportunidad de la relicitación, enlazada al contrato.

    Idempotente: si el contrato ya tenía oportunidad de renovación, devuelve
    esa con ``creada=false`` y no crea otra.
    """
    try:
        return await run_db(
            preparar_renovacion,
            int(ctx["user_id"]),
            cartera_id,
            body.licitacion_id,
            organization_id=organization_id,
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except CarteraNoEncontradaError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RenovacionInvalidaError, PursuitValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/pursuits/weights-proposal/apply", response_model=PesosPropuestosAplicados)
async def post_pursuits_weights_proposal_apply(
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PesosPropuestosAplicados:
    """Aplica la propuesta vigente al perfil de scoring. Queda en el audit log.

    No admite pesos en el cuerpo: recalcula la propuesta y escribe exactamente
    esa, de modo que lo aplicado y lo que se enseñó no puedan divergir. El resto
    del perfil (keywords de afinidad, CPV, rango de importe) se conserva.

    Responde 422 mientras la propuesta sea insuficiente.
    """
    try:
        return await run_db(
            apply_weights_proposal,
            int(ctx["user_id"]),
            user_key=str(ctx["user_key"]),
            organization_id=organization_id,
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/pursuits/direccion",
    summary="Cuadro de mando de dirección (F4.2) — solo owner y admin",
    responses={403: {"description": "Dirección es para owner y admin"}},
)
async def get_direccion(
    organization_id: int | None = Query(default=None, ge=1),
    period_from: datetime | None = Query(
        default=None, description="Inicio de la ventana de **cierres** (incluido)"
    ),
    period_to: datetime | None = Query(
        default=None, description="Fin de la ventana de cierres (excluido); sin él, ahora"
    ),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> CuadroDireccion:
    """El control de rol está **en el servicio**, no en el rail.

    Un `member` que teclee la URL recibe 403, no una pantalla sin enlace: un
    rail sin enlace es una sugerencia, esto es un permiso.

    Cada tarjeta lleva universo, `n` y mínimo; por debajo del mínimo sale sin
    `valor` y con la `nota` que dice por qué, nunca con un número inventado.
    Con ventana, cada tarjeta trae además la del mismo periodo de hace un año
    y la diferencia (`anterior`, `delta`).
    """
    try:
        return await run_db(
            cuadro_de_direccion,
            int(ctx["user_id"]),
            organization_id,
            period_from=period_from,
            period_to=period_to,
        )
    except OrganizationPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/pursuits/direccion/carga",
    summary="Carga del equipo: abiertas y avisos por responsable — solo owner y admin",
    responses={403: {"description": "Dirección es para owner y admin"}},
)
async def get_direccion_carga(
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> CargaEquipo:
    """Quién tiene qué abierto hoy y qué de eso pide atención.

    Mismo permiso que el cuadro, comprobado en el servicio. Una fila por
    miembro activo, también los que no tienen nada abierto.
    """
    try:
        return await run_db(carga_del_equipo, int(ctx["user_id"]), organization_id)
    except (OrganizationPermissionError, OrganizationAccessError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get(
    "/pursuits/actividad",
    summary="Feed de lo que hizo el equipo (F4.5)",
    responses={403: {"description": "No perteneces a esa organización"}},
)
async def get_actividad(
    organization_id: int | None = Query(default=None, ge=1),
    antes_de_id: int | None = Query(
        default=None, ge=1, description="Cursor: id del último evento de la página anterior"
    ),
    usuario: int | None = Query(default=None, ge=1, description="Filtrar por quién lo hizo"),
    limit: int = Query(50, ge=1, le=200),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> FeedActividad:
    """Paginado **por cursor de id** y no por `offset`.

    El ledger es append-only, así que el id ya es el orden temporal; con
    `created_at` dos eventos del mismo segundo podrían repetirse o perderse
    entre páginas.

    Un `member` recibe el feed acotado a los eventos que puede ver, y la
    respuesta lo declara (`filtrado_por_rol`) en vez de dejarle creer que no
    ha pasado nada.
    """
    try:
        return await run_db(
            actividad_de_organizacion,
            int(ctx["user_id"]),
            organization_id=organization_id,
            antes_de_id=antes_de_id,
            solo_usuario=usuario,
            limit=limit,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


# ── Rutas estáticas bajo /pursuits ───────────────────────────────────────────
#
# Van **antes** de `/pursuits/{pursuit_id}` a propósito: FastAPI resuelve por
# orden de declaración, así que declaradas después, `GET /pursuits/mi-baja`
# entraría por el detalle con `pursuit_id="mi-baja"` y devolvería un 422 que no
# dice nada. Es el mismo motivo por el que `/pursuits/metrics` y
# `/pursuits/agenda` están donde están. `tests/test_c6_captura.py` fija el orden
# para que un añadido futuro no lo rompa en silencio.


@router.get("/pursuits/tasks/agenda", response_model=list[PursuitTaskOut])
async def get_tasks_agenda(
    organization_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=500),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> list[PursuitTaskOut]:
    """Tareas abiertas de la organización por urgencia (Mi Pipeline → Agenda)."""
    from services.pursuit_tasks import agenda

    try:
        filas = await run_db(
            agenda, int(ctx["user_id"]), organization_id=organization_id, limit=limit
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return [PursuitTaskOut.model_validate(f) for f in filas]


# ── Adjuntos propios (C6.3) ────----------------------------------------------
#
# Estas cuatro cuelgan de `/pursuits/adjuntos/{attachment_id}` y no de
# `/pursuits/{pursuit_id}/adjuntos/{id}`: el adjunto ya sabe de qué oportunidad
# es, y repetir el `pursuit_id` en la URL crea un segundo sitio donde el cliente
# puede equivocarse sin que el servidor lo note. Por eso van aquí arriba, con
# las demás estáticas.


@router.get("/pursuits/adjuntos/politica", response_model=PursuitAttachmentPolicy)
async def get_adjuntos_politica(
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> PursuitAttachmentPolicy:
    """Si este entorno acepta adjuntos, el tope por fichero y los tipos admitidos.

    Sin organización: la lista blanca y el tope son del producto y el almacén es
    del despliegue, iguales para todos. Lo que sí depende de la organización —si
    quien mira puede subir— lo decide su rol, y la subida lo vuelve a comprobar.
    """
    from services.pursuit_attachments import politica

    # Al threadpool: resolver el almacén la primera vez construye el cliente de
    # boto3, y eso no puede correr sobre el event loop del único proceso.
    vigente = await run_db(politica)
    return PursuitAttachmentPolicy(
        almacen_disponible=vigente.almacen_disponible,
        max_bytes=vigente.max_bytes,
        tipos=[
            TipoAdjuntoOut(content_type=tipo, extensiones=list(extensiones))
            for tipo, extensiones in vigente.tipos
        ],
    )


@router.get("/pursuits/adjuntos/{attachment_id}/enlace", response_model=PursuitAttachmentLink)
async def get_adjunto_enlace(
    attachment_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PursuitAttachmentLink:
    """Emite un enlace de descarga **firmado y con caducidad**.

    La autorización se comprueba **aquí**, con la sesión delante; el enlace que
    sale ya no la necesita, y por eso dura diez minutos y no un día.
    """
    from services.pursuit_attachments import firmar_descarga, obtener

    try:
        fila = await run_db(
            obtener,
            int(ctx["user_id"]),
            attachment_id,
            organization_id=organization_id,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if fila is None:
        raise HTTPException(status_code=404, detail="Adjunto no encontrado.")

    enlace = firmar_descarga(attachment_id)
    return PursuitAttachmentLink(path=enlace.path, expira_en=enlace.expira_en)


@router.get(
    "/pursuits/adjuntos/{attachment_id}/descargar",
    response_class=Response,
    responses={
        200: {"content": {"application/octet-stream": {}}, "description": "El fichero"},
        403: {"description": "Enlace caducado o firma inválida"},
        404: {"description": "No existe, o no es de tu organización"},
    },
)
async def get_adjunto_descarga(
    attachment_id: int,
    exp: int = Query(description="Caducidad del enlace (epoch); es parte de lo firmado"),
    t: str = Query(description="Firma HMAC emitida por `/enlace`"),
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> Response:
    """Sirve el binario si la firma vale y no ha caducado.

    **403 y no 410** para el enlace caducado: 410 diría que el recurso existió y
    ya no está, y el fichero sigue ahí — lo que caducó es el permiso.

    Sigue exigiendo sesión: la firma acota *qué* adjunto y *hasta cuándo*, no
    sustituye a la autenticación. Un enlace reenviado por correo no abre nada a
    quien no pertenezca ya a la organización.
    """
    from services.pursuit_attachments import descargar, verificar_descarga

    if not verificar_descarga(attachment_id, exp=exp, token=t):
        raise HTTPException(
            status_code=403,
            detail="El enlace de descarga ha caducado o su firma no es válida.",
        )

    try:
        resultado = await run_db(
            descargar,
            int(ctx["user_id"]),
            attachment_id,
            organization_id=organization_id,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if resultado is None:
        raise HTTPException(status_code=404, detail="Adjunto no encontrado.")

    fila, contenido = resultado
    return Response(
        content=contenido,
        media_type=str(fila["content_type"]),
        headers={"Content-Disposition": _content_disposition(str(fila["filename"]))},
    )


def _content_disposition(nombre: str) -> str:
    """``attachment`` con el nombre en ASCII y, entero, en ``filename*`` (RFC 5987).

    Las cabeceras de respuesta viajan en Latin-1: un ``filename="Oferta Łódź.pdf"``
    a secas no se puede ni escribir y la descarga respondía 500. El nombre
    saneado admite cualquier letra (``\\w`` Unicode), así que no basta con
    confiar en él. El navegador prefiere ``filename*``; el ``filename`` en ASCII
    queda para quien no lo entienda.
    """
    ascii_ = nombre.encode("ascii", "replace").decode("ascii").replace('"', "_")
    return f"attachment; filename=\"{ascii_}\"; filename*=UTF-8''{quote(nombre, safe='')}"


@router.put(
    "/pursuits/adjuntos/{attachment_id}/indexable",
    response_model=PursuitAttachmentOut,
)
async def put_adjunto_indexable(
    attachment_id: int,
    body: PursuitAttachmentIndexableIn,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PursuitAttachmentOut:
    """Levanta o baja el opt-in del RAG **para un adjunto concreto**.

    Por adjunto y no por organización: una propuesta puede llevar el CV de
    alguien y el pliego técnico en el mismo expediente, y un permiso global
    obligaría a decidir por el conjunto.
    """
    from services.pursuit_attachments import marcar_indexable

    try:
        fila = await run_db(
            marcar_indexable,
            int(ctx["user_id"]),
            attachment_id,
            indexable=body.indexable,
            organization_id=organization_id,
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if fila is None:
        raise HTTPException(status_code=404, detail="Adjunto no encontrado.")
    return PursuitAttachmentOut.model_validate(fila)


@router.delete(
    "/pursuits/adjuntos/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_adjunto(
    attachment_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> None:
    """Borra el adjunto y su binario del almacén."""
    from services.pursuit_attachments import borrar

    try:
        borrado = await run_db(
            borrar, int(ctx["user_id"]), attachment_id, organization_id=organization_id
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if not borrado:
        raise HTTPException(status_code=404, detail="Adjunto no encontrado.")


# ── Plantilla go/no-go (C6.4, D30) ───────────────────────────────────────────


@router.get("/pursuits/mi-baja", response_model=MiBajaOut)
async def get_mi_baja(
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> MiBajaOut:
    """Mi baja media por CPV4 y por órgano, frente a la del mercado.

    `suficiente` dice si el segmento llega a las cinco ofertas que el ítem
    exige; los que no llegan salen igual **con su `n`**, porque saber que solo
    hay dos es información y no saberlo es lo que engaña.
    """
    from services.mi_baja import mi_baja

    try:
        return MiBajaOut.model_validate(
            await run_db(mi_baja, int(ctx["user_id"]), organization_id=organization_id)
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/pursuits/{pursuit_id}", response_model=PursuitDetail)
async def get_pursuit_detail(
    pursuit_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PursuitDetail:
    try:
        return await run_db(
            get_pursuit,
            int(ctx["user_id"]),
            pursuit_id,
            organization_id=organization_id,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/pursuits/{pursuit_id}/ficha.pdf",
    # `response_class`: la respuesta es el fichero, no un 200 JSON que
    # documentar. Mismo patrón que `api/routes/exports.py`.
    response_class=Response,
    summary="Ficha de la oportunidad en PDF (one-pager para dirección)",
    responses={
        200: {"content": {"application/pdf": {}}, "description": "El PDF"},
        403: {"description": "La oportunidad es de otra organización"},
        404: {"description": "No existe"},
    },
)
async def get_pursuit_ficha_pdf(
    pursuit_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> Response:
    """F2.7 — el one-pager que se lleva a un comité.

    Va por la misma lectura con ámbito que `GET /pursuits/{id}`: un 403 aquí y
    un 403 allí son el mismo control, no dos.
    """
    try:
        pdf = await run_db(
            ficha_pdf,
            int(ctx["user_id"]),
            pursuit_id,
            organization_id=organization_id,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            # `inline`: el usuario quiere verla antes de decidir si la guarda.
            "Content-Disposition": f'inline; filename="oportunidad-{pursuit_id}.pdf"',
        },
    )


class KitItemBody(BaseModel):
    """Marcado (o desmarcado) de un documento del kit."""

    clave: str = Field(min_length=1, max_length=120)
    listo: bool


class KitResponsableBody(BaseModel):
    """Responsable de un documento del kit. Se guarda como tarea (C6.1)."""

    clave: str = Field(min_length=1, max_length=120)
    responsable_user_id: int = Field(ge=1)
    #: `YYYY-MM-DD`, o ausente para no fijar (ni tocar) el plazo.
    vence: str | None = Field(default=None, max_length=10)


@router.get(
    "/pursuits/{pursuit_id}/kit",
    summary="Kit de presentación: documentos que exige el pliego y cuáles están listos",
    responses={403: {"description": "La oportunidad es de otra organización"}},
)
async def get_pursuit_kit(
    pursuit_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> KitPresentacion:
    """F2.3 — qué hay que entregar, en qué sobre, y qué falta."""
    try:
        return await run_db(
            kit_de_pursuit,
            int(ctx["user_id"]),
            pursuit_id,
            organization_id=organization_id,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/pursuits/{pursuit_id}/kit",
    status_code=status.HTTP_200_OK,
    summary="Marcar un documento del kit como listo (o desmarcarlo)",
    responses={403: {"description": "La oportunidad es de otra organización"}},
)
async def post_pursuit_kit_item(
    pursuit_id: int,
    body: KitItemBody,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> KitPresentacion:
    """Anota el marcado en el ledger y devuelve el kit ya actualizado.

    Devuelve el kit entero y no un `204`: el checklist es colaborativo, así que
    la respuesta es la ocasión de traer también lo que han marcado otros desde
    que el cliente lo cargó.
    """
    try:
        return await run_db(
            marcar_kit_de_pursuit,
            int(ctx["user_id"]),
            pursuit_id,
            clave=body.clave,
            listo=body.listo,
            organization_id=organization_id,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/pursuits/{pursuit_id}/kit/responsable",
    status_code=status.HTTP_200_OK,
    summary="Asignar un documento del kit a una persona (crea o reasigna su tarea)",
    responses={
        403: {
            "description": (
                "La oportunidad es de otra organización, tu rol es de lectura "
                "o el responsable no es miembro activo"
            )
        },
        422: {"description": "El documento no está en el kit de esta oportunidad"},
    },
)
async def post_pursuit_kit_responsable(
    pursuit_id: int,
    body: KitResponsableBody,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> KitPresentacion:
    """F2.3 + C6.1 — el responsable de un documento es el de su tarea.

    Devuelve el kit entero por lo mismo que el marcado: la respuesta trae
    también lo que otros han asignado desde que el cliente lo cargó.
    """
    try:
        return await run_db(
            asignar_kit_de_pursuit,
            int(ctx["user_id"]),
            pursuit_id,
            clave=body.clave,
            responsable_user_id=body.responsable_user_id,
            vence=body.vence,
            organization_id=organization_id,
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (PursuitValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/pursuits/{pursuit_id}", response_model=PursuitDetail)
async def patch_pursuit(
    pursuit_id: int,
    body: PursuitUpdate,
    organization_id: int | None = Query(default=None, ge=1),
    idempotency_key: str | None = Header(
        default=None,
        alias="X-Idempotency-Key",
        max_length=200,
    ),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PursuitDetail:
    """Aplica una transición validada y añade un único evento."""
    try:
        return await run_db(
            update_pursuit,
            int(ctx["user_id"]),
            pursuit_id,
            body,
            organization_id=organization_id,
            idempotency_key=idempotency_key,
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (PursuitTransitionError, PursuitConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PursuitValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ── Hilo de comentarios ─────────────────────────────────────────────────────


@router.get("/pursuits/{pursuit_id}/comments", response_model=PursuitCommentListResponse)
async def get_pursuit_comments(
    pursuit_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    page: PageParams = Depends(pagina(200)),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PursuitCommentListResponse:
    """Conversación del equipo sobre la oportunidad.

    Paginada desde el más reciente (``offset=0`` = los últimos ``limit``), y
    cada página se devuelve en orden cronológico.
    """
    try:
        return await run_db(
            list_comments,
            int(ctx["user_id"]),
            pursuit_id,
            organization_id=organization_id,
            limit=page.limit,
            offset=page.offset,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/pursuits/{pursuit_id}/comments",
    response_model=PursuitCommentOut,
    status_code=status.HTTP_201_CREATED,
)
async def post_pursuit_comment(
    pursuit_id: int,
    body: PursuitCommentCreate,
    organization_id: int | None = Query(default=None, ge=1),
    idempotency_key: str | None = Header(
        default=None,
        alias="X-Idempotency-Key",
        max_length=200,
    ),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PursuitCommentOut:
    """Publica un comentario; reintentar con la misma clave no lo duplica."""
    try:
        return await run_db(
            add_comment,
            int(ctx["user_id"]),
            pursuit_id,
            body,
            organization_id=organization_id,
            idempotency_key=idempotency_key,
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete(
    "/pursuits/{pursuit_id}/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borrar un comentario",
)
async def delete_pursuit_comment(
    pursuit_id: int,
    comment_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> None:
    """Borra un comentario propio; owner y admin pueden borrar cualquiera."""
    try:
        await run_db(
            delete_comment,
            int(ctx["user_id"]),
            pursuit_id,
            comment_id,
            organization_id=organization_id,
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (PursuitNotFoundError, PursuitCommentNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ── Tareas de la oportunidad (C6.1) ──────────────────────────────────────────


@router.get("/pursuits/{pursuit_id}/tasks", response_model=list[PursuitTaskOut])
async def get_pursuit_tasks(
    pursuit_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> list[PursuitTaskOut]:
    """Tareas de la oportunidad: abiertas primero y por vencimiento."""
    from services.pursuit_tasks import list_tasks

    try:
        filas = await run_db(
            list_tasks, int(ctx["user_id"]), pursuit_id, organization_id=organization_id
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [PursuitTaskOut.model_validate(f) for f in filas]


@router.post(
    "/pursuits/{pursuit_id}/tasks",
    response_model=PursuitTaskOut,
    status_code=status.HTTP_201_CREATED,
)
async def post_pursuit_task(
    pursuit_id: int,
    body: PursuitTaskCreate,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PursuitTaskOut:
    """Crea una tarea y recalcula `next_action`, que pasa a derivarse de estas."""
    from services.pursuit_tasks import create_task

    try:
        fila = await run_db(
            create_task,
            int(ctx["user_id"]),
            pursuit_id,
            titulo=body.titulo,
            responsable_user_id=body.responsable_user_id,
            vence=body.vence,
            organization_id=organization_id,
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PursuitTaskOut.model_validate(fila)


@router.patch("/pursuits/{pursuit_id}/tasks/{task_id}", response_model=PursuitTaskOut)
async def patch_pursuit_task(
    pursuit_id: int,
    task_id: int,
    body: PursuitTaskPatch,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PursuitTaskOut:
    from services.pursuit_tasks import PursuitTaskNotFoundError, update_task

    try:
        fila = await run_db(
            update_task,
            int(ctx["user_id"]),
            pursuit_id,
            task_id,
            organization_id=organization_id,
            titulo=body.titulo,
            responsable_user_id=body.responsable_user_id,
            vence=body.vence,
            estado=body.estado,
            limpiar_responsable=body.limpiar_responsable,
            limpiar_vence=body.limpiar_vence,
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (PursuitNotFoundError, PursuitTaskNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PursuitTaskOut.model_validate(fila)


@router.delete(
    "/pursuits/{pursuit_id}/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_pursuit_task(
    pursuit_id: int,
    task_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> None:
    from services.pursuit_tasks import PursuitTaskNotFoundError, delete_task

    try:
        await run_db(
            delete_task,
            int(ctx["user_id"]),
            pursuit_id,
            task_id,
            organization_id=organization_id,
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (PursuitNotFoundError, PursuitTaskNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/pursuits/{pursuit_id}/adjuntos",
    response_model=list[PursuitAttachmentOut],
)
async def get_pursuit_adjuntos(
    pursuit_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> list[PursuitAttachmentOut]:
    """Adjuntos propios de la oportunidad, recientes primero."""
    from services.pursuit_attachments import listar

    try:
        filas = await run_db(
            listar, int(ctx["user_id"]), pursuit_id, organization_id=organization_id
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [PursuitAttachmentOut.model_validate(f) for f in filas]


@router.post(
    "/pursuits/{pursuit_id}/adjuntos",
    response_model=PursuitAttachmentOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Adjunto registrado"},
        403: {"description": "No perteneces a esa organización, o eres viewer"},
        404: {"description": "La oportunidad no existe en tu organización"},
        409: {"description": "Ese mismo fichero ya está subido aquí"},
        413: {"description": "Supera el tope por fichero o el de la organización"},
        415: {"description": "Tipo de fichero no admitido"},
        503: {"description": "No hay almacén de objetos configurado"},
    },
)
async def post_pursuit_adjunto(
    request: Request,
    pursuit_id: int,
    x_filename: str = Header(
        alias="X-Filename",
        # Tres veces los 255 del nombre guardado: codificado como URI, cada
        # carácter no ASCII ocupa hasta tres `%XX`.
        max_length=1024,
        description=(
            "Nombre original del fichero, codificado como componente de URI "
            "(`encodeURIComponent`). Se decodifica y se sanea antes de guardarlo."
        ),
    ),
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PursuitAttachmentOut:
    """Sube un adjunto: **cuerpo crudo**, no `multipart/form-data`.

    El fichero viaja como cuerpo de la petición y su nombre en `X-Filename`. Es
    una decisión, no una limitación: `multipart` obligaría a añadir
    `python-multipart` —una dependencia que este plan no pre-autoriza (D31)— para
    parsear un formato que aquí solo transportaría un campo. El cliente hace
    `fetch(url, {method: 'POST', body: file, headers: {'Content-Type': file.type,
    'X-Filename': encodeURIComponent(file.name)}})`, y el servidor recibe
    exactamente los bytes.

    El nombre va **codificado como URI** porque una cabecera HTTP solo lleva
    Latin-1: `fetch` lanza `TypeError` ante «Oferta — v2.pdf» (la raya,
    U+2014), y un nombre con tilde llegaba según cómo lo serializara cada
    cliente. Un nombre sin `%` se decodifica a sí mismo, así que el cliente que
    lo mande en claro sigue funcionando.

    El tamaño se comprueba **dos veces**: contra `Content-Length` antes de leer
    —para no traer 500 MB a memoria y rechazarlos después— y contra los bytes
    reales, porque la cabecera la escribe el cliente.
    """
    from db.repositories.pursuit_attachments import PursuitAttachmentExists
    from services.pursuit_attachments import (
        MAX_BYTES,
        AttachmentError,
        AttachmentStoreUnavailable,
        AttachmentTooLarge,
        AttachmentTypeRejected,
        subir,
    )

    declarado = request.headers.get("content-length")
    if declarado and declarado.isdigit() and int(declarado) > MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"El fichero declara {declarado} bytes y el tope es {MAX_BYTES}.",
        )

    datos = await request.body()
    content_type = request.headers.get("content-type") or ""

    try:
        fila = await run_db(
            subir,
            int(ctx["user_id"]),
            pursuit_id,
            filename=unquote(x_filename, errors="replace"),
            content_type=content_type,
            data=datos,
            organization_id=organization_id,
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PursuitAttachmentExists as exc:
        raise HTTPException(
            status_code=409,
            detail="Ese mismo fichero ya está adjunto a esta oportunidad.",
        ) from exc
    except AttachmentStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AttachmentTooLarge as exc:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc)) from exc
    except AttachmentTypeRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
        ) from exc
    except AttachmentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if fila is None:
        raise HTTPException(status_code=404, detail="Oportunidad no encontrada.")
    return PursuitAttachmentOut.model_validate(fila)


@router.get("/organizations/go-no-go/weights", response_model=GoNoGoWeightsOut)
async def get_go_no_go_weights(
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> GoNoGoWeightsOut:
    from services.go_no_go_puntuacion import get_weights

    try:
        return GoNoGoWeightsOut.model_validate(
            await run_db(get_weights, int(ctx["user_id"]), organization_id=organization_id)
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.put("/organizations/go-no-go/weights", response_model=GoNoGoWeightsOut)
async def put_go_no_go_weights(
    body: GoNoGoWeightsIn,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> GoNoGoWeightsOut:
    """Cambia los pesos de la plantilla. Solo owner/admin; queda auditado."""
    from services.go_no_go_puntuacion import set_weights

    try:
        return GoNoGoWeightsOut.model_validate(
            await run_db(
                set_weights, int(ctx["user_id"]), body.pesos, organization_id=organization_id
            )
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/pursuits/{pursuit_id}/go-no-go", response_model=GoNoGoScoreOut)
async def get_pursuit_go_no_go(
    pursuit_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> GoNoGoScoreOut:
    """Puntuación ponderada de la oportunidad y si contradice la decisión tomada."""
    from services.go_no_go_puntuacion import get_score

    try:
        return GoNoGoScoreOut.model_validate(
            await run_db(
                get_score, int(ctx["user_id"]), pursuit_id, organization_id=organization_id
            )
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/pursuits/{pursuit_id}/go-no-go", response_model=GoNoGoScoreOut)
async def put_pursuit_go_no_go(
    pursuit_id: int,
    body: GoNoGoScoreIn,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> GoNoGoScoreOut:
    from services.go_no_go_puntuacion import set_score

    try:
        return GoNoGoScoreOut.model_validate(
            await run_db(
                set_score,
                int(ctx["user_id"]),
                pursuit_id,
                criterio=body.criterio,
                puntuacion=body.puntuacion,
                motivo=body.motivo,
                organization_id=organization_id,
            )
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ── Mi baja frente al mercado (C6.5) ─────────────────────────────────────────
