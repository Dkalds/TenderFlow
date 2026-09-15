"""Modelos de respuesta que **comparte más de una familia**.

``LicitacionSummary`` la devuelven el listado, la búsqueda y el bulk-get;
``LicitacionDetail`` y ``LoteOut``, la ficha; ``AdjudicacionSummary``, tanto
``/adjudicaciones`` como el detalle; ``DocumentoSummary``, la familia de
documentos. Los modelos de una sola familia se quedan en su módulo: bajarlos
aquí convertiría este fichero en el cajón de sastre que el paquete evita.

Tres de estos tienen homónimos en ``shared/dto.py`` con tipos distintos, y hay
un ratchet que lo vigila (``tests/test_shared_dto.py``). No es descuido: los de
allí son el contrato de la superficie pública y los de aquí el de la interna.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LicitacionSummary(BaseModel):
    id_externo: str
    titulo: str
    organo_contratacion: str | None = None
    importe: float | None = None
    estado: str | None = None
    fecha_publicacion: str | None = None
    # La fecha límite decide la urgencia de una licitación: sin ella un listado
    # no puede ordenar por cierre ni avisar de un plazo que se agota.
    fecha_limite: str | None = None
    ccaa: str | None = None
    cpv: str | None = None
    url: str | None = None
    tecnologia: str | None = None
    ml_tecnologias: str | None = None
    ml_proba_max: float | None = None
    ml_tech_principal: str | None = None


class LicitacionDetail(LicitacionSummary):
    descripcion: str | None = None
    tipo_contrato: str | None = None
    moneda: str | None = None
    provincia: str | None = None
    nuts_code: str | None = None
    duracion_valor: float | None = None
    duracion_unidad: str | None = None
    fecha_inicio: str | None = None
    fecha_fin: str | None = None
    raw_keywords: str | None = None
    fecha_extraccion: str | None = None
    # Fuente de ingesta (ADR-009): 'placsp', 'ted', 'pscp', 'euskadi_rss'… La
    # ficha etiquetaba su enlace externo como «Ver en PLACSP» pasara lo que
    # pasara, y con TED/PSCP/Euskadi el `url` no lleva a PLACSP: el texto
    # mentía. Sin este campo el frontend no tiene de dónde sacar la etiqueta —
    # `id_externo` no sirve, porque PLACSP es el legacy sin namespace.
    fuente: str | None = None
    # C4.2 / D23 — republicación.
    #
    # Un contrato reemitido (TED acuña un `publication-number` por anuncio;
    # PSCP cae al `id` de la fila cuando no hay expediente) deja de aparecer en
    # el Radar y en los listados, pero **sigue siendo alcanzable por URL**: un
    # enlace guardado no puede dar 404 porque un job nocturno decidió que era un
    # duplicado. Lo que la ficha hace es decirlo, con el id de la canónica para
    # que el usuario pueda ir al original.
    #
    # `None` = no es una republicación conocida.
    republicacion_de: str | None = None
    # C1.4 — los lotes del expediente. Lista vacía = lote único implícito,
    # que es el caso mayoritario; no significa «no medido».
    lotes: list[LoteOut] = Field(default_factory=list)


class LoteOut(BaseModel):
    """Un lote del expediente (C1.4).

    `GET /licitaciones/{id}` devolvía el expediente sin sus lotes, así que un
    multi-lote se presentaba como uno solo con el presupuesto total —la misma
    confusión que `EFFECTIVE_BUDGET_SQL` resolvió del lado del cálculo, sin
    resolver del lado de lo que el usuario ve.
    """

    numero: str
    titulo: str | None = None
    cpv: str | None = None
    importe: float | None = None
    fecha_limite: str | None = None


class AdjudicacionSummary(BaseModel):
    id: int
    licitacion_id: str
    nombre: str
    nif: str | None = None
    importe_adjudicado: float | None = None
    fecha_adjudicacion: str | None = None
    ccaa: str | None = None
    es_pyme: int | None = None
    n_ofertas_recibidas: int | None = None


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
