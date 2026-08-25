"""Rutas ``/api/v1/publico`` — superficie anónima e indexable.

Es el único router de la API sin dependencia de autenticación, y por eso todo
en él es deliberado:

**El prefijo propio no es estético.** ``api/app.py`` registra al final, y a
propósito, un catch-all ``/api/v1/licitaciones/{id_externo:path}`` que exige
``require_any_auth`` (existe para que los expedientes con barras en el id
lleguen al handler). Cualquier ruta pública que colgara de
``/api/v1/licitaciones/`` quedaría ensombrecida por él y devolvería 401 al
tráfico anónimo, sin un solo error visible en el arranque. Colgar de
``/publico`` elimina la clase entera de problema.

**Ni un campo derivado del pipeline propio.** La proyección vive en
``db/repositories/publico.py`` como allowlist explícita y los DTO son nuevos
—``LicitacionPublica``, no ``LicitacionSummary``— porque los privados arrastran
``tecnologia``, ``ml_tecnologias``, ``ml_proba_max`` y ``ml_tech_principal``.
``scripts/check_public_surface.py`` lo verifica en CI.

**Nada de ``adjudicaciones``.** El adjudicatario puede ser un autónomo y no hay
lógica en el repositorio que distinga persona física de jurídica, así que la
tabla se queda entera detrás del login. Decisión del dueño del producto.

**Entrada de internet, salida sin 5xx.** ``scripts/fuzz_api_contract.py``
mantiene ``KNOWN_5XX`` a cero: una referencia inventada tiene que acabar en un
404 limpio. Por eso ``decodificar_ref`` devuelve ``None`` en vez de lanzar.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from api.concurrency import run_db
from db.repositories.publico import PublicoRepository
from observability.logging import get_logger
from shared.dto import LicitacionPublica, LotePublico, PaginatedResponse
from shared.public_ref import codificar_ref, decodificar_ref

log = get_logger(__name__)

router = APIRouter(tags=["publico"])

_repo = PublicoRepository()

# Cacheabilidad de la superficie pública.
#
# El dato cambia como mucho cada cuatro horas (la cadencia del cron de ingesta),
# así que revalidar en cada visita es puro desperdicio. `s-maxage` alto deja el
# trabajo en el CDN, y `stale-while-revalidate` evita que una oleada de
# rastreadores golpee Postgres a la vez cuando expira la entrada.
#
# El `ETagMiddleware` respeta este valor para peticiones sin cookie y lo
# sustituye por `private, no-cache` si la petición trae una; además emite
# `Vary: Cookie, X-API-Key`, que es lo que impide que un CDN mezcle ambas.
_CACHE_PUBLICA = "public, max-age=300, s-maxage=3600, stale-while-revalidate=86400"

# Tope de página. Más bajo que el de la API privada a propósito: aquí el
# consumidor son rastreadores y el coste de una página grande lo paga Postgres.
_MAX_LIMITE_PUBLICO = 100


class EntradaSitemap(BaseModel):
    """Lo mínimo para construir una URL de sitemap y su ``lastmod``."""

    ref: str
    ccaa: str | None = None
    titulo: str
    actualizado: str | None = None


def _a_dto(
    fila: dict[str, object], lotes: list[dict[str, object]] | None = None
) -> LicitacionPublica:
    """Construye el DTO público desde una fila del repositorio.

    El mapeo es explícito campo a campo, no ``LicitacionPublica(**fila)``. Con
    el desempaquetado, una columna nueva en la proyección llegaría al DTO sin
    que nadie lo decidiera; así hay que escribirla aquí, que es donde toca
    pensárselo.
    """
    id_externo = str(fila["id_externo"])
    return LicitacionPublica(
        ref=codificar_ref(id_externo),
        expediente=id_externo,
        titulo=str(fila["titulo"]),
        descripcion=fila.get("descripcion"),  # type: ignore[arg-type]
        organo_contratacion=fila.get("organo_contratacion"),  # type: ignore[arg-type]
        importe=fila.get("importe"),  # type: ignore[arg-type]
        moneda=fila.get("moneda"),  # type: ignore[arg-type]
        cpv=fila.get("cpv"),  # type: ignore[arg-type]
        tipo_contrato=fila.get("tipo_contrato"),  # type: ignore[arg-type]
        estado=fila.get("estado"),  # type: ignore[arg-type]
        procedimiento=fila.get("procedimiento"),  # type: ignore[arg-type]
        tramitacion=fila.get("tramitacion"),  # type: ignore[arg-type]
        fecha_publicacion=fila.get("fecha_publicacion"),  # type: ignore[arg-type]
        fecha_limite=fila.get("fecha_limite"),  # type: ignore[arg-type]
        fecha_inicio=fila.get("fecha_inicio"),  # type: ignore[arg-type]
        fecha_fin=fila.get("fecha_fin"),  # type: ignore[arg-type]
        duracion_valor=fila.get("duracion_valor"),  # type: ignore[arg-type]
        duracion_unidad=fila.get("duracion_unidad"),  # type: ignore[arg-type]
        provincia=fila.get("provincia"),  # type: ignore[arg-type]
        ccaa=fila.get("ccaa"),  # type: ignore[arg-type]
        nuts_code=fila.get("nuts_code"),  # type: ignore[arg-type]
        url=fila.get("url"),  # type: ignore[arg-type]
        fuente=str(fila.get("fuente") or "placsp"),
        actualizado=fila.get("fecha_extraccion"),  # type: ignore[arg-type]
        lotes=[
            LotePublico(
                numero=str(lote["numero"]),
                titulo=lote.get("titulo"),  # type: ignore[arg-type]
                cpv=lote.get("cpv"),  # type: ignore[arg-type]
                importe=lote.get("importe"),  # type: ignore[arg-type]
                fecha_limite=lote.get("fecha_limite"),  # type: ignore[arg-type]
            )
            for lote in (lotes or [])
        ],
    )


@router.get(
    "/publico/licitaciones",
    response_model=PaginatedResponse[LicitacionPublica],
    summary="Listado público de licitaciones",
    responses={
        200: {"description": "Página de anuncios publicables"},
        422: {"description": "Parámetros inválidos"},
    },
)
async def listar_publicas(
    response: Response,
    ccaa: str | None = Query(
        None,
        max_length=100,
        pattern=r"^[a-z0-9-]+$",
        description="Slug de comunidad autónoma, p.ej. `comunidad-valenciana`",
    ),
    cpv: str | None = Query(
        None, max_length=10, pattern=r"^\d{2,8}$", description="Prefijo de código CPV"
    ),
    limit: int = Query(50, ge=1, le=_MAX_LIMITE_PUBLICO),
    offset: int = Query(0, ge=0, le=1_000_000),
) -> PaginatedResponse[LicitacionPublica]:
    """Anuncios publicables, del más reciente al más antiguo.

    ``total`` es el recuento real con los filtros aplicados, no el tamaño de la
    página. Lo necesita la paginación del hub: sin él no se puede saber si hay
    página siguiente ni enlazar a la última, y un hub sin paginación deja
    huérfanas todas las fichas a partir de la primera cincuentena — solo
    alcanzables por sitemap, que las hace rastreables pero no les transmite
    ninguna autoridad.
    """
    filas = await run_db(
        _repo.listar,
        ccaa_slug=ccaa,
        cpv_prefijo=cpv,
        limite=limit,
        desplazamiento=offset,
    )
    total = await run_db(_repo.contar, ccaa_slug=ccaa, cpv_prefijo=cpv)
    response.headers["Cache-Control"] = _CACHE_PUBLICA
    return PaginatedResponse[LicitacionPublica](
        total=total, limit=limit, offset=offset, items=[_a_dto(f) for f in filas]
    )


@router.get(
    "/publico/licitaciones/{ref}",
    response_model=LicitacionPublica,
    summary="Anuncio público de una licitación",
    responses={
        200: {"description": "Anuncio con sus lotes"},
        404: {"description": "No existe, es duplicado, o no supera el umbral de sustancia"},
    },
)
async def ficha_publica(ref: str, response: Response) -> LicitacionPublica:
    """Anuncio oficial de un expediente, por su referencia pública.

    Los tres motivos de 404 —no existe, es un duplicado no canónico, o es
    demasiado pobre para ser una página— se devuelven indistinguibles a
    propósito: para el visitante son el mismo caso, y distinguirlos filtraría
    qué expedientes existen en la base pero se ocultan.
    """
    id_externo = decodificar_ref(ref)
    if id_externo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontrada.")

    fila = await run_db(_repo.ficha, id_externo)
    if fila is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontrada.")

    lotes = await run_db(_repo.lotes_de, id_externo)
    response.headers["Cache-Control"] = _CACHE_PUBLICA
    return _a_dto(fila, lotes)


class HubCcaa(BaseModel):
    """Una comunidad autónoma con página de índice propia."""

    slug: str
    nombre: str
    total: int = Field(ge=0)


class HubCpv(BaseModel):
    """Un código CPV con página de índice propia."""

    codigo: str
    total: int = Field(ge=0)


class Hubs(BaseModel):
    """Índice de la superficie pública."""

    ccaa: list[HubCcaa]
    cpv: list[HubCpv]


@router.get(
    "/publico/hubs",
    response_model=Hubs,
    summary="Comunidades y códigos CPV con página de índice",
)
async def hubs(response: Response) -> Hubs:
    """Alimenta las páginas `/licitaciones` y `/cpv`.

    Ambas listas van filtradas por volumen mínimo en el repositorio: un hub con
    dos licitaciones no es una página, es contenido delgado.

    Va en un solo endpoint y no en dos porque sus dos consumidores —los índices
    y los enlaces de la portada— quieren las dos listas a la vez, y así una
    página de índice hace una llamada en vez de dos.
    """
    ccaa, cpv = await run_db(_repo.hubs_ccaa), await run_db(_repo.hubs_cpv)
    response.headers["Cache-Control"] = _CACHE_PUBLICA
    return Hubs(
        ccaa=[
            HubCcaa(slug=str(h["slug"]), nombre=str(h["nombre"]), total=int(h["total"]))
            for h in ccaa
        ],
        cpv=[HubCpv(codigo=str(h["codigo"]), total=int(h["total"])) for h in cpv],
    )


class ResumenSitemap(BaseModel):
    """Tamaño y frescura del corpus publicable.

    ``total`` dimensiona la partición del sitemap; ``actualizado`` es la fecha
    de incorporación del expediente publicable más reciente, y lo consume la
    franja de cifras de la landing.

    ``actualizado`` es opcional porque un corpus vacío no tiene fecha que dar.
    El consumidor tiene que tratar ese caso como "todavía no lo sé" y no
    pintarlo: inventar una fecha ahí sería fabricar la prueba de frescura que
    el dato existe para respaldar.
    """

    total: int = Field(ge=0)
    actualizado: str | None = None


@router.get(
    "/publico/sitemap/resumen",
    response_model=ResumenSitemap,
    summary="Tamaño y frescura del corpus publicable",
)
async def resumen_sitemap(response: Response) -> ResumenSitemap:
    """Lo consumen ``generateSitemaps`` de Next y la franja de cifras de la landing.

    Las dos consultas van en el mismo endpoint —y no en uno nuevo— porque son
    el mismo hecho sobre el mismo corpus y comparten cacheabilidad: separarlas
    duplicaría el ``WHERE`` de publicabilidad en dos rutas que tendrían que
    moverse a la vez.
    """
    total = await run_db(_repo.contar)
    actualizado = await run_db(_repo.ultima_incorporacion)
    response.headers["Cache-Control"] = _CACHE_PUBLICA
    return ResumenSitemap(total=total, actualizado=actualizado)


@router.get(
    "/publico/sitemap/entradas",
    response_model=list[EntradaSitemap],
    summary="Tramo de URLs para un fichero de sitemap",
)
async def entradas_sitemap(
    response: Response,
    offset: int = Query(0, ge=0, le=10_000_000),
    limit: int = Query(1000, ge=1, le=50_000),
) -> list[EntradaSitemap]:
    """Un tramo estable de expedientes publicables.

    El orden lo fija el repositorio por ``id_externo`` y no por fecha: con orden
    temporal, un expediente republicado saltaría de fichero y el mismo tramo
    devolvería URLs distintas en cada regeneración.
    """
    filas = await run_db(_repo.pagina_de_sitemap, desplazamiento=offset, tamano=limit)
    response.headers["Cache-Control"] = _CACHE_PUBLICA
    return [
        EntradaSitemap(
            ref=codificar_ref(str(f["id_externo"])),
            ccaa=f.get("ccaa"),
            titulo=str(f["titulo"]),
            actualizado=str(f["fecha_extraccion"]) if f.get("fecha_extraccion") else None,
        )
        for f in filas
    ]
