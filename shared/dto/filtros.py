"""Filtros del listado de licitaciones: un objeto, no veintidós parámetros sueltos."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FiltrosLicitacion(BaseModel):
    """Los filtros que comparten el listado por offset, el cursor y su conteo.

    Hasta 2026-10-25 viajaban como parámetros sueltos por cinco firmas hermanas
    —las dos rutas de ``api/routes/licitaciones/listado.py`` y
    ``list_paginated``, ``list_cursor`` y ``_list_fts`` de
    ``db/repositories/licitaciones.py``— que había que mantener sincronizadas a
    mano: un filtro nuevo eran cinco ediciones y un sitio donde olvidarlo. Ahora
    la ruta lo construye una vez (con ``Depends``) y el repositorio lo recibe
    entero; ``_base_filters`` es el único que lo traduce a SQL.

    No es un modelo del contrato HTTP y no llega al OpenAPI: los parámetros de
    query, con sus descripciones y cotas (``ge``, ``max_length``…), siguen
    declarados uno a uno en las dependencias de la ruta, que es lo que el
    cliente generado lee. Aquí solo está la forma, y ``extra="forbid"`` para que
    un filtro mal escrito falle en vez de ignorarse.

    Los filtros multi-valor (``estado``, ``ccaa``, ``cpv``…) llegan como la
    cadena separada por comas de la query; los trocea ``csv_values`` en el
    repositorio, igual que antes.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    q: str | None = None
    estado: str | None = None
    solo_abiertas: bool = False
    ccaa: str | None = None
    tecnologia: str | None = None
    tecnologia_predicha: str | None = None
    min_proba_tech: float | None = None
    fecha_desde: str | None = None
    fecha_hasta: str | None = None
    cierre_desde: str | None = None
    cierre_hasta: str | None = None
    importe_min: float | None = None
    importe_max: float | None = None
    cpv: str | None = None
    organo: str | None = None
    provincia: str | None = None
    procedimiento: str | None = None
    tramitacion: str | None = None
    tipo_contrato: str | None = None
    dias_restantes_max: int | None = None
    #: Etiqueta de organización (F1.6) puesta como favorito.
    etiqueta_id: int | None = None
    #: Organización **ya resuelta** dueña de ``etiqueta_id`` (la ruta la valida
    #: contra la membresía antes de construir el objeto). Una etiqueta sin ella
    #: hace fallar la consulta en vez de filtrar por id a secas: ver
    #: ``_etiqueta_requerida`` en el repositorio.
    etiqueta_organization_id: int | None = None
