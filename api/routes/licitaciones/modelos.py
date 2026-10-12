"""Lo que **comparte más de una familia** del router de licitaciones. Nada más.

``LicitacionSummary`` es lo que devuelven el listado, la búsqueda y el
bulk-get; ``LicitacionDetail`` la extiende y la sirve la ficha. Viven juntas
porque una hereda de la otra: separar una clase de su base entre dos módulos
por seguir una regla sale peor que la regla. ``LoteOut`` y
``AdjudicatarioOut`` las acompañan por lo mismo — sólo los construye la ficha,
pero son el tipo de un campo de ``LicitacionDetail`` —.

Lo que **no** está aquí: ``AdjudicacionSummary`` vive en ``adjudicaciones`` y
``DocumentoSummary`` en ``documentos``, cada uno con su única familia. Un
módulo de «modelos» al que todo el mundo añade es el fichero de 1.600 líneas
con otro nombre, y el paquete existe justamente para no tenerlo.

Estos modelos tuvieron homónimos en ``shared/dto.py`` con tipos distintos, y
de ahí vienen los ratchets de ``tests/test_shared_dto.py`` y
``tests/test_contract_dto.py`` (ambos vacíos hoy): los de allí son el contrato
de la superficie pública y los de aquí el de la interna, y dos clases con el
mismo nombre y campos distintos hacen que nadie sepa cuál está leyendo.
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
    # F1.7 — código CODICE crudo de procedimiento y tramitación. La etiqueta
    # legible y su definición las sirve `GET /meta/filters` desde
    # `shared/procedimientos.py`: el listado no traduce, para que un código
    # nuevo llegue como código nuevo y la consola lo marque «no catalogado».
    procedimiento: str | None = None
    tramitacion: str | None = None


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


class AdjudicatarioOut(BaseModel):
    """Quién ganó el expediente (o uno de sus lotes), tal como lo publicó la fuente.

    Una fila por adjudicatario y lote, sin agregar ni resolver a empresa
    canónica: la ficha enseña lo publicado, y el maestro de empresas puede estar
    todavía corrigiendo la identidad en la cola de revisión. Lo que la fuente no
    publicó llega como ``None`` —nunca como cero—, porque un importe o un número
    de ofertas a cero se leerían como dato.

    El lote va por su **número** y su título, no por el id de ``lotes``: la
    re-ingesta borra y reinserta los lotes, y el id no sobrevive (``v110``).
    ``lote_numero`` ``None`` es la adjudicación del expediente completo.
    """

    nombre: str
    nif: str | None = None
    importe_adjudicado: float | None = None
    n_ofertas_recibidas: int | None = None
    fecha_adjudicacion: str | None = None
    lote_numero: str | None = None
    lote_titulo: str | None = None


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
    # El desenlace del expediente. Lista vacía = la ingesta no conoce ninguna
    # adjudicación, que es lo normal mientras está abierto; no significa que se
    # declarara desierto (eso lo dice `estado`).
    adjudicatarios: list[AdjudicatarioOut] = Field(default_factory=list)
