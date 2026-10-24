"""Analítica compartida: cobertura de métricas, «Grandes en plazo» y dosier competitivo."""

from __future__ import annotations

from pydantic import BaseModel, Field

# ── «Grandes en plazo» (el campo que se llama `calientes`) ──────────────────
#
# Decisión del 2026-09-18 (P3 «Unificar la definición de Calientes»): el
# contador del Resumen y de la campana **mantiene su heurística de importe** y
# no adopta la banda `Caliente` del score. Responde a «cuáles son gordas y
# siguen vivas», que es otra pregunta que «cuáles merecen mi tiempo», y el
# score ya tiene su superficie (el Radar). La UI lo rotula «Grandes en plazo»
# desde el 2026-08-12; el nombre del campo se conserva porque es contrato
# público, y esta descripción es lo que el cliente generado lee en su lugar.
DESCRIPCION_GRANDES_EN_PLAZO = (
    "«Grandes en plazo»: licitaciones abiertas, en plazo y con importe ≥ P75 del "
    "ámbito. NO es la banda `Caliente` del score (≥ 75 puntos); el nombre del "
    "campo se conserva por compatibilidad del contrato."
)


# ── Clustering (F1) ─────────────────────────────────────────────────────────


class CoberturaMetricaDTO(BaseModel):
    """Cuántas filas sostienen realmente un porcentaje agregado.

    Un porcentaje sin denominador no es un hecho del mercado: es un hecho sobre
    qué filas traen el campo. El caso que motiva este DTO es «oferta única
    93,1 %» en la tira de salud competitiva del Resumen — el numerador cuenta
    ``n_ofertas_recibidas = 1`` y el denominador solo las filas con el campo
    informado, y la republicación masiva de PSCP no trae ese campo. Con ese
    sesgo de selección el número mide la fuente, no la competencia.

    Por eso cada porcentaje viaja con su base. Todos los campos son opcionales
    con default: añadirlos no rompe a ningún cliente del contrato, y el default
    (`base`/`cobertura_pct` desconocidas, ``suficiente=False``) es el
    conservador — quien no sabe su cobertura no puede afirmar su porcentaje.

    ``cobertura_pct`` se sirve **sin redondear a un número cómodo**: un 3,4 %
    tiene que llegar al cliente como 3,4 %, no como «bajo» ni como 0.
    """

    #: Filas con el campo informado — el denominador honesto del porcentaje.
    base: int | None = Field(default=None, ge=0)
    #: Filas del corpus consideradas (informadas o no).
    universo: int | None = Field(default=None, ge=0)
    #: ``base / universo * 100``. ``None`` = cobertura no medida, que **no** es
    #: lo mismo que cobertura cero: no autoriza a afirmar el porcentaje, pero
    #: tampoco a negarlo.
    cobertura_pct: float | None = Field(default=None, ge=0, le=100)
    #: Umbral por debajo del cual el consumidor no debe presentar la métrica
    #: como un hecho. Viaja con el dato para que el cliente no lo reinvente.
    umbral_pct: float = Field(default=50.0, ge=0, le=100)
    #: ``cobertura_pct is not None and cobertura_pct >= umbral_pct``. Lo decide
    #: el backend (ADR-014): el frontend presenta, no deriva analítica.
    suficiente: bool = False


# Competitive company dossier


class CompetitiveCompanyIdentityDTO(BaseModel):
    """Canonical identity displayed in a competitor dossier."""

    empresa_id: int = Field(ge=1)
    nombre: str
    nif: str | None = None
    es_ute: bool = False
    grupo: str | None = None


class CompetitiveCompanyTotalsDTO(BaseModel):
    """Headline activity and data-coverage metrics for the selected scope."""

    contratos: int = Field(default=0, ge=0)
    importe_total: float = Field(default=0, ge=0)
    importe_mediano: float | None = Field(default=None, ge=0)
    ofertas_medias: float | None = Field(default=None, ge=0)
    baja_media_pct: float | None = None
    pct_oferta_unica: float | None = Field(default=None, ge=0, le=100)
    cobertura_ofertas_pct: float = Field(default=0, ge=0, le=100)
    primera_adjudicacion: str | None = None
    ultima_adjudicacion: str | None = None
    organos: int = Field(default=0, ge=0)
    territorios: int = Field(default=0, ge=0)
    familias_cpv: int = Field(default=0, ge=0)


class CompetitiveCompanyBreakdownDTO(BaseModel):
    """Reusable amount/count distribution row (CPV, territory or buyer)."""

    codigo: str | None = None
    label: str
    cpv2: str | None = None
    ccaa: str | None = None
    organo: str | None = None
    contratos: int = Field(ge=0)
    importe: float = Field(ge=0)
    cuota_empresa_pct: float = Field(default=0, ge=0, le=100)
    ultima_adjudicacion: str | None = None


class CompetitiveCompanyYearDTO(BaseModel):
    """Annual activity point."""

    anio: int = Field(ge=1900, le=2200)
    contratos: int = Field(ge=0)
    importe: float = Field(ge=0)


class CompetitiveCompanyPositionDTO(BaseModel):
    """Market position inside the currently selected segment."""

    rank: int | None = Field(default=None, ge=1)
    empresas: int = Field(default=0, ge=0)
    cuota_pct: float | None = Field(default=None, ge=0, le=100)
    importe_segmento: float = Field(default=0, ge=0)


class CompetitiveCompanyComparisonDTO(BaseModel):
    """Current period compared with the immediately preceding equal period."""

    desde: str
    hasta: str
    anterior_desde: str
    anterior_hasta: str
    contratos: int = Field(default=0, ge=0)
    contratos_anterior: int = Field(default=0, ge=0)
    variacion_contratos_pct: float | None = None
    importe: float = Field(default=0, ge=0)
    importe_anterior: float = Field(default=0, ge=0)
    variacion_importe_pct: float | None = None
    importe_mediano: float | None = Field(default=None, ge=0)
    importe_mediano_anterior: float | None = Field(default=None, ge=0)


class CompetitiveCompanyConcentrationDTO(BaseModel):
    """Dependence on the most relevant public buyers."""

    organo_principal: str | None = None
    top1_contratos_pct: float = Field(default=0, ge=0, le=100)
    top1_importe_pct: float = Field(default=0, ge=0, le=100)
    top3_importe_pct: float = Field(default=0, ge=0, le=100)


class CompetitiveCompanySignalDTO(BaseModel):
    """Explainable movement or risk derived from observed awards."""

    kind: str
    tone: str = Field(pattern="^(positive|neutral|warning|negative)$")
    title: str
    detail: str


class CompetitiveCompanyScopeDTO(BaseModel):
    """Effective filters used to calculate a company dossier."""

    fecha_desde: str | None = None
    fecha_hasta: str | None = None
    cpv: str | None = None
    ccaas: list[str] = Field(default_factory=list)
    tecnologias: list[str] = Field(default_factory=list)
    importe_min: float | None = Field(default=None, ge=0)


class CompetitiveCompanyHistoryDTO(BaseModel):
    """Unfiltered company history, separate from the active analysis scope."""

    contratos: int = Field(default=0, ge=0)
    importe_total: float = Field(default=0, ge=0)
    primera_adjudicacion: str | None = None
    ultima_adjudicacion: str | None = None


class CompetitiveCompanyAwardDTO(BaseModel):
    """Award row in the paginated company history."""

    licitacion_id: str
    titulo: str | None = None
    organo_contratacion: str | None = None
    fecha_adjudicacion: str | None = None
    cpv: str | None = None
    ccaa: str | None = None
    tecnologia: str | None = None
    presupuesto_licitacion: float | None = Field(default=None, ge=0)
    importe_adjudicado: float | None = Field(default=None, ge=0)
    baja_pct: float | None = None
    n_ofertas_recibidas: int | None = Field(default=None, ge=0)
    expediente_url: str | None = None


class CompetitiveCompanyUteParticipationDTO(BaseModel):
    """UTE en la que la empresa participa como miembro, con su actividad propia.

    Deliberadamente separado de ``totales``/``posicion_mercado``, que solo
    cuentan lo adjudicado directamente a ``empresa_id`` -- sumarlo ahí
    duplicaría el importe ya atribuido a la UTE como entidad propia en
    cuota_mercado()/concentracion_hhi(). Esto es visibilidad adicional, no
    una redefinición de la cuota de mercado.
    """

    ute_empresa_id: int = Field(ge=1)
    ute_nombre: str
    otros_miembros: list[str] = Field(default_factory=list)
    contratos: int = Field(default=0, ge=0)
    importe_total: float = Field(default=0, ge=0)


class CompetitiveCompanyCorteDTO(BaseModel):
    """F3.5 — una celda de un corte del perfil (procedimiento o tramo de importe).

    Con ``n`` siempre; ``baja_media`` e ``importe_total`` solo cuando la celda
    llega al mínimo (``CompetitiveCompanyProfileDTO.corte_min_n``). La celda no
    se omite por debajo: que un competidor tenga dos adjudicaciones por
    negociado también dice algo, pero su media no.
    """

    clave: str
    n: int = Field(ge=0)
    baja_media: float | None = Field(
        default=None,
        description="Baja media en tanto por uno (0.12 = 12 %). Nula por debajo del mínimo.",
    )
    importe_total: float | None = Field(default=None, ge=0)


class CompetitiveCompanyProfileDTO(BaseModel):
    """Full competitor dossier used by quick and deep company views."""

    empresa: CompetitiveCompanyIdentityDTO
    scope: CompetitiveCompanyScopeDTO
    actividad_historica: CompetitiveCompanyHistoryDTO
    totales: CompetitiveCompanyTotalsDTO
    posicion_mercado: CompetitiveCompanyPositionDTO
    comparacion: CompetitiveCompanyComparisonDTO
    concentracion_clientes: CompetitiveCompanyConcentrationDTO
    por_cpv: list[CompetitiveCompanyBreakdownDTO] = Field(default_factory=list)
    por_ccaa: list[CompetitiveCompanyBreakdownDTO] = Field(default_factory=list)
    organos_principales: list[CompetitiveCompanyBreakdownDTO] = Field(default_factory=list)
    por_anio: list[CompetitiveCompanyYearDTO] = Field(default_factory=list)
    movimientos: list[CompetitiveCompanySignalDTO] = Field(default_factory=list)
    contratos_recientes: list[CompetitiveCompanyAwardDTO] = Field(default_factory=list)
    participaciones_ute: list[CompetitiveCompanyUteParticipationDTO] = Field(default_factory=list)
    #: F3.5 — bajas y adjudicaciones por tipo de procedimiento (etiqueta de
    #: F1.7) y por tramo de importe de licitación (fronteras LCSP), sobre la
    #: misma actividad filtrada que ``totales``.
    por_procedimiento: list[CompetitiveCompanyCorteDTO] = Field(default_factory=list)
    por_tramo_importe: list[CompetitiveCompanyCorteDTO] = Field(default_factory=list)
    #: Adjudicaciones mínimas por celda para publicar su media.
    corte_min_n: int = Field(default=5, ge=1)


class CompetitiveCompanyAwardsDTO(BaseModel):
    """Paginated award history for a canonical company."""

    items: list[CompetitiveCompanyAwardDTO] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(default=0, ge=0)
