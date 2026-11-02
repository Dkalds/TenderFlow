"""Búsqueda de texto — POST /api/v1/search/semantic.

Expone el motor de :mod:`services.investigador.busqueda` como endpoint REST
(requiere API-key o sesión).

Diseño
------
* La frase se **interpreta** antes de buscar
  (:mod:`services.investigador.consulta`): «en Andalucía», «de más de 500K»,
  «abiertas» o «desde 2025» son filtros, no palabras, y lo entendido vuelve en
  ``interpretacion`` para que la pantalla lo enseñe. ``interpretar=false``
  busca el texto tal cual.
* Cuatro caminos, y ``source`` dice cuál se ejecutó de verdad: texto completo
  de Postgres sobre anuncios **y pliegos** (``fts``), coincidencia literal
  (``like``), lo más reciente del ámbito cuando la frase eran solo filtros
  (``filtros``) y ``rrf`` cuando la fusión con la similitud vectorial sobre
  ``documento_chunks`` aportó algo. La fusión solo se intenta con la flag
  ``busqueda_semantica`` encendida para quien busca (apagada por defecto) y
  degrada al texto, sin error, si no hay modelo de embeddings, pgvector o
  fragmentos embebidos; el log ``semantic_search.ok`` dice por qué
  (``semantica``) y cuánto costó (``fusion_ms``; presupuesto en
  ``docs/sli-slo.md``). La fusión **completa** la lista del texto,
  no la sustituye (:func:`services.investigador.busqueda.combinar`): cada
  resultado sigue diciendo dónde casa.
* ``hay_mas`` dice si el motor tenía más resultados que ``top_k``: la pantalla
  pide la siguiente tanda con un ``top_k`` mayor.
* El ámbito —el explícito y el entendido— va en el ``WHERE`` de cada camino.
  Hasta 2026-10 se aplicaba después, contra un conjunto de 5.000 ids sin
  ordenar: con Cataluña (60.840 filas) el filtro descartaba el 92 % de lo que
  sí casaba.
* ``alpha`` pondera las dos listas de la fusión (0 = solo léxico, 1 = solo
  semántico) y no interviene en los demás caminos.
* ``run_ml`` aísla la latencia en el pool de ML (bulkhead 2 slots).

Ejemplo::

    curl -X POST /api/v1/search/semantic \\
         -H "X-API-Key: sk-..." \\
         -H "Content-Type: application/json" \\
         -d '{"q": "SAP S/4HANA consultoría", "top_k": 5}'
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from api.concurrency import run_db, run_ml
from api.routes.dual_auth import require_any_auth
from api.tenancy import resolve_organization_ctx
from observability.logging import get_logger
from services.busqueda_global import BusquedaGlobal, buscar_global
from services.investigador.busqueda import (
    FUENTE_FILTROS,
    FUENTE_FUSION,
    FUENTE_LITERAL,
    FUENTE_TEXTO,
    FUENTES,
    Resultado,
)
from services.investigador.busqueda import preparar as preparar_consulta
from services.investigador.consulta import ConsultaInterpretada
from shared.procedimientos import etiqueta_procedimiento

log = get_logger(__name__)

router = APIRouter(tags=["search"])

_MAX_Q_LEN = 500
# Tope de los filtros multi-valor del cuerpo: las comunidades son 19 y las
# tecnologías del diccionario, unas decenas; el resto es relleno que viaja a la
# consulta como parámetros.
_MAX_FILTROS = 50
_MAX_FILTRO_LEN = 100
_DEFAULT_TOP_K = 10
_MAX_TOP_K = 100

# Valores posibles de ``SemanticSearchResponse.source``, en el orden en que se
# intentan los caminos. Son constantes y no un literal suelto porque el
# Investigador tiene que poder etiquetar todos sin inventarse otro:
# ``tests/test_search_semantic_source.py`` comprueba que la tabla de etiquetas
# de la UI y esta tupla no se separen. La fuente de verdad es el servicio.
SOURCE_RRF = FUENTE_FUSION
SOURCE_FTS = FUENTE_TEXTO
SOURCE_LIKE = FUENTE_LITERAL
SOURCE_FILTROS = FUENTE_FILTROS
SEARCH_SOURCES: tuple[str, ...] = FUENTES


# ── Schemas ──────────────────────────────────────────────────────────────────


class SemanticSearchRequest(BaseModel):
    """Cuerpo de la petición de búsqueda semántica."""

    q: str = Field(
        ..., min_length=1, max_length=_MAX_Q_LEN, description="Consulta en lenguaje natural"
    )
    top_k: int = Field(
        default=_DEFAULT_TOP_K, ge=1, le=_MAX_TOP_K, description="Número máximo de resultados"
    )
    alpha: float = Field(
        default=0.70,
        ge=0.0,
        le=1.0,
        description=(
            "Peso del lado semántico en la fusión RRF: 0 = solo texto completo, "
            "1 = solo similitud vectorial. Solo tiene efecto cuando la respuesta "
            "es source=rrf; con source=fts, like o filtros no hay nada que ponderar."
        ),
    )
    embedding_model: str = Field(
        default="",
        max_length=200,
        description="LEGACY — sin efecto desde la retirada de FAISS (2026-07); se acepta por compatibilidad",
    )
    ccaa: list[Annotated[str, Field(max_length=_MAX_FILTRO_LEN)]] = Field(
        default_factory=list,
        max_length=_MAX_FILTROS,
        description="Filtra resultados por CCAA (multi-valor)",
    )
    tecnologia: list[Annotated[str, Field(max_length=_MAX_FILTRO_LEN)]] = Field(
        default_factory=list,
        max_length=_MAX_FILTROS,
        description="Filtra resultados por tecnología (multi-valor)",
    )
    fecha_desde: str | None = Field(
        default=None, description="Fecha de publicación desde (YYYY-MM-DD)"
    )
    fecha_hasta: str | None = Field(
        default=None, description="Fecha de publicación hasta (YYYY-MM-DD)"
    )
    interpretar: bool = Field(
        default=True,
        description=(
            "Lee los filtros que diga la frase (comunidad, importe, fechas, «abiertas», "
            "«más recientes») y los aplica; lo entendido vuelve en `interpretacion`. Con "
            "false se busca el texto tal cual. Un filtro explícito del cuerpo manda sobre "
            "el de la frase en su misma dimensión."
        ),
    )

    @field_validator("q", "ccaa", "tecnologia", "fecha_desde", "fecha_hasta")
    @classmethod
    def _sin_bytes_nul(cls, value: str | list[str] | None) -> str | list[str] | None:
        """Postgres rechaza NUL (0x00) en campos de texto con un ``DataError``
        que llegaba al cliente como 5xx (lo encontró el fuzzing de contrato).
        Se rechaza como 422 en vez de sanearse en silencio: un NUL en una
        consulta nunca es intención de usuario, es un input malformado."""
        if value is None:
            return value
        values = value if isinstance(value, list) else [value]
        if any("\x00" in item for item in values):
            raise ValueError("El texto no puede contener bytes NUL (0x00).")
        return value


class TramoTexto(BaseModel):
    """Un trozo de un título o de un extracto, y si casa con la consulta."""

    texto: str
    resaltado: bool


class PasajePliego(BaseModel):
    """El fragmento de pliego que casa con la consulta."""

    documento_id: int | None
    tipo: str | None = Field(description="Clase del documento: legal, technical o additional.")
    filename: str | None
    page_number: int | None
    tramos: list[TramoTexto]


class SemanticHit(BaseModel):
    """Un resultado de búsqueda semántica."""

    id_externo: str
    titulo: str | None
    organo_contratacion: str | None
    importe: float | None
    descripcion: str | None
    url: str | None
    fecha_publicacion: str | None
    fecha_limite: str | None = Field(
        description="Fin del plazo de presentación, tal como lo publica la fuente."
    )
    ccaa: str | None
    estado: str | None
    tecnologia: str | None = Field(description="Códigos de tecnología del expediente, en CSV.")
    score: float = Field(
        description=(
            "En [0, 1], y su significado DEPENDE de source; no es comparable entre "
            "búsquedas ni entre fuentes. Con fts es la parte de los términos de la "
            "consulta que casan: 1 = todos, en el anuncio o en un pasaje del pliego. "
            "Con like, la parte de los términos buscados por subcadena que el anuncio "
            "contiene. Con rrf, los resultados que casan por texto conservan esa "
            "escala, y los que solo se parecen por significado se escalan contra el "
            "mejor de la fusión en esta misma respuesta, que vale 1. Con filtros vale "
            "0: no hubo texto que casar."
        )
    )
    coincide_en: list[Literal["anuncio", "pliego", "significado"]] = Field(
        description=(
            "Dónde casa la consulta: en el anuncio (título, descripción o CPV), en un "
            "pasaje del pliego, y/o por significado (solo con source=rrf: la "
            "similitud vectorial lo trajo). Vacío con source=filtros."
        ),
    )
    terminos_ausentes: list[str] = Field(
        description="Términos de la consulta que este resultado no contiene.",
    )
    titulo_tramos: list[TramoTexto] = Field(
        description="El título entero, troceado por lo que casa. Vacío si no se calculó.",
    )
    extracto: list[TramoTexto] = Field(
        description=(
            "Fragmentos de la descripción alrededor de lo que casa. Vacío si la "
            "descripción no contiene ningún término: no se rellena con su arranque."
        ),
    )
    pasaje: PasajePliego | None = Field(
        description=(
            "El fragmento de pliego que casa, cuando coincide_en incluye pliego; o, "
            "en un resultado que solo casa por significado, el arranque del "
            "fragmento más parecido, sin resaltados."
        )
    )


class Interpretacion(BaseModel):
    """Lo que se entendió de la frase y se aplicó a la búsqueda."""

    texto: str = Field(description="El texto con el que se buscó, ya sin los filtros.")
    terminos: list[str]
    ccaa: list[str]
    importe_min: float | None
    importe_max: float | None
    solo_abiertas: bool
    fecha_desde: str | None
    fecha_hasta: str | None
    cierre_desde: str | None = Field(
        default=None, description="Fin del plazo de presentación desde (YYYY-MM-DD)."
    )
    cierre_hasta: str | None = Field(
        default=None, description="Fin del plazo de presentación hasta (YYYY-MM-DD, incluido)."
    )
    procedimiento: list[str] = Field(
        default_factory=list, description="Códigos CODICE de procedimiento entendidos."
    )
    procedimiento_etiquetas: list[str] = Field(
        default_factory=list,
        description="Las etiquetas legibles de `procedimiento`, en el mismo orden.",
    )
    organo: list[str] = Field(
        default_factory=list,
        description="Órganos de contratación nombrados en la frase, como se escribieron.",
    )
    orden: Literal["relevancia", "recientes"]

    @classmethod
    def de(cls, consulta: ConsultaInterpretada) -> Interpretacion:
        return cls(
            texto=consulta.texto,
            terminos=list(consulta.terminos),
            ccaa=list(consulta.ccaa),
            importe_min=consulta.importe_min,
            importe_max=consulta.importe_max,
            solo_abiertas=consulta.solo_abiertas,
            fecha_desde=consulta.fecha_desde,
            fecha_hasta=consulta.fecha_hasta,
            cierre_desde=consulta.cierre_desde,
            cierre_hasta=consulta.cierre_hasta,
            procedimiento=list(consulta.procedimiento),
            procedimiento_etiquetas=[etiqueta_procedimiento(c) for c in consulta.procedimiento],
            organo=list(consulta.organo),
            orden=consulta.orden,
        )


class SemanticSearchResponse(BaseModel):
    """Respuesta de búsqueda semántica."""

    q: str
    top_k: int
    # Tipado ``str`` y no ``Literal``: el conjunto de valores es cerrado y lo
    # fija ``SEARCH_SOURCES``, pero un Literal en la respuesta convierte
    # cualquier camino futuro en un 500 de validación en producción.
    source: str = Field(
        description=(
            "Camino REALMENTE ejecutado: rrf (el texto completo, completado con lo "
            "que la similitud vectorial trajo de más o confirmó), fts (texto completo "
            "sobre anuncios y pliegos), "
            "like (coincidencia literal) o filtros (la frase eran solo filtros: lo "
            "más reciente del ámbito). No se declara por configuración."
        )
    )
    hits: list[SemanticHit]
    hay_mas: bool = Field(
        default=False,
        description=(
            "El motor tenía más resultados que top_k: pedir un top_k mayor trae "
            "la siguiente tanda. No es un total; contarlo costaría la búsqueda entera."
        ),
    )
    elapsed_ms: int
    interpretacion: Interpretacion = Field(
        description="Los filtros y términos que salieron de la frase y se aplicaron.",
    )


# ── Endpoint ─────────────────────────────────────────────────────────────────


@router.post(
    "/search/semantic",
    response_model=SemanticSearchResponse,
    summary="Búsqueda de texto completo en anuncios y pliegos, con fusión semántica",
    description=(
        "Interpreta los filtros que diga la frase, busca por texto completo en los "
        "anuncios y en los pasajes de pliego (tsvector/ts_rank_cd) y, si la flag "
        "busqueda_semantica está encendida para quien busca y la instalación tiene "
        "embeddings con los que codificar la consulta, completa la lista con lo que "
        "la fusión (RRF, ponderada por alpha) encuentra por significado; si no, o si "
        "la fusión falla, responde solo por texto, sin error. Si el texto no encuentra nada degrada a coincidencia literal; "
        "el campo source de la respuesta dice cuál de los caminos se ejecutó."
    ),
)
async def semantic_search(
    body: SemanticSearchRequest,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> SemanticSearchResponse:
    """Búsqueda semántica híbrida."""
    import time

    t0 = time.perf_counter()

    # Pura y sin BD: se entiende la frase antes de despachar al pool.
    consulta, ambito = preparar_consulta(
        body.q,
        ccaa=body.ccaa,
        tecnologia=body.tecnologia,
        fecha_desde=body.fecha_desde,
        fecha_hasta=body.fecha_hasta,
        interpretar_filtros=body.interpretar,
    )

    def _run() -> Resultado:
        from services.investigador.busqueda import buscar, semantica_activa

        # Uno de más: si llega, hay otra tanda que pedir.
        return buscar(
            consulta,
            ambito,
            body.top_k + 1,
            alpha=body.alpha,
            semantica=semantica_activa(ctx.get("email")),
        )

    try:
        resultado = await run_ml(_run)
    except Exception as exc:
        log.error("semantic_search.failed", error=str(exc), q_len=len(body.q))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El servicio de búsqueda semántica no está disponible temporalmente.",
        ) from exc
    source = resultado.fuente
    hay_mas = len(resultado.hits) > body.top_k
    hits = resultado.hits[: body.top_k]

    elapsed_ms = round((time.perf_counter() - t0) * 1000)

    log.info(
        "semantic_search.ok",
        # El texto de la consulta no se escribe: es la estrategia comercial de
        # quien lo busca, y la analítica del frontend tampoco lo manda. La
        # longitud y los términos que quedaron bastan para leer el log.
        q_len=len(body.q),
        n=len(hits),
        source=source,
        # ``alpha`` solo se interpreta cuando ``source`` es rrf; loguear ambos
        # juntos es lo que permite saber, sin abrir la BD, si esa instalación
        # tiene embeddings que fusionar.
        alpha=body.alpha,
        # Qué fue de la búsqueda por significado (apagada, sin_motor,
        # sin_aporte, error, servida…) y cuánto costó: con la flag encendida,
        # es lo que distingue «sirve significado» de «degrada a texto».
        semantica=resultado.semantica,
        fusion_ms=resultado.fusion_ms,
        # Si la frase traía filtros y cuántos términos quedaron: una búsqueda
        # sin resultados se lee distinto si se entendió «en Madrid» que si no.
        filtros_entendidos=consulta.tiene_filtros,
        n_terminos=len(consulta.terminos),
        elapsed_ms=elapsed_ms,
        user=ctx.get("user_id"),
    )

    campos = SemanticHit.model_fields
    return SemanticSearchResponse(
        q=body.q,
        top_k=body.top_k,
        source=source,
        hits=[SemanticHit(**{k: v for k, v in h.items() if k in campos}) for h in hits],
        hay_mas=hay_mas,
        elapsed_ms=elapsed_ms,
        interpretacion=Interpretacion.de(consulta),
    )


@router.get(
    "/search/global",
    summary="Búsqueda unificada para la paleta: expedientes, empresas, órganos y oportunidades",
    responses={
        401: {"description": "Autenticación inválida"},
        403: {"description": "Sin membresía en la organización pedida"},
    },
)
async def get_search_global(
    q: str = Query(..., max_length=_MAX_Q_LEN, description="Término de búsqueda"),
    organization_id: int | None = Query(
        default=None,
        ge=1,
        description=(
            "Sin él **no se buscan oportunidades**, que no es lo mismo que no "
            "encontrar ninguna: la respuesta lo declara en `tipos_buscados`."
        ),
    ),
    limit: int = Query(5, ge=1, le=20, description="Máximo por tipo"),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> BusquedaGlobal:
    """F1.2 — un término, cuatro clases de resultado.

    Un término demasiado corto devuelve 200 con `sin_busqueda`, no un 422: la
    paleta consulta en cada tecla y un error por escribir dos letras sería un
    error en la mitad de las pulsaciones.
    """
    # La organización se **resuelve**, no se cree: el filtro de oportunidades
    # es `WHERE p.organization_id = %s`, así que pasar el valor crudo de la
    # query convertía la paleta en un enumerador del pipeline ajeno. Sin
    # `organization_id` no se resuelve nada, porque `None` aquí significa «no
    # busques oportunidades», no «la organización por defecto».
    resuelta: int | None = None
    if organization_id is not None:
        ambito = await resolve_organization_ctx(ctx, organization_id)
        resuelta = int(ambito["organization_id"])
    return await run_db(buscar_global, q, organization_id=resuelta, limite_por_tipo=limit)
