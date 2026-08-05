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


class TenderFactSheet(BaseModel):
    """Ficha de decisión derivada de pliegos, validada y citable."""

    model_config = ConfigDict(extra="forbid")

    award_criteria: list[WeightedCriterion] = Field(default_factory=list, max_length=50)
    technical_solvency: list[FactItem] = Field(default_factory=list, max_length=50)
    economic_solvency: list[MonetaryFact] = Field(default_factory=list, max_length=50)
    guarantees: list[MonetaryFact] = Field(default_factory=list, max_length=30)
    penalties: list[MonetaryFact] = Field(default_factory=list, max_length=30)
    subcontracting: list[FactItem] = Field(default_factory=list, max_length=30)
    team_requirements: list[TeamRequirement] = Field(default_factory=list, max_length=50)
    extensions: list[FactItem] = Field(default_factory=list, max_length=30)
    critical_deadlines: list[DeadlineFact] = Field(default_factory=list, max_length=30)
    technologies: list[TechnologyMention] = Field(default_factory=list, max_length=30)


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
