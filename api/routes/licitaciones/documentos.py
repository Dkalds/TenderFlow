"""Familia **documentos**: los adjuntos del expediente y su paginación.

Listado de documentos, la página concreta de un pliego con la cita localizada,
y el reporte de un dato erróneo —que vive aquí porque lo que se reporta casi
siempre viene de un documento—.
"""

from __future__ import annotations

from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from pydantic import BaseModel, Field

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from api.routes.licitaciones._base import (
    _doc_repo,
)
from observability.logging import get_logger
from services.rag.paginas import PaginaDocumento, get_pagina
from services.reportes_dato import COLA_POR_TIPO, TipoReporte, registrar_reporte
from shared.dto import (
    SafeStr,
)

log = get_logger(__name__)

router = APIRouter(tags=["licitaciones"])


# ── /licitaciones/{id_externo}/documentos ─────────────────────────────────


class DocumentoSummary(BaseModel):
    id: int
    tipo: str
    uri: str
    filename: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None
    status: str
    created_at: str | None = None


# `PaginatedResponse` y `CursorPaginatedResponse` viven en `shared/dto.py`
# (contrato de paginación común del API). Se importan arriba: la forma que
# estas rutas ya usaban es la que ahora comparten las demás.


class DocumentosResult(BaseModel):
    """Adjuntos (pliegos) de una licitación, sin el texto extraído."""

    id_externo: str
    items: list[DocumentoSummary]


@router.get(
    "/licitaciones/{id_externo:path}/documentos",
    summary="Documentos (pliegos) referenciados por una licitación",
    responses={401: {"description": "API key inválida"}},
)
async def get_documentos(
    id_externo: str,
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> DocumentosResult:
    """Metadatos de los adjuntos (pliegos) parseados del CODICE/UBL para esta
    licitación — sin el texto extraído, que solo usa internamente el pipeline
    RAG ("Preguntar al copilot"). Lista vacía si aún no se procesó ningún
    documento (no todas las fuentes/licitaciones tienen adjuntos parseados).
    """
    items = await run_db(_doc_repo.list_by_licitacion, id_externo)
    return DocumentosResult(
        id_externo=id_externo,
        items=[DocumentoSummary.model_validate(d) for d in items],
    )


class ReporteDatoBody(BaseModel):
    """Un aviso de que algo del expediente está mal."""

    tipo: TipoReporte
    #: Texto libre y opcional. Va a la nota del reporte y **no** a la
    #: telemetría: es del usuario y habla de un expediente concreto.
    comentario: SafeStr | None = Field(default=None, max_length=2000)


class ReporteDatoResult(BaseModel):
    """Acuse del reporte, con la cola que lo va a revisar."""

    id_externo: str
    tipo: str
    #: A qué revisión llega (`ml_feedback`, `dedupe`, `empresas`). Se devuelve
    #: para que la consola pueda decir «lo revisa el equipo de datos» en vez de
    #: un «gracias» sin contenido.
    cola: str
    created_at: str


@router.post(
    "/licitaciones/{id_externo:path}/reportes",
    status_code=status.HTTP_201_CREATED,
    summary="Reportar un dato incorrecto de un expediente",
    responses={401: {"description": "Autenticación inválida"}},
)
async def post_reporte_dato(
    id_externo: str,
    body: ReporteDatoBody,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> ReporteDatoResult:
    """F6.2 — «este dato está mal», desde la ficha.

    No comprueba que el expediente exista: la corrección más valiosa es
    justamente la de una fila que no debería estar, y un 404 aquí convertiría
    un reporte legítimo en un error del usuario.
    """
    user_id = ctx.get("user_id")
    creado = await run_db(
        registrar_reporte,
        id_externo=id_externo,
        tipo=body.tipo,
        comentario=body.comentario,
        user_id=int(user_id) if user_id is not None else None,
    )
    return ReporteDatoResult(
        id_externo=id_externo,
        tipo=body.tipo,
        cola=COLA_POR_TIPO[body.tipo],
        created_at=creado,
    )


@router.get(
    "/licitaciones/{id_externo:path}/documentos/{documento_id}/paginas/{page_number}",
    summary="Página de un pliego, con el fragmento de la cita localizado",
    responses={
        401: {"description": "Autenticación inválida"},
        404: {"description": "La página no existe para ese documento y licitación"},
    },
)
async def get_pagina_documento(
    id_externo: str,
    documento_id: int,
    page_number: int,
    inicio: int | None = Query(
        default=None, ge=0, description="Offset absoluto de inicio de la cita"
    ),
    fin: int | None = Query(default=None, ge=0, description="Offset absoluto de fin de la cita"),
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> PaginaDocumento:
    """F2.5 — el texto de una página del pliego y dónde cae la cita.

    Con `inicio` y `fin` (los `EvidenceRef.start_offset`/`end_offset` de la
    ficha) la respuesta trae los índices **ya relativos a esta página**. Unos
    offsets incoherentes no son un error del usuario: la página se devuelve
    entera y sin resaltar, y `resaltado_omitido` dice por qué.

    Sin `:path` en `id_externo`, al revés que sus vecinas: aquí el id va en
    medio de la ruta y un comodín de camino se comería los segmentos
    siguientes. Los ids con barra se piden con la barra codificada.
    """
    pagina = await run_db(
        get_pagina,
        id_externo,
        documento_id,
        page_number,
        inicio=inicio,
        fin=fin,
    )
    if pagina is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hay texto extraído para esa página de ese documento.",
        )
    return pagina
