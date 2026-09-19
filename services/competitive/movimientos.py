"""Movimientos de las empresas vigiladas — señales proactivas (RFC ux-competidores #4).

El dossier de una empresa ya calcula «movimientos» bajo demanda, pero sólo
cuando el usuario abre esa empresa. Esto invierte el sentido: parte de la
watchlist de empresas y dice qué ha pasado con TODAS ellas en la ventana, sin
que haya que ir a buscarlo.

Las señales son explicables y salen de adjudicaciones reales, nunca de un
modelo:

- ``nueva_ccaa``: gana en una CCAA donde no tenía ninguna adjudicación antes de
  la ventana (expansión territorial).
- ``nuevo_cpv``: gana en una familia CPV (2 dígitos) nueva para ella
  (diversificación hacia otro nicho).
- ``racha``: acumula :data:`UMBRAL_RACHA` o más adjudicaciones en la ventana.

El SQL vive en ``db/watchlist_empresas.py``; aquí sólo se clasifica lo que ya
viene agregado. Es una función pura, testeable sin base de datos.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

#: Adjudicaciones en la ventana a partir de las cuales se señala una racha.
UMBRAL_RACHA = 3

#: Techo de señales en la respuesta. Las de racha van primero (una por empresa).
MAX_SENALES = 50

TipoSenal = Literal["nueva_ccaa", "nuevo_cpv", "racha"]


class EmpresaVigiladaActividad(BaseModel):
    """Actividad de una empresa vigilada en la ventana (0 si no se ha movido)."""

    empresa_id: int
    nombre: str
    adjudicaciones: int = 0
    importe: float = 0.0


class SenalCompetitiva(BaseModel):
    """Una señal explicable sobre una empresa vigilada."""

    tipo: TipoSenal
    empresa_id: int
    empresa: str
    titulo: str = Field(description="Frase corta, lista para pintar.")
    detalle: str
    licitacion_id: str | None = None
    fecha: str | None = Field(default=None, description="Fecha de adjudicación, YYYY-MM-DD.")
    importe: float | None = None


class MovimientosVigiladasResult(BaseModel):
    """Señales y actividad de las empresas vigiladas en los últimos ``dias``."""

    dias: int
    desde: str
    empresas: list[EmpresaVigiladaActividad] = Field(default_factory=list)
    senales: list[SenalCompetitiva] = Field(default_factory=list)
    senales_truncadas: bool = Field(
        default=False,
        description=f"True si había más de {MAX_SENALES} señales y se recortaron.",
    )


def _fecha(valor: Any) -> str | None:
    return str(valor)[:10] if valor else None


def construir_movimientos(
    datos: dict[str, list[dict[str, Any]]], *, dias: int, desde: str
) -> MovimientosVigiladasResult:
    """Clasifica las filas de :func:`db.watchlist_empresas.movimientos_vigiladas`."""
    empresas = [
        EmpresaVigiladaActividad(
            empresa_id=int(fila["empresa_id"]),
            nombre=str(fila.get("nombre") or f"Empresa {fila['empresa_id']}"),
            adjudicaciones=int(fila.get("adjudicaciones") or 0),
            importe=float(fila.get("importe") or 0),
        )
        for fila in datos.get("resumen", [])
    ]

    senales: list[SenalCompetitiva] = [
        SenalCompetitiva(
            tipo="racha",
            empresa_id=emp.empresa_id,
            empresa=emp.nombre,
            titulo=f"{emp.nombre}: {emp.adjudicaciones} adjudicaciones",
            detalle=f"{emp.adjudicaciones} adjudicaciones en los últimos {dias} días.",
            importe=emp.importe,
        )
        for emp in empresas
        if emp.adjudicaciones >= UMBRAL_RACHA
    ]

    # Una señal por (empresa, CCAA) y por (empresa, familia CPV): si gana tres
    # contratos en la misma CCAA nueva, la novedad es una, no tres.
    vistas: set[tuple[str, int, str]] = set()
    for fila in datos.get("adjudicaciones", []):
        empresa_id = int(fila["empresa_id"])
        nombre = str(fila.get("nombre") or f"Empresa {empresa_id}")
        # `Any`: los valores ya van tipados y validados por el modelo al construirlo.
        comun: dict[str, Any] = {
            "empresa_id": empresa_id,
            "empresa": nombre,
            "licitacion_id": str(fila["licitacion_id"]) if fila.get("licitacion_id") else None,
            "fecha": _fecha(fila.get("fecha_adjudicacion")),
            "importe": (
                float(fila["importe_adjudicado"])
                if fila.get("importe_adjudicado") is not None
                else None
            ),
        }
        ccaa = fila.get("ccaa")
        if fila.get("ccaa_nueva") and ccaa and ("ccaa", empresa_id, str(ccaa)) not in vistas:
            vistas.add(("ccaa", empresa_id, str(ccaa)))
            senales.append(
                SenalCompetitiva(
                    tipo="nueva_ccaa",
                    titulo=f"{nombre} entra en {ccaa}",
                    detalle=(
                        f"Primera adjudicación en {ccaa}: "
                        f"{fila.get('titulo') or fila.get('licitacion_id')}."
                    ),
                    **comun,
                )
            )
        cpv = str(fila.get("cpv") or "")
        familia = cpv[:2]
        if fila.get("cpv_nuevo") and familia and ("cpv", empresa_id, familia) not in vistas:
            vistas.add(("cpv", empresa_id, familia))
            senales.append(
                SenalCompetitiva(
                    tipo="nuevo_cpv",
                    titulo=f"{nombre} gana en la familia CPV {familia}",
                    detalle=(
                        f"Primera adjudicación en CPV {familia}xxxxxx: "
                        f"{fila.get('titulo') or fila.get('licitacion_id')}."
                    ),
                    **comun,
                )
            )

    return MovimientosVigiladasResult(
        dias=dias,
        desde=desde,
        empresas=empresas,
        senales=senales[:MAX_SENALES],
        senales_truncadas=len(senales) > MAX_SENALES,
    )
