"""Contrato estricto de la ficha estructurada de un pliego.

Los valores extraídos nunca viajan solos: cada elemento declara confianza y
evidencia anclada a una página persistida. ``extra='forbid'`` convierte cambios
del extractor o respuestas inesperadas del LLM en fallos visibles, no en datos
silenciosamente ignorados.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EvidenceRef(BaseModel):
    """Cita verificable a texto persistido de un documento."""

    model_config = ConfigDict(extra="forbid")

    documento_id: int = Field(gt=0)
    page_number: int = Field(gt=0)
    quote: str = Field(min_length=1, max_length=600)
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)


class FactItem(BaseModel):
    """Hecho textual con confianza y una o más citas."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(ge=0, le=1)
    evidence: list[EvidenceRef] = Field(default_factory=list, max_length=8)


class WeightedCriterion(FactItem):
    """Criterio de adjudicación y peso publicado, cuando existe."""

    name: str = Field(min_length=1, max_length=500)
    weight_pct: float | None = Field(default=None, ge=0, le=100)
    criterion_type: Literal["price", "quality", "automatic", "judgement", "other"] = "other"


class MonetaryFact(FactItem):
    """Importe exigido/previsto; ``amount_eur`` queda nulo si no es inequívoco."""

    amount_eur: float | None = Field(default=None, ge=0)


class TeamRequirement(FactItem):
    """Perfil o capacidad mínima del equipo."""

    role: str | None = Field(default=None, max_length=300)
    minimum_years: float | None = Field(default=None, ge=0)
    quantity: int | None = Field(default=None, ge=1)


class DeadlineFact(FactItem):
    """Hito temporal extraído del pliego."""

    name: str = Field(min_length=1, max_length=300)
    date_value: date | None = None


class TechnologyMention(FactItem):
    """Plataforma/tecnología mencionada explícitamente como objeto del
    contrato (no una mención de pasada -- ver la pregunta de extracción en
    ``services/rag/fact_sheet.py``). ``name`` es el nombre tal como aparece
    en el pliego; la normalización a ``TECH_LABELS`` la hace
    ``services.tech_signal.ingest_llm_technologies``, no el extractor."""

    name: str = Field(min_length=1, max_length=100)


class LotFact(FactItem):
    """Lote publicado; el número de lotes de la licitación es ``len(lots)``.

    ``lot_number`` se conserva como texto ("1", "Lote III"): los pliegos no
    numeran de forma uniforme y forzar un entero perdería el original citable.
    """

    lot_number: str | None = Field(default=None, max_length=50)
    name: str | None = Field(default=None, max_length=500)
    amount_eur: float | None = Field(default=None, ge=0)


class CertificationRequirement(FactItem):
    """Certificación exigida (ISO 27001, ENS, partner de fabricante, títulos
    de perfil). ``scope`` distingue si la acredita la empresa o el equipo."""

    name: str = Field(min_length=1, max_length=300)
    scope: Literal["company", "team", "other"] = "other"


class ServiceLevelFact(FactItem):
    """ANS/SLA: indicador y objetivo comprometido. Las penalizaciones por
    incumplirlo pertenecen a ``penalties``, no aquí."""

    name: str = Field(min_length=1, max_length=300)
    target: str | None = Field(default=None, max_length=300)


#: Cómo el pliego convierte una baja en puntos de precio.
#:
#: Se cataloga la **forma**, no la fórmula literal: los parámetros van aparte
#: para que el simulador pueda calcular sin interpretar texto. `otra` es la
#: salida honesta cuando el pliego usa algo que no encaja en las tres primeras
#: —y entonces el simulador **no calcula**, lo dice—, que es preferible a
#: aproximarla con la más parecida.
PriceFormulaType = Literal[
    # Puntos = max * (baja_propia / baja_mayor). La mas comun.
    "proporcional_inversa",
    # Tramos fijos de puntuación por franjas de baja.
    "lineal_por_tramos",
    # Proporcional pero con corte en el umbral de temeridad.
    "con_umbral_temeridad",
    "otra",
]


class PriceFormulaFact(FactItem):
    """F2.2 — la fórmula de valoración del precio, con sus parámetros.

    ``max_points`` es lo que reparte la fórmula; si el pliego no lo publica, el
    simulador cae al peso del precio (``licitaciones.peso_precio_pct``, v85) y
    lo declara. ``params`` guarda lo específico de cada tipo (los tramos, el
    umbral de temeridad) como números, nunca como texto a interpretar después:
    un simulador que parsee prosa en el momento de calcular es un simulador que
    da un número distinto cada vez que alguien toca el extractor.
    """

    formula_type: PriceFormulaType = "otra"
    max_points: float | None = Field(default=None, ge=0, le=100)
    #: Umbral de baja a partir del cual la oferta se considera anormalmente
    #: baja, en tanto por uno (0.25 = 25 %).
    umbral_temeridad: float | None = Field(default=None, ge=0, le=1)
    #: Parámetros numéricos del tipo. Claves libres pero **valores numéricos**:
    #: es lo que hace que el cálculo sea reproducible.
    params: dict[str, float] = Field(default_factory=dict)


class RequiredDocumentFact(FactItem):
    """F2.3 — un documento que el pliego exige presentar.

    ``scope`` es el sobre en el que va, que es lo que organiza el trabajo: el
    sobre A se prepara una vez y se reutiliza, el C se escribe para cada
    licitación. Sin él, el kit es una lista plana de veinte cosas sin orden de
    ataque.
    """

    name: str = Field(min_length=1, max_length=300)
    scope: Literal["sobre_a", "sobre_b", "sobre_c", "otro"] = "otro"
    #: ``True`` cuando el pliego lo marca como subsanable. `None` = no lo dice.
    subsanable: bool | None = None


class RateCardFact(FactItem):
    """F2.4 — tarifa máxima por perfil, con las horas si el pliego las da."""

    role: str = Field(min_length=1, max_length=300)
    max_rate_eur_hour: float | None = Field(default=None, ge=0)
    estimated_hours: float | None = Field(default=None, ge=0)


class BudgetLineFact(FactItem):
    """F2.4 — una línea del desglose del presupuesto publicado."""

    concept: str = Field(min_length=1, max_length=300)
    #: `salariales`, `directos`, `indirectos`, `beneficio` u `otro`. Es la
    #: partición que usan los pliegos españoles de servicios (art. 100 LCSP).
    category: Literal["salariales", "directos", "indirectos", "beneficio", "otro"] = "otro"
    amount_eur: float | None = Field(default=None, ge=0)
    pct: float | None = Field(default=None, ge=0, le=100)


class TenderFactSheet(BaseModel):
    """Ficha de decisión derivada de pliegos, validada y citable."""

    model_config = ConfigDict(extra="forbid")

    lots: list[LotFact] = Field(default_factory=list, max_length=50)
    award_criteria: list[WeightedCriterion] = Field(default_factory=list, max_length=50)
    technical_solvency: list[FactItem] = Field(default_factory=list, max_length=50)
    economic_solvency: list[MonetaryFact] = Field(default_factory=list, max_length=50)
    guarantees: list[MonetaryFact] = Field(default_factory=list, max_length=30)
    penalties: list[MonetaryFact] = Field(default_factory=list, max_length=30)
    service_levels: list[ServiceLevelFact] = Field(default_factory=list, max_length=50)
    subcontracting: list[FactItem] = Field(default_factory=list, max_length=30)
    team_requirements: list[TeamRequirement] = Field(default_factory=list, max_length=50)
    certifications: list[CertificationRequirement] = Field(default_factory=list, max_length=50)
    extensions: list[FactItem] = Field(default_factory=list, max_length=30)
    critical_deadlines: list[DeadlineFact] = Field(default_factory=list, max_length=30)
    technologies: list[TechnologyMention] = Field(default_factory=list, max_length=30)
    # ── Familias nuevas (F2.2, F2.3, F2.4) ────────────────────────────────
    #
    # Aditivas: una ficha extraída antes de esto se sigue validando, y las
    # listas vacías significan «el extractor no lo encontró», que es lo que la
    # UI dice en vez de proponer una lista genérica como si fuera del pliego.
    #: F2.2. Lista y no campo único porque un pliego multi-lote puede publicar
    #: una fórmula por lote; el simulador usa la del lote o la única que haya.
    price_formula: list[PriceFormulaFact] = Field(default_factory=list, max_length=10)
    #: F2.3.
    required_documents: list[RequiredDocumentFact] = Field(default_factory=list, max_length=60)
    #: F2.4.
    rate_cards: list[RateCardFact] = Field(default_factory=list, max_length=40)
    budget_breakdown: list[BudgetLineFact] = Field(default_factory=list, max_length=40)


FactSheetStatus = Literal["pending", "extracted", "needs_review", "failed"]


class TenderFactSheetRecord(BaseModel):
    """Envelope persistido y servido por API."""

    model_config = ConfigDict(extra="forbid")

    licitacion_id: str
    status: FactSheetStatus
    extraction_version: str
    model: str | None = None
    facts: TenderFactSheet | None = None
    field_count: int = Field(default=0, ge=0)
    evidence_count: int = Field(default=0, ge=0)
    error_detail: str | None = None
    extracted_at: str | None = None
    updated_at: str
