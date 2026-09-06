"""F3.3 — con quién ir a una UTE, y por qué.

``services/partners.py`` lleva meses con tres funciones sin un solo consumidor
(``suggest_partners``, ``segment_winners``, ``company_profile``): sólo
``build_partnership_graph`` se usa, desde el grafo de UTEs. Este módulo es el
consumidor que faltaba, y añade lo que aquellas no dan y el usuario necesita:
**por qué** se propone cada empresa.

Una lista de empresas ordenada por facturación no es una sugerencia de socio,
es un ranking. Lo que convierte una en la otra es el motivo —«coincide contigo
en 4 órganos», «hace UTE el 60 % de las veces», «es PYME»—, porque el usuario
va a llamar a una de ellas y necesita saber qué decirle.

Lo que este módulo **no** propone
---------------------------------
- La propia organización, cuando se sabe cuál es.
- Competidores marcados como excluidos.
- Nada cuando no hay datos suficientes: lista vacía **declarada**, no un top-5
  de empresas irrelevantes que llenen el hueco.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from observability.logging import get_logger
from services.partners import suggest_partners

log = get_logger(__name__)

__all__ = ["SocioSugerido", "SugerenciaSocios", "sugerir_socios"]

#: Contratos mínimos para proponer a una empresa como socio. Con menos, la
#: «especialización» que se le atribuye es una casualidad de dos contratos.
MIN_CONTRATOS = 3

#: Por encima de este porcentaje de UTEs, la empresa se considera acostumbrada
#: a asociarse — que es información distinta de su tamaño y a menudo más útil:
#: la más grande del CPV puede no coger el teléfono.
UMBRAL_PCT_UTE = 30.0


class SocioSugerido(BaseModel):
    """Una empresa propuesta, con el motivo por el que se propone."""

    model_config = ConfigDict(extra="forbid")

    empresa: str
    empresa_key: str
    n_contratos: int = Field(ge=0)
    importe_total: float = Field(ge=0)
    n_organos: int = Field(ge=0)
    pct_ute: float = Field(ge=0, le=100)
    es_pyme: bool = False
    #: Una o más razones, en lenguaje llano. **Nunca vacío**: una sugerencia
    #: sin motivo no se publica, porque entonces es sólo un nombre en una lista.
    motivos: list[str] = Field(min_length=1)


class SugerenciaSocios(BaseModel):
    """Respuesta del buscador de socios, con su universo declarado."""

    model_config = ConfigDict(extra="forbid")

    socios: list[SocioSugerido] = Field(default_factory=list)
    #: Adjudicaciones sobre las que se calculó. Es el `n` que ADR-014 exige.
    n_adjudicaciones: int = Field(default=0, ge=0)
    cpv: str | None = None
    ccaa: str | None = None
    #: Por qué la lista está vacía, cuando lo está.
    sin_resultados: str | None = None


def _motivos(fila: dict[str, Any]) -> list[str]:
    """Por qué esta empresa. Cada motivo cita el dato que lo sostiene."""
    razones: list[str] = []
    n_organos = int(fila.get("n_organos") or 0)
    pct_ute = float(fila.get("pct_ute") or 0.0)
    n_contratos = int(fila.get("n_contratos") or 0)

    if n_organos >= 3:
        razones.append(f"Adjudicataria en {n_organos} órganos distintos de este segmento.")
    if pct_ute >= UMBRAL_PCT_UTE:
        razones.append(f"Se presenta en UTE el {round(pct_ute)} % de las veces.")
    if fila.get("es_pyme"):
        razones.append("Es PYME: puede sumar en los criterios que lo puntúan.")
    if not razones:
        # Nunca vacío: si nada más la distingue, el motivo es el volumen, que
        # es un hecho medido y no un adjetivo.
        razones.append(f"Tiene {n_contratos} adjudicaciones en este segmento.")
    return razones


def sugerir_socios(
    adjudicaciones: pd.DataFrame,
    *,
    cpv: str | None = None,
    ccaa: str | None = None,
    excluir: set[str] | None = None,
    limit: int = 10,
) -> SugerenciaSocios:
    """Empresas que complementan en este segmento, con su motivo.

    ``excluir`` son las claves de empresa que no se proponen: la propia
    organización y los competidores marcados. Se aplica **después** del
    ranking y no antes, para que excluir a la primera no promocione a una que
    no llegaba al mínimo — el corte por ``MIN_CONTRATOS`` se hace sobre el
    universo real, no sobre el que queda tras quitar a los conocidos.
    """
    if adjudicaciones.empty:
        return SugerenciaSocios(
            cpv=cpv, ccaa=ccaa, sin_resultados="No hay adjudicaciones en este segmento."
        )

    ranking = suggest_partners(
        adjudicaciones,
        keywords=[cpv] if cpv else None,
        ccaa=ccaa,
    )
    if ranking.empty:
        return SugerenciaSocios(
            n_adjudicaciones=len(adjudicaciones),
            cpv=cpv,
            ccaa=ccaa,
            sin_resultados="Ninguna empresa acumula adjudicaciones en este segmento.",
        )

    fuera = excluir or set()
    socios: list[SocioSugerido] = []
    # `to_dict("records")` tipa las claves como `Hashable`; aquí son los
    # nombres de columna que fija `suggest_partners`, todos `str`.
    for bruta in ranking.to_dict("records"):
        fila: dict[str, Any] = {str(k): v for k, v in bruta.items()}
        if int(fila.get("n_contratos") or 0) < MIN_CONTRATOS:
            continue
        clave = str(fila.get("empresa_key") or "")
        if not clave or clave in fuera:
            continue
        socios.append(
            SocioSugerido(
                empresa=str(fila.get("empresa") or clave),
                empresa_key=clave,
                n_contratos=int(fila.get("n_contratos") or 0),
                importe_total=float(fila.get("importe_total") or 0.0),
                n_organos=int(fila.get("n_organos") or 0),
                pct_ute=float(fila.get("pct_ute") or 0.0),
                es_pyme=bool(fila.get("es_pyme")),
                motivos=_motivos(fila),
            )
        )
        if len(socios) >= limit:
            break

    if not socios:
        return SugerenciaSocios(
            n_adjudicaciones=len(adjudicaciones),
            cpv=cpv,
            ccaa=ccaa,
            sin_resultados=(
                f"Ninguna empresa llega a {MIN_CONTRATOS} adjudicaciones en este segmento."
            ),
        )

    return SugerenciaSocios(socios=socios, n_adjudicaciones=len(adjudicaciones), cpv=cpv, ccaa=ccaa)
