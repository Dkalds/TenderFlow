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

    #: ``YYYY-MM-DD``. ``None`` si la fuente no publica ni fecha ni duración.
    fecha_fin: str | None = None
    origen: OrigenFechaFin
    dias_restantes: int | None = None


class MarcoDeLicitacion(BaseModel):
    """Lo que se sabe del acuerdo marco o el SDA de un expediente.

    Para un marco o un SDA, sus admitidos y su vigencia. Para un contrato
    basado, solo que lo es: ninguna fuente publica de qué marco cuelga, así que
    ``admitidos_total`` y ``organizacion_admitida`` llegan a ``None`` —sin
    dato—, nunca a cero.
    """

    model_config = ConfigDict(extra="forbid")

    licitacion_id: str
    #: ``None`` si la fuente no dice qué sistema de contratación es.
    sistema: SistemaContratacion | None = None
    #: ``False`` si la organización no ha declarado ningún NIF: sin él no se
    #: puede decir si está entre los admitidos.
    identidad_conocida: bool
    #: Empresas distintas admitidas. ``None`` fuera de un marco o un SDA.
    admitidos_total: int | None = Field(default=None, ge=0)
    #: Las primeras por orden alfabético, hasta el tope de la respuesta.
    admitidos: list[AdmitidoMarco] = Field(default_factory=list)
    #: ``None`` si no se puede saber: sin NIF declarado, sin admitidos
    #: publicados, o en un contrato basado.
    organizacion_admitida: bool | None = None
    vigencia: VigenciaMarco | None = None
