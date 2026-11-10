"""Modificaciones de contrato publicadas (art. 207.3 LCSP) en la ficha (v180)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: Base de un importe (ADR-032): el vocabulario de ``licitaciones.importe_tipo``.
BaseImporte = Literal["sin_iva", "con_iva", "desconocido"]


class ModificacionPublicada(BaseModel):
    """Una modificación tal como la publicó su fuente. Lo no publicado va a ``None``."""

    model_config = ConfigDict(extra="forbid")

    fuente: Literal["placsp", "ted"]
    #: Número de la modificación en PLACSP (``cbc:ID``).
    numero: str | None = None
    lote_numero: str | None = None
    #: ``YYYY-MM-DD``. En PLACSP, el del anuncio ``DOC_MOD`` solo cuando hay uno
    #: por modificación; en TED, la publicación del aviso.
    fecha_publicacion: str | None = None
    #: Código eForms del motivo (BT-200), solo TED.
    motivo_codigo: str | None = None
    #: El motivo en texto: ``cbc:Note`` en PLACSP, BT-201 en TED.
    motivo: str | None = None
    #: Qué se modifica (BT-202), solo TED.
    descripcion: str | None = None
    #: Lo que la modificación añade (o quita, si es negativo).
    importe_modificacion: float | None = None
    importe_modificacion_base: BaseImporte | None = None
    #: El importe del contrato tras la modificación.
    importe_final: float | None = None
    importe_final_base: BaseImporte | None = None
    moneda: str | None = None
    plazo_modificacion: float | None = None
    plazo_final: float | None = None
    #: ``ANN``, ``MON``, ``DAY``… tal como lo publica la fuente.
    plazo_unidad: str | None = None
    #: Número del aviso TED que se modifica (BT-1501).
    aviso_original: str | None = None
    url: str | None = None


class CosteDeContrato(BaseModel):
    """Lo adjudicado frente a lo que el contrato cuesta tras su última modificación.

    Solo cuando las dos cifras están publicadas y en la misma base (sin IVA).
    """

    model_config = ConfigDict(extra="forbid")

    #: ``None`` = el expediente sin lotes.
    lote_numero: str | None = None
    adjudicado: float
    final: float
    #: ``final / adjudicado - 1``, en tanto por ciento.
    variacion_pct: float
    base: Literal["sin_iva"] = "sin_iva"


class AmpliacionDelOrgano(BaseModel):
    """Cuánto acaban costando, sobre lo adjudicado, los contratos modificados del órgano.

    Solo cuentan los contratos con una modificación publicada que trae importe
    final y cuya adjudicación está publicada (``n``). Por debajo de
    ``muestra_minima`` no hay cifra: ``mediana_pct`` es ``None`` y la ficha dice
    «sin datos suficientes».
    """

    model_config = ConfigDict(extra="forbid")

    n: int
    muestra_minima: int
    #: Mediana de ``variacion_pct`` de esos contratos.
    mediana_pct: float | None = None
    base: Literal["sin_iva"] = "sin_iva"


class ModificacionesDeLicitacion(BaseModel):
    """Las modificaciones publicadas del expediente y lo que dicen de su coste."""

    model_config = ConfigDict(extra="forbid")

    items: list[ModificacionPublicada] = Field(default_factory=list)
    costes: list[CosteDeContrato] = Field(default_factory=list)
    #: El agregado del órgano del expediente; ``n`` es 0 si no tiene órgano o
    #: ninguno de sus contratos tiene el dato.
    organo: AmpliacionDelOrgano
