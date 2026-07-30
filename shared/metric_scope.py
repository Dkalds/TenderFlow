"""Metadatos obligatorios para interpretar una métrica de mercado."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MetricScope(BaseModel):
    """Universo y denominador explícitos de un agregado analítico."""

    model_config = ConfigDict(extra="forbid")

    label: str
    universe: str
    denominator_records: int = Field(ge=0)
    denominator_amount_eur: float = Field(ge=0)
    filters: dict[str, str]
    sources: list[str]
    filter_versions: list[str]
    model_versions: list[str]
    window_from: str | None = None
    window_to: str | None = None
    computed_at: str
    caveat: str
