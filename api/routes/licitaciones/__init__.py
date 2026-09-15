"""Rutas ``/api/v1/licitaciones`` y ``/api/v1/adjudicaciones``, por familias.

Por qué un paquete y no un módulo
---------------------------------
Esto era un fichero de 1.612 líneas con 21 operaciones. El problema no era el
tamaño: era que el **orden de declaración** dentro de él decidía el
comportamiento —una ruta con el conversor ``:path`` se come a las que vienen
detrás— y ese orden quedaba implícito en el sitio donde cada uno pegó su
endpoint. Partido por familias, el orden pasa a estar escrito aquí abajo, en un
sitio donde se lee, y hay un test que lo comprueba
(``tests/test_licitaciones_identificador.py``).

Las familias
------------
==================  =====================================================
``listado``         Muchos expedientes: offset, cursor, search, bulk-get
``ficha``           El expediente: detalle, similares, comparar
``documentos``      Adjuntos, páginas de pliego y reporte de dato
``pliegos``         Extracción de ficha técnica, guion, embeddings (caro)
``analitica``       Lo que se **deduce**: explain, tech-scores, tecnologías,
                    simulador
``adjudicaciones``  ``/adjudicaciones``, recurso propio de primer nivel
==================  =====================================================

``_base`` tiene lo que comparten (repositorios, validaciones, cursor, ETag) y
``modelos`` los DTO que usa más de una. Lo que usa una sola familia vive en su
módulo: si todo baja a ``_base``, el paquete es el fichero de 1.600 líneas con
directorios.

Los dos routers
---------------
``router`` lleva todo menos el detalle. ``router_detalle`` lleva **sólo**
``GET /licitaciones/{id_externo:path}``, que es glotón —casa también con
``/licitaciones/X/eventos``— y por eso ``api/app.py`` lo incluye el último de
todos, detrás incluso de ``eventos``, ``predicciones`` y ``ask``, que cuelgan
del mismo prefijo desde otros módulos. No lo juntes con ``router``: dejaría sin
ruta a media docena de endpoints de otros ficheros.
"""

from __future__ import annotations

from fastapi import APIRouter

from api.routes.licitaciones import (
    adjudicaciones,
    analitica,
    documentos,
    ficha,
    listado,
    pliegos,
)
from api.routes.licitaciones._base import (
    SUNSET_LISTADO_POR_OFFSET,
    _check_etag,
    _decode_cursor,
    _encode_cursor,
    _get_classifier,
    _make_etag,
)
from api.routes.licitaciones.adjudicaciones import AdjudicacionSummary
from api.routes.licitaciones.analitica import (
    ExplainFeature,
    ExplainPayload,
    ExplainResult,
    TechScore,
    TechScoresResult,
    TecnologiaDetalle,
    TecnologiasSenalResult,
)
from api.routes.licitaciones.documentos import (
    DocumentosResult,
    DocumentoSummary,
    ReporteDatoBody,
    ReporteDatoResult,
)
from api.routes.licitaciones.ficha import (
    CompararBody,
    SimilaresResult,
    SimilarOut,
    get_licitacion,
)
from api.routes.licitaciones.ficha import router_detalle as router_detalle
from api.routes.licitaciones.listado import (
    BulkGetRequest,
    BulkGetResult,
    SearchRequest,
)
from api.routes.licitaciones.modelos import (
    LicitacionDetail,
    LicitacionSummary,
    LoteOut,
)
from api.routes.licitaciones.pliegos import (
    ExpedienteJobEncolado,
    FactSheetExtractionState,
)

router = APIRouter(tags=["licitaciones"])

# El orden **sí** importa, aunque aquí ninguna ruta sea glotona: `listado` va
# primero porque es quien trae los segmentos fijos (`/cursor`, `/search`,
# `/bulk-get`), y una ruta fija declarada después de una paramétrica que la
# cubriera quedaría muerta. Mantenerlo así hace que añadir un endpoint nuevo no
# obligue a razonar sobre los otros veinte.
router.include_router(listado.router)
router.include_router(ficha.router)
router.include_router(documentos.router)
router.include_router(pliegos.router)
router.include_router(analitica.router)
router.include_router(adjudicaciones.router)

#: Lo que el resto del árbol importa de aquí. El paquete sustituye a un módulo
#: y tiene que seguir sirviendo los mismos nombres: hay tests que importan
#: `LicitacionSummary`, `SimilaresResult`, `_get_classifier` y
#: `SUNSET_LISTADO_POR_OFFSET` desde `api.routes.licitaciones`, y no había
#: ninguna razón para hacerles cambiar el import por una reorganización
#: interna.
__all__ = [
    "SUNSET_LISTADO_POR_OFFSET",
    "AdjudicacionSummary",
    "BulkGetRequest",
    "BulkGetResult",
    "CompararBody",
    "DocumentoSummary",
    "DocumentosResult",
    "ExpedienteJobEncolado",
    "ExplainFeature",
    "ExplainPayload",
    "ExplainResult",
    "FactSheetExtractionState",
    "LicitacionDetail",
    "LicitacionSummary",
    "LoteOut",
    "ReporteDatoBody",
    "ReporteDatoResult",
    "SearchRequest",
    "SimilarOut",
    "SimilaresResult",
    "TechScore",
    "TechScoresResult",
    "TecnologiaDetalle",
    "TecnologiasSenalResult",
    "_check_etag",
    "_decode_cursor",
    "_encode_cursor",
    "_get_classifier",
    "_make_etag",
    "get_licitacion",
    "router",
    "router_detalle",
]
