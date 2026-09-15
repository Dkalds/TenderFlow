"""Familia **ficha**: el expediente como objeto.

El detalle, sus parecidos y la comparación entre varios. El detalle no cuelga
de ``router`` sino de ``router_detalle``, declarado unas líneas más abajo con
el motivo al lado: su ruta es glotona y tiene que registrarse la última de
todas.
"""

from __future__ import annotations

from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from pydantic import BaseModel, Field, field_validator

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from api.routes.licitaciones._base import (
    _check_etag,
    _lic_repo,
    _make_etag,
)
from api.routes.licitaciones.modelos import (
    LicitacionDetail,
    LoteOut,
)
from db.repositories import dedupe as _dedupe_repo
from db.repositories.licitaciones import lotes_de
from observability.logging import get_logger
from services.comparador_fichas import (
    MAX_EXPEDIENTES as MAX_EXPEDIENTES_COMPARAR,
)
from services.comparador_fichas import (
    ComparacionFichas,
    comparar,
)
from shared.dto import (
    SafeStr,
)
from shared.tender_facts import TenderFactSheet

log = get_logger(__name__)

router = APIRouter(tags=["licitaciones"])


#: Router aparte **sólo** para `GET /licitaciones/{id_externo:path}`.
#:
#: Un `id_externo` de PLACSP lleva barras y espacios ("PA-S 2026/000058"), así
#: que el detalle necesita el conversor `:path`. Pero `:path` es glotón:
#: `/licitaciones/{id:path}` también casa con `/licitaciones/X/eventos` y con
#: todos los demás hijos, y el que se declara antes gana. Por eso esta ruta se
#: registra en un router propio que `api/app.py` incluye **el último de todos**,
#: después de `eventos`, `predicciones` y `ask`, que también cuelgan de
#: `/licitaciones/{...}` y viven en otros módulos.
#:
#: Antes esto era un `app.add_api_route(..., include_in_schema=False)` al final
#: de `api/app.py`: funcionaba, pero (a) dejaba el detalle **fuera del esquema**
#: con la forma correcta —el spec publicaba la variante de segmento simple, que
#: es la que se rompe con esos ids—, (b) metía conocimiento de una ruta
#: concreta en el ensamblado de la aplicación y (c) su corrección dependía de
#: un orden que nadie comprobaba. Ahora el orden lo fija
#: `tests/test_licitaciones_identificador.py`.
router_detalle = APIRouter(tags=["licitaciones"])


# ── /licitaciones/{id_externo} ────────────────────────────────────────────
# Va en `router_detalle` y no en `router`: ver el comentario de ese router.


@router_detalle.get(
    "/licitaciones/{id_externo:path}",
    response_model=LicitacionDetail,
    summary="Detalle de una licitación",
    responses={
        200: {"description": "Detalle completo"},
        304: {"description": "Not Modified (ETag coincide)"},
        401: {"description": "API key inválida"},
        404: {"description": "No encontrado"},
    },
)
async def get_licitacion(
    id_externo: str,
    request: Request,
    response: Response,
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> Any:
    """Devuelve todos los campos de una licitación por su ID externo.

    Soporta caching via ETag / If-None-Match.
    """
    data = await run_db(_lic_repo.get_by_id, id_externo)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontrado.")

    etag = _make_etag(data)
    response.headers["ETag"] = etag
    # Sin `Cache-Control` aquí: lo fija `ETagMiddleware`, que para tráfico
    # autenticado —y esta ruta siempre lo es— lo pone en `private, no-cache`
    # para que ningún caché compartido guarde la respuesta. El
    # `private, max-age=60` que había era papel mojado: el middleware lo
    # pisaba en cada respuesta, así que prometía una frescura que el cliente
    # nunca recibió.

    if _check_etag(request, etag):
        # El `ETag` se repite aquí y no se hereda del `response` inyectado:
        # FastAPI sólo fusiona sus cabeceras cuando el handler **no** devuelve
        # un `Response` propio (`routing.py`: `if isinstance(raw_response,
        # Response): response = raw_response`, y el `extend` vive en el `else`).
        # Sin esto el 304 salía sin `ETag`, que RFC 7232 §4.1 exige.
        return Response(status_code=304, headers={"ETag": etag})

    canonica = await run_db(_dedupe_repo.canonical_for, id_externo)
    lotes = await run_db(lotes_de, id_externo)
    campos = {k: data.get(k) for k in LicitacionDetail.model_fields}
    campos["republicacion_de"] = canonica
    campos["lotes"] = [LoteOut(**lote) for lote in lotes]
    return LicitacionDetail(**campos)  # type: ignore[arg-type]


# ── /licitaciones/{id_externo}/similares ─────────────────────────────────


class SimilarOut(BaseModel):
    """Un expediente propuesto como predecesor o similar (C1.3)."""

    id_externo: str
    titulo: str
    organo_contratacion: str | None = None
    cpv: str | None = None
    importe: float | None = None
    estado: str | None = None
    fecha_publicacion: str | None = None
    #: Parecido con el expediente consultado, en la escala del `metodo`.
    score: float
    # Solo el predecesor los trae: son la información accionable —quién es el
    # incumbente y a qué precio ganó— y por eso no se rellenan en los similares,
    # donde no hay una adjudicación que los respalde.
    adjudicatario: str | None = None
    importe_adjudicado: float | None = None
    fecha_adjudicacion: str | None = None
    #: Baja del predecesor, calculada sobre base sin IVA cuando la fila la trae
    #: (C1.1). `None` si no se puede calcular sin mezclar bases.
    baja_pct: float | None = None


class SimilaresResult(BaseModel):
    """Predecesor y expedientes parecidos."""

    licitacion_id: str
    # `None` = no hay ninguno que cumpla mismo órgano + mismo CPV4 +
    # anterioridad. **No se rellena con «el más parecido»**: proponer un
    # incumbente equivocado hace que alguien prepare su oferta contra un
    # competidor que no existe.
    predecesor: SimilarOut | None = None
    similares: list[SimilarOut] = Field(default_factory=list)
    #: `embedding` | `fts`. Sin embeddings instalados el orden es peor, y una
    #: lista ordenada por un criterio que el consumidor no conoce no se puede
    #: interpretar.
    metodo: str = "fts"
    #: Candidatos evaluados. Sin él, `similares: []` no distingue «no hay nada
    #: parecido» de «no había contra qué comparar».
    n: int = 0


@router.get(
    "/licitaciones/{id_externo:path}/similares",
    response_model=SimilaresResult,
    summary="Predecesor y expedientes similares",
)
async def get_similares(
    id_externo: str,
    limit: int = Query(10, ge=1, le=50, description="Máximo de similares"),
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> SimilaresResult:
    """¿Este contrato ya se licitó antes? ¿Quién lo tiene hoy?

    `services/embeddings.py` sabía buscar textos parecidos desde siempre y
    ninguna ruta lo exponía (hecho 3 del plan complementario). Esta lo hace, con
    dos preguntas separadas porque tienen listones de evidencia distintos: ver
    `services/similares.py`.
    """
    from services.similares import buscar

    resultado = await run_db(buscar, id_externo, max_similares=limit)
    if resultado is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontrado.")

    return SimilaresResult(
        licitacion_id=resultado.licitacion_id,
        predecesor=(SimilarOut(**vars(resultado.predecesor)) if resultado.predecesor else None),
        similares=[SimilarOut(**vars(c)) for c in resultado.similares],
        metodo=resultado.metodo,
        n=resultado.n,
    )


class CompararBody(BaseModel):
    """Hasta tres expedientes a comparar familia a familia."""

    ids: list[SafeStr] = Field(min_length=2, max_length=MAX_EXPEDIENTES_COMPARAR)

    @field_validator("ids")
    @classmethod
    def _sin_repetidos(cls, valor: list[SafeStr]) -> list[SafeStr]:
        """Dos ids iguales no son dos columnas.

        El handler indexa las fichas por id, así que ``["A", "A", "B"]``
        pasaba el ``min_length=2`` como tres expedientes y devolvía una tabla
        de dos columnas, habiendo pedido la ficha de A dos veces. Se rechaza
        en el contrato en vez de colapsar en silencio: el cliente pidió algo
        que la respuesta no iba a cumplir.
        """
        vistos = {str(v).strip() for v in valor}
        if len(vistos) != len(valor):
            raise ValueError("No se puede comparar un expediente consigo mismo.")
        return valor


@router.post(
    "/licitaciones/comparar",
    summary="Comparar las fichas de hasta tres expedientes, familia a familia",
    responses={401: {"description": "Autenticación inválida"}},
)
async def post_comparar_fichas(
    body: CompararBody,
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> ComparacionFichas:
    """F2.8 — determinista y sin LLM.

    Una familia vacía **se muestra vacía**, no se omite: que uno de los dos
    pliegos no diga nada de solvencia técnica es exactamente lo que hay que
    ver. Los expedientes sin ficha extraída se declaran en `sin_ficha`, para
    que una columna en blanco no se confunda con un pliego que no exige nada.
    """

    def _trabajo() -> ComparacionFichas:
        from services.rag.fact_sheet import get_fact_sheet

        fichas: dict[str, TenderFactSheet | None] = {}
        for id_externo in body.ids:
            record = get_fact_sheet(str(id_externo))
            fichas[str(id_externo)] = record.facts if record else None
        return comparar(fichas)

    return await run_db(_trabajo)
