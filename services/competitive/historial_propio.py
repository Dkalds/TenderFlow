"""Tu historial con el órgano y el CPV de un expediente (ficha de la licitación).

La competencia esperada responde «contra quién»; esto responde «y yo, qué he
hecho aquí»: lo que la organización ha ganado con el mismo órgano y en el mismo
CPV-4, y cómo acabaron sus oportunidades con ese órgano. La identidad es la de
:func:`services.pursuit_awards.identidad_fiscal` (NIF declarados y su
``empresa_id``), la misma con la que la competencia esperada se quita de la
lista de rivales.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from db.repositories import competencia_esperada as repo
from db.repositories.competencia_esperada import (
    FilaAdjudicacionPropia,
    FilaOportunidadPorEstado,
    FilaResumenPropio,
    Segmento,
)
from db.sql_fragments import plegar_organo
from services.pursuit_awards import identidad_fiscal
from shared.cpv import cpv4 as _cpv4

#: Estados de oportunidad que cuentan como «te presentaste».
PRESENTADAS = frozenset({"submitted", "won", "lost"})


class ResumenPropio(BaseModel):
    """Lo ganado en un ámbito: con el órgano o en el CPV-4."""

    model_config = ConfigDict(extra="forbid")

    expedientes: int = Field(ge=0)
    importe: float = Field(ge=0)
    #: Mediana de la baja con la que ganaste, sobre ``bajas_n`` adjudicaciones
    #: con base comparable. ``None`` sin ninguna.
    baja_mediana_pct: float | None = None
    bajas_n: int = Field(ge=0)


class AdjudicacionPropia(BaseModel):
    """Una adjudicación ganada por la organización en el órgano o el CPV-4."""

    model_config = ConfigDict(extra="forbid")

    licitacion_id: str
    titulo: str | None = None
    organo_contratacion: str | None = None
    fecha_adjudicacion: str | None = None
    importe_adjudicado: float | None = None
    baja_pct: float | None = None
    mismo_organo: bool
    mismo_cpv4: bool


class OportunidadesConOrgano(BaseModel):
    """Cómo acabaron las oportunidades de la organización con este órgano."""

    model_config = ConfigDict(extra="forbid")

    total: int = Field(ge=0)
    presentadas: int = Field(ge=0)
    ganadas: int = Field(ge=0)
    perdidas: int = Field(ge=0)


class HistorialPropio(BaseModel):
    """Tu historial con el órgano y el CPV-4 del expediente."""

    model_config = ConfigDict(extra="forbid")

    licitacion_id: str
    #: ``False`` si la organización no ha declarado ningún NIF: sin él no se
    #: puede reconocer lo que ganó y el bloque lo dice en vez de enseñar ceros.
    identidad_conocida: bool
    organo: str | None = None
    cpv4: str | None = None
    con_organo: ResumenPropio | None = None
    en_cpv4: ResumenPropio | None = None
    oportunidades: OportunidadesConOrgano | None = None
    recientes: list[AdjudicacionPropia] = Field(default_factory=list)


def _resumen(filas: list[FilaResumenPropio], ambito: Literal["organo", "cpv4"]) -> ResumenPropio:
    fila = next((f for f in filas if f["ambito"] == ambito), None)
    if fila is None:
        return ResumenPropio(expedientes=0, importe=0.0, bajas_n=0)
    baja = fila["baja_mediana_pct"]
    return ResumenPropio(
        expedientes=int(fila["expedientes"]),
        importe=float(fila["importe"]),
        baja_mediana_pct=round(float(baja), 1) if baja is not None else None,
        bajas_n=int(fila["bajas_n"]),
    )


def _oportunidades(filas: list[FilaOportunidadPorEstado]) -> OportunidadesConOrgano:
    por_estado = {f["status"]: int(f["n"]) for f in filas}
    return OportunidadesConOrgano(
        total=sum(por_estado.values()),
        presentadas=sum(n for estado, n in por_estado.items() if estado in PRESENTADAS),
        ganadas=por_estado.get("won", 0),
        perdidas=por_estado.get("lost", 0),
    )


def _adjudicacion(f: FilaAdjudicacionPropia) -> AdjudicacionPropia:
    importe = f["importe_adjudicado"]
    baja = f["baja_pct"]
    fecha = f["fecha_adjudicacion"]
    return AdjudicacionPropia(
        licitacion_id=str(f["licitacion_id"]),
        titulo=f["titulo"],
        organo_contratacion=f["organo_contratacion"],
        fecha_adjudicacion=str(fecha)[:10] if fecha else None,
        importe_adjudicado=float(importe) if importe is not None else None,
        baja_pct=round(float(baja), 1) if baja is not None else None,
        mismo_organo=bool(f["mismo_organo"]),
        mismo_cpv4=bool(f["mismo_cpv4"]),
    )


def historial_propio(
    id_externo: str, *, organization_id: int, limite: int = 5
) -> HistorialPropio | None:
    """El historial de ``organization_id`` con el segmento del expediente; ``None`` si no existe.

    ``organization_id`` llega ya resuelto por la ruta (``require_organization``).
    """
    objetivo = repo.objetivo(id_externo)
    if objetivo is None:
        return None
    cpv4 = _cpv4(objetivo.get("cpv"))
    organo_id = objetivo.get("organo_id")
    organo = objetivo.get("organo_contratacion")
    identidad = identidad_fiscal(organization_id)
    base = HistorialPropio(
        licitacion_id=id_externo,
        identidad_conocida=identidad.conocida,
        organo=str(organo) if organo else None,
        cpv4=cpv4,
    )
    segmento = Segmento(
        cpv4=cpv4 or "",
        organo_id=int(organo_id) if organo_id is not None else None,
        organo_norm=plegar_organo(organo),
    )
    if not identidad.conocida or not (cpv4 or segmento.tiene_organo):
        return base

    datos = repo.historial_propio(
        segmento,
        organization_id=organization_id,
        empresa_ids=sorted(identidad.empresa_ids),
        nifs=sorted(identidad.nifs),
        excluir=id_externo,
        limite=limite,
    )
    return base.model_copy(
        update={
            "con_organo": _resumen(datos["resumen"], "organo") if segmento.tiene_organo else None,
            "en_cpv4": _resumen(datos["resumen"], "cpv4") if cpv4 else None,
            "oportunidades": (
                _oportunidades(datos["oportunidades"]) if segmento.tiene_organo else None
            ),
            "recientes": [_adjudicacion(f) for f in datos["recientes"]],
        }
    )
