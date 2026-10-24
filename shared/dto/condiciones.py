"""Condiciones oficiales de PLACSP (v148): criterios, garantías y solvencia."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ── Condiciones oficiales de PLACSP (v148) ──────────────────────────────────
#
# Criterios, garantías y solvencia tal como los publica el anuncio CODICE
# (`scraper.codice_parser.parse_condiciones`). Viven aquí porque los comparten
# la ruta que los sirve (`GET /licitaciones/{id}/condiciones-oficiales`) y el
# checklist Go/No-Go (`services/go_no_go.py`), que contrasta la solvencia
# oficial cuando existe. Son el contrato de la **fuente primaria**; la ficha
# LLM del pliego (`shared/tender_facts.py`) es otro contrato y no se mezcla.
#
# Los `*_codigo` son los códigos crudos de las listas de CODICE, sin traducir:
# sus listas no están verificadas en el repo, y una etiqueta de memoria sería
# plausible pero falsa.

ClaseSolvenciaOficial = Literal["tecnica", "economica", "clasificacion"]


class CriterioOficial(BaseModel):
    """Un criterio de adjudicación publicado (`cac:AwardingCriteria`)."""

    model_config = ConfigDict(extra="forbid")

    orden: int = Field(ge=1)
    #: `orden` del criterio del que cuelga, si es un subcriterio.
    padre_orden: int | None = Field(default=None, ge=1)
    descripcion: str | None = None
    #: `cbc:WeightNumeric` tal como lo publica el órgano, en su escala.
    peso: float | None = None
    #: El mismo peso sobre 100, solo cuando la escala de su ámbito es deducible
    #: (la suma de los criterios raíz da ~100 o ~1). Nulo en los subcriterios.
    peso_pct: float | None = None
    #: Inferido de la descripción o el tipo; no es un campo de CODICE.
    es_precio: bool = False
    tipo_codigo: str | None = None
    subtipo_codigo: str | None = None
    nota: str | None = None


class GarantiaOficial(BaseModel):
    """Una garantía exigida (`cac:RequiredFinancialGuarantee`)."""

    model_config = ConfigDict(extra="forbid")

    orden: int = Field(ge=1)
    tipo_codigo: str | None = None
    #: `cbc:AmountRate` tal cual: 5 es el 5 %.
    porcentaje: float | None = None
    #: `cbc:LiabilityAmount`.
    importe: float | None = None
    moneda: str | None = None
    descripcion: str | None = None


class RequisitoSolvenciaOficial(BaseModel):
    """Un requisito de solvencia (`cac:TendererQualificationRequest`)."""

    model_config = ConfigDict(extra="forbid")

    orden: int = Field(ge=1)
    clase: ClaseSolvenciaOficial
    #: Código de criterio de evaluación; en `clasificacion`, la categoría.
    tipo_codigo: str | None = None
    descripcion: str | None = None
    #: `cbc:ThresholdAmount`.
    umbral_importe: float | None = None
    moneda: str | None = None


class CondicionesAmbito(BaseModel):
    """Las condiciones de un ámbito: el expediente (`lote_numero` nulo) o un lote."""

    model_config = ConfigDict(extra="forbid")

    lote_numero: str | None = None
    lote_titulo: str | None = None
    criterios: list[CriterioOficial] = Field(default_factory=list)
    garantias: list[GarantiaOficial] = Field(default_factory=list)
    solvencia: list[RequisitoSolvenciaOficial] = Field(default_factory=list)


class CondicionesOficiales(BaseModel):
    """Lo que la publicación oficial dice de un expediente, por ámbito.

    `ambitos` vacío significa que el anuncio no publica estos bloques —o que el
    expediente se ingirió antes de v148 y no se ha vuelto a leer—, no que el
    pliego no los tenga: para eso está la ficha del pliego.
    """

    model_config = ConfigDict(extra="forbid")

    #: El expediente cuya publicación se lee. Una republicación confirmada
    #: (TED de un expediente de PLACSP) devuelve la del original.
    licitacion_id: str
    fuente: Literal["placsp"] = "placsp"
    #: Enlace a la publicación en la Plataforma, para comprobarla allí.
    url_publicacion: str | None = None
    #: Última vez que la ingesta escribió estas filas (ISO 8601).
    actualizado: str | None = None
    ambitos: list[CondicionesAmbito] = Field(default_factory=list)
