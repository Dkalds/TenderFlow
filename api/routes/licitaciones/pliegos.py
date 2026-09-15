"""Familia **pliegos**: extracción de la ficha técnica y lo que cuesta dinero.

Leer la ficha es barato; extraerla llama al proveedor LLM, descarga PDF y
sobrescribe lo vigente. Por eso estas rutas comparten tope de peticiones con
``/ask`` y son las únicas de la casa que atribuyen gasto
(:func:`_budget_subject`). El guion de oferta y el encolado de embeddings
entran aquí por lo mismo: trabajo caro y asíncrono sobre el pliego.
"""

from __future__ import annotations

from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from pydantic import BaseModel

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from api.routes.licitaciones._base import (
    _lic_repo,
)
from api.tenancy import require_organization
from observability.logging import get_logger
from services.rag.guion_oferta import GuionOferta, generar_guion
from shared.tender_facts import TenderFactSheetRecord

log = get_logger(__name__)

router = APIRouter(tags=["licitaciones"])


@router.post(
    "/licitaciones/{id_externo:path}/guion",
    summary="Guion de la oferta técnica: esquema de puntos con citas al pliego",
    responses={
        401: {"description": "Autenticación inválida"},
        429: {"description": "Presupuesto LLM agotado"},
    },
)
async def post_guion_oferta(
    id_externo: str,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> GuionOferta:
    """F2.6 — sólo esquema, nunca prosa (D33).

    `POST` y no `GET` porque genera: cuesta una llamada al LLM y consume
    presupuesto. Devuelve 200 con `sin_guion` cuando no hay criterios
    extraídos o no hay texto de pliegos — que no es un error del usuario.

    El presupuesto se ata al mismo sujeto opaco que el resto de superficies
    LLM, con la `user_key` del auth y nunca el email ni el `user_id` crudo.
    """
    from llm.budget import LLMBudgetExceeded, bind_budget_subject

    def _trabajo() -> GuionOferta:
        bind_budget_subject(_budget_subject(ctx))
        return generar_guion(id_externo)

    try:
        return await run_db(_trabajo)
    except LLMBudgetExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


@router.get(
    "/licitaciones/{id_externo:path}/ficha-pliego",
    response_model=TenderFactSheetRecord,
    summary="Ficha estructurada y citable de los pliegos",
    responses={
        401: {"description": "Autenticación inválida"},
        404: {"description": "Ficha todavía no disponible"},
    },
)
async def get_tender_fact_sheet(
    id_externo: str,
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> TenderFactSheetRecord:
    """Lee la extracción vigente sin invocar al proveedor LLM."""
    from services.rag.fact_sheet import get_fact_sheet

    record = await run_db(get_fact_sheet, id_externo)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La ficha del pliego todavía no está disponible.",
        )
    return record


def _budget_subject(ctx: dict[str, Any]) -> str | None:
    """Sujeto al que atribuir el gasto LLM: la ``user_key`` opaca del auth.

    Réplica deliberada de ``api/routes/ask.py::_budget_subject``: es el
    contrato de ``llm.budget`` (nunca el email ni el ``user_id`` crudo), y
    duplicar tres líneas cuesta menos que hacer que una ruta importe un
    privado de otra.
    """
    raw = ctx.get("user_key")
    return raw if isinstance(raw, str) and raw else None


@router.post(
    "/licitaciones/{id_externo:path}/ficha-pliego/extract",
    response_model=TenderFactSheetRecord,
    summary="Extraer o reprocesar la ficha estructurada",
    responses={
        401: {"description": "Autenticación inválida"},
        422: {"description": "Sin texto de pliegos disponible (ni descargable ahora)"},
        # El 429 por presupuesto LLM agotado (ver el handler) no se declara aquí
        # a propósito: tocar `responses` regenera `web/src/generated/api.d.ts` y
        # el gate de codegen drift exige recommitearlo. Documentarlo es una
        # línea + `make openapi`, en un cambio que no arrastre esto.
        502: {"description": "El proveedor no devolvió una ficha válida"},
    },
)
async def extract_tender_fact_sheet(
    id_externo: str,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> TenderFactSheetRecord:
    """Reextracción explícita; descarga bajo demanda los pliegos que aún
    estén pendientes (el cron nocturno drena el backlog global por lotes y
    esta licitación puede no haber tocado turno) y valida toda cita antes de
    persistirla."""
    from config import settings
    from llm.budget import LLMBudgetExceeded, bind_budget_subject
    from services.rag.fact_sheet import extract_fact_sheet_on_demand
    from services.tech_signal import ingest_llm_technologies

    # El gasto de esta ruta entra por ``stream_llm_response``, que consulta y
    # apunta el presupuesto sin saber a quién atribuirlo. Sin sujeto el guard
    # solo veía el tope global: una sola cuenta podía agotar la ventana de
    # todas las demás reextrayendo fichas, que es una denegación de servicio
    # barata. El ``bind`` va DENTRO del closure a propósito —anyio copia el
    # contexto en cada salto al threadpool, así que la mutación muere con el
    # hilo y no se filtra a otra request—, igual que en ask.py::_stream_ask.
    scope_key = _budget_subject(ctx)

    # El nombre del closure viaja al span OTEL (``db.function``), así que se
    # elige parecido al de la función que envuelve para no romper búsquedas.
    def _extract_fact_sheet_on_demand() -> TenderFactSheetRecord:
        bind_budget_subject(scope_key)
        return extract_fact_sheet_on_demand(id_externo, model=settings.PLIEGO_FACTS_MODEL)

    try:
        record = await run_db(_extract_fact_sheet_on_demand)
    except LLMBudgetExceeded as exc:
        # Con sujeto bindeado el breaker de coste ya puede dispararse aquí. Se
        # captura ANTES del 502 genérico: el presupuesto agotado es un límite
        # reintentable del cliente (429, como en /ask), no un fallo del
        # proveedor. Va también antes del 422 sólo por claridad de lectura;
        # LLMBudgetExceeded hereda de RuntimeError, no de ValueError.
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        log.warning("tender_fact_sheet_extract_failed", id_externo=id_externo, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="No se pudo extraer una ficha verificable del pliego.",
        ) from exc

    try:
        await run_db(ingest_llm_technologies, record)
    except Exception as exc:
        # La ficha ya se persistió y es lo que la ruta promete devolver; un
        # fallo al ingerir la señal de tecnología no debe convertir una
        # extracción exitosa en un 502.
        log.warning("tender_fact_sheet_tech_ingest_failed", id_externo=id_externo, error=str(exc))

    return record


class FactSheetExtractionState(BaseModel):
    """Estado del proceso de extracción de la ficha (no del dato persistido)."""

    licitacion_id: str
    running: bool
    #: Job de la cola que hace el trabajo, **si es de la organización de quien
    #: pregunta**. ``null`` cuando no hay ninguno en curso o cuando la
    #: extracción la lanzó otra organización: en ese caso ``running`` sigue
    #: siendo ``true`` —la ficha es dato compartido y se está extrayendo— pero
    #: el id no se publica, porque ``GET /jobs/{id}`` responde 404 a quien no es
    #: su dueño y devolverlo aquí sería prometer una consulta que no funciona.
    job_id: int | None = None


class ExpedienteJobEncolado(BaseModel):
    """202 de las acciones de expediente que se resuelven en la cola."""

    licitacion_id: str
    job_id: int


@router.post(
    "/licitaciones/{id_externo:path}/ficha-pliego/extract-async",
    response_model=FactSheetExtractionState,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Encolar la extracción de la ficha",
    responses={
        202: {"description": "Extracción encolada (o ya en cola)"},
        401: {"description": "Autenticación inválida"},
        404: {"description": "Licitación no encontrada"},
    },
)
async def extract_tender_fact_sheet_async(
    id_externo: str,
    ctx: dict[str, Any] = Depends(require_organization(write=True)),
) -> FactSheetExtractionState:
    """Variante asíncrona de ``…/ficha-pliego/extract`` para la UI.

    El camino síncrono descarga hasta 8 PDFs y llama al LLM dentro de la
    request — minutos de spinner con la conexión abierta. Aquí la request
    devuelve 202 al instante con el ``job_id`` del trabajo encolado; el cliente
    sondea ``…/ficha-pliego/estado`` (o ``GET /jobs/{job_id}`` para el detalle)
    y relee la ficha al terminar. Idempotente: con una extracción ya en cola
    responde 202 con el mismo ``job_id``.
    """
    from config import settings
    from shared.jobs import TIPO_FICHA_PLIEGO, enqueue

    # 404 ANTES de encolar: con un id inexistente el trabajo acabaría
    # intentando persistir el estado `failed` y violando la FK de
    # ``tender_fact_sheets`` — exactamente el 5xx que cazó Schemathesis.
    if await run_db(_lic_repo.get_by_id, id_externo) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Licitación '{id_externo}' no encontrada.",
        )

    # Hasta S5 esto era un ``BackgroundTask`` del propio proceso de la API con
    # 30 s de drenado al apagar: un despliegue en mitad de la extracción la
    # mataba y el polling se quedaba esperando para siempre. Ahora la petición
    # es una fila que sobrevive al proceso.
    job_id = await run_db(
        enqueue,
        TIPO_FICHA_PLIEGO,
        {
            "licitacion_id": id_externo,
            "model": settings.PLIEGO_FACTS_MODEL,
            "budget_subject": _budget_subject(ctx),
        },
        organization_id=int(ctx["organization_id"]),
    )
    log.info("tender_fact_sheet_extract_async_encolada", id_externo=id_externo, job_id=job_id)
    return FactSheetExtractionState(licitacion_id=id_externo, running=True, job_id=job_id)


@router.post(
    "/licitaciones/{id_externo:path}/embeddings-async",
    response_model=ExpedienteJobEncolado,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Encolar el cálculo de embeddings de los pliegos del expediente",
    responses={
        202: {"description": "Cálculo encolado (o ya en cola)"},
        401: {"description": "Autenticación inválida"},
        404: {"description": "Licitación no encontrada"},
    },
)
async def enqueue_expediente_embeddings(
    id_externo: str,
    ctx: dict[str, Any] = Depends(require_organization(write=True)),
) -> ExpedienteJobEncolado:
    """Calcula los embeddings de los pliegos de ESTE expediente, ya.

    El cron nocturno (``documentos_embeddings``) drena la cola global por lotes
    de 50, así que un expediente recién ingerido puede tardar días en tener
    chunks — y sin chunks el RAG del resumen y la búsqueda dentro del pliego no
    tienen de dónde leer. Esta ruta adelanta el del expediente que alguien está
    mirando. Idempotente: si ya hay uno en cola devuelve el mismo ``job_id``.
    """
    from shared.jobs import TIPO_EMBEDDINGS_EXPEDIENTE, enqueue

    if await run_db(_lic_repo.get_by_id, id_externo) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Licitación '{id_externo}' no encontrada.",
        )

    job_id = await run_db(
        enqueue,
        TIPO_EMBEDDINGS_EXPEDIENTE,
        {"licitacion_id": id_externo},
        organization_id=int(ctx["organization_id"]),
    )
    return ExpedienteJobEncolado(licitacion_id=id_externo, job_id=job_id)


@router.get(
    "/licitaciones/{id_externo:path}/ficha-pliego/estado",
    response_model=FactSheetExtractionState,
    summary="¿Hay una extracción de ficha en curso?",
    responses={401: {"description": "Autenticación inválida"}},
)
async def get_tender_fact_sheet_state(
    id_externo: str,
    ctx: dict[str, Any] = Depends(require_organization()),
) -> FactSheetExtractionState:
    """Estado de la extracción para el polling de la UI. El resultado en sí se
    lee de ``…/ficha-pliego``.

    Consulta la cola, no una bandera en la caché del proceso: aquella era
    invisible desde cualquier otra instancia de la API y desaparecía con el
    reinicio, así que decía «no hay extracción» mientras la había.

    ``running`` mira la cola entera y ``job_id`` solo la organización de quien
    pregunta: la ficha del pliego es dato compartido, así que una extracción
    ajena en curso es una respuesta correcta a «¿hay algo en marcha?» (y evita
    lanzar una segunda contra el mismo expediente), pero el identificador de
    ese trabajo no es suyo y su ``GET /jobs/{id}`` daría 404.
    """
    from shared.jobs import TIPO_FICHA_PLIEGO, job_activo

    job = await run_db(job_activo, TIPO_FICHA_PLIEGO, campo="licitacion_id", valor=id_externo)
    propio = job is not None and job.organization_id == int(ctx["organization_id"])
    return FactSheetExtractionState(
        licitacion_id=id_externo,
        running=job is not None,
        job_id=job.id if (job is not None and propio) else None,
    )
