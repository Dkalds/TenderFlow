"""Acuerdos marco y sistemas dinámicos de adquisición en la ficha (v178)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.sistema_contratacion import SistemaContratacion

#: De dónde sale la fecha de fin: ``db.sql_fragments.ORIGENES_FECHA_FIN``.
OrigenFechaFin = Literal["real", "estimada_inicio", "estimada_adjudicacion", "desconocida"]


class AdmitidoMarco(BaseModel):
    """Una empresa admitida en el marco: adjudicataria de alguno de sus lotes."""

    model_config = ConfigDict(extra="forbid")

    #: El nombre tal como lo publicó la fuente.
    nombre: str
    nif: str | None = None
    #: Números de los lotes en los que está admitida. Vacío si el marco se
    #: adjudicó sin lotes.
    lotes: list[str] = Field(default_factory=list)
    #: Es la organización que mira, por sus NIF declarados.
    es_tu_organizacion: bool = False


class VigenciaMarco(BaseModel):
    """Hasta cuándo está vivo el marco. Es la fecha que usa Renovaciones."""

    model_config = ConfigDict(extra="forbid")

    #: ``YYYY-MM-DD``. ``None`` si la fuente no publica fecha de fin, o publica
    #: solo una duración y aún no hay inicio ni adjudicación desde los que contarla.
    fecha_fin: str | None = None
    origen: OrigenFechaFin
    dias_restantes: int | None = None
    #: La duración publicada, en ``ANN``, ``MON`` o ``DAY``. Es lo único que
    #: hay de un marco que aún se está licitando.
    duracion_valor: float | None = None
    duracion_unidad: Literal["ANN", "MON", "DAY"] | None = None


class MarcoEnlazado(BaseModel):
    """El marco del que cuelga un contrato basado, cuando está en el producto."""

    model_config = ConfigDict(extra="forbid")

    licitacion_id: str
    titulo: str
    organo_contratacion: str | None = None
    sistema: SistemaContratacion | None = None


class ContratoBasado(BaseModel):
    """Un contrato basado que cita al marco."""

    model_config = ConfigDict(extra="forbid")

    licitacion_id: str
    titulo: str
    organo_contratacion: str | None = None
    estado: str | None = None
    importe: float | None = None
    fecha_publicacion: str | None = None


class MarcoDeLicitacion(BaseModel):
    """Lo que se sabe del acuerdo marco o el SDA de un expediente.

    En un marco o un SDA, ``admitidos`` y ``vigencia`` son los suyos. En un
    contrato basado son los de su marco **entero** —la fuente no dice de qué
    lote cuelga el basado—, y solo llegan si publica cuál es y ese marco está
    en el producto (``marco``). Donde no se sabe,
    ``admitidos_total``, ``organizacion_admitida`` y ``basados_total`` son
    ``None`` —sin dato—, nunca cero.
    """

    model_config = ConfigDict(extra="forbid")

    licitacion_id: str
    #: ``None`` si la fuente no dice qué sistema de contratación es.
    sistema: SistemaContratacion | None = None
    #: ``False`` si la organización no ha declarado ningún NIF: sin él no se
    #: puede decir si está entre los admitidos.
    identidad_conocida: bool
    #: Solo en un basado: su marco, si la fuente lo publica y está en el producto.
    marco: MarcoEnlazado | None = None
    #: Solo en un basado cuyo marco se conoce pero no está en el producto: la
    #: referencia tal como se puede buscar fuera («TED 649072-2024»).
    marco_referencia: str | None = None
    #: Empresas distintas admitidas en el marco. ``None`` si no se conoce el
    #: marco, o si su fila no consta todavía como marco.
    admitidos_total: int | None = Field(default=None, ge=0)
    #: La organización que mira va la primera; el resto, por orden alfabético,
    #: hasta el tope de la respuesta.
    admitidos: list[AdmitidoMarco] = Field(default_factory=list)
    #: ``None`` si no se puede saber: sin NIF declarado, sin admitidos
    #: publicados, algún admitido sin NIF, o un basado sin marco conocido.
    organizacion_admitida: bool | None = None
    vigencia: VigenciaMarco | None = None
    #: Solo en un marco o un SDA: contratos basados que lo citan. ``None`` si
    #: ninguno lo cita: no se distingue de que su fuente no publique el enlace,
    #: así que nunca es cero.
    basados_total: int | None = Field(default=None, ge=0)
    #: Los más recientes, hasta el tope de la respuesta.
    basados: list[ContratoBasado] = Field(default_factory=list)
