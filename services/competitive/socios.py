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
- La propia organización, cuando se sabe cuál es. Desde S2.1 se sabe: la
  identidad fiscal declarada (``organization_nifs``) se traduce a las claves de
  empresa del segmento en :func:`claves_de_la_organizacion`, y esas claves
  salen tanto de las sugerencias como de la lista de líderes —que es
  literalmente el «contra quién se va»—.
- Competidores marcados como excluidos.
- Nada cuando no hay datos suficientes: lista vacía **declarada**, no un top-5
  de empresas irrelevantes que llenen el hueco.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from observability.logging import get_logger
from services.analytics.competitors import cargar_adjudicaciones_resueltas
from services.organizations import resolve_organization
from services.partners import segment_winners, suggest_partners
from services.pursuit_awards import IdentidadFiscal, identidad_fiscal

log = get_logger(__name__)

__all__ = [
    "LiderSegmento",
    "SocioSugerido",
    "SugerenciaSocios",
    "claves_de_la_organizacion",
    "socios_del_segmento",
    "sugerir_socios",
]

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


class LiderSegmento(BaseModel):
    """Una empresa que domina el segmento, con su cuota."""

    model_config = ConfigDict(extra="forbid")

    empresa: str
    empresa_key: str
    n_contratos: int = Field(ge=0)
    importe_total: float = Field(ge=0)
    #: Sobre el importe adjudicado del segmento, 0-100.
    cuota_pct: float = Field(ge=0, le=100)


class SugerenciaSocios(BaseModel):
    """Respuesta del buscador de socios, con su universo declarado."""

    model_config = ConfigDict(extra="forbid")

    socios: list[SocioSugerido] = Field(default_factory=list)
    #: Quién manda en el segmento. No son socios —son con quién se compite— y
    #: por eso van en su propia lista: mezclarlos con las sugerencias haría
    #: parecer que el producto propone aliarse con el líder, que casi nunca es
    #: la jugada. Sirven para lo contrario: saber contra quién se va.
    lideres: list[LiderSegmento] = Field(default_factory=list)
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


#: Columnas de identidad que deja `_prepare_company_identity` sobre cada fila.
#: Son las que permiten decir «esta fila es la propia organización» sin volver
#: a normalizar nada: el NIF ya viene por `normalize_nif` y el `empresa_id` ya
#: viene resuelto contra el maestro.
_COLUMNAS_IDENTIDAD = ("empresa_key", "_nif_key", "_empresa_id_key")


def _sin_na(valor: Any) -> Any:
    """``None`` en lugar de los ausentes de pandas (``NA``/``NaN``/``NaT``)."""
    return None if valor is None or pd.isna(valor) else valor


def claves_de_la_organizacion(adjudicaciones: pd.DataFrame, identidad: IdentidadFiscal) -> set[str]:
    """Las ``empresa_key`` de este segmento que **son** la propia organización.

    Es la pieza que faltaba entre :class:`IdentidadFiscal` —que habla de NIFs y
    de ``empresa_id`` del maestro— y el resto de este módulo, que agrupa por la
    clave analítica que calcula ``_prepare_company_identity`` (union-find sobre
    maestro, NIF y nombre normalizado). Sin esta traducción no hay forma de
    excluirse: la organización sabe su NIF, pero la lista de competidores está
    indexada por otra clave.

    Se mira **fila a fila** y no sólo el NIF representativo del grupo: si una
    sola adjudicación del grupo lleva nuestro NIF, ese grupo somos nosotros —es
    justamente lo que hace la agrupación cuando junta una UTE, un grupo
    empresarial o una variante del nombre bajo la misma clave—.

    Devuelve el conjunto vacío cuando la organización no ha declarado NIFs: sin
    identidad no se excluye a nadie, que es preferible a excluir por parecido
    de nombre.
    """
    if not identidad.conocida or adjudicaciones.empty:
        return set()
    if any(columna not in adjudicaciones.columns for columna in _COLUMNAS_IDENTIDAD):
        # Un DataFrame sin resolver (`cargar_adjudicaciones_resueltas` es quien
        # añade estas columnas). No se adivina: se declara que no se excluyó.
        log.warning("socios_identidad_sin_columnas_resueltas")
        return set()

    propias: set[str] = set()
    for clave, nif, empresa_id in adjudicaciones[list(_COLUMNAS_IDENTIDAD)].itertuples(
        index=False, name=None
    ):
        texto = str(clave) if _sin_na(clave) is not None else ""
        if not texto or texto in propias:
            continue
        nif_limpio = _sin_na(nif)
        empresa_id_limpio = _sin_na(empresa_id)
        if identidad.reconoce(
            nifs=[str(nif_limpio) if nif_limpio is not None else None],
            empresa_ids=[int(empresa_id_limpio) if empresa_id_limpio is not None else None],
        ):
            propias.add(texto)
    return propias


def sugerir_socios(
    adjudicaciones: pd.DataFrame,
    *,
    cpv: str | None = None,
    ccaa: str | None = None,
    excluir: set[str] | None = None,
    identidad: IdentidadFiscal | None = None,
    limit: int = 10,
) -> SugerenciaSocios:
    """Empresas que complementan en este segmento, con su motivo.

    ``excluir`` son las claves de empresa que no se proponen: la propia
    organización y los competidores marcados. Se aplica **después** del
    ranking y no antes, para que excluir a la primera no promocione a una que
    no llegaba al mínimo — el corte por ``MIN_CONTRATOS`` se hace sobre el
    universo real, no sobre el que queda tras quitar a los conocidos.

    ``identidad`` es la identidad fiscal de la organización que mira (S2.1).
    Cuando se pasa, sus claves se suman a ``excluir`` y salen **también** de
    ``lideres``: esa lista es literalmente el «contra quién se va», y verse a
    uno mismo ahí es peor que un adorno — infla la concentración aparente del
    segmento y sugiere aliarse consigo mismo. Es un parámetro y no una lectura
    interna porque la organización activa la resuelve quien atiende la
    petición: este módulo no sabe quién pregunta, y adivinarlo con la
    organización personal del proceso sería excluir a la casa equivocada.
    """
    if adjudicaciones.empty:
        return SugerenciaSocios(
            cpv=cpv, ccaa=ccaa, sin_resultados="No hay adjudicaciones en este segmento."
        )

    ranking = suggest_partners(
        adjudicaciones,
        cpv_prefijo=cpv or None,
        ccaa=ccaa,
    )
    if ranking.empty:
        return SugerenciaSocios(
            n_adjudicaciones=len(adjudicaciones),
            cpv=cpv,
            ccaa=ccaa,
            sin_resultados="Ninguna empresa acumula adjudicaciones en este segmento.",
        )

    fuera = set(excluir or set())
    if identidad is not None:
        fuera |= claves_de_la_organizacion(adjudicaciones, identidad)
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

    return SugerenciaSocios(
        socios=socios,
        lideres=_lideres(adjudicaciones, excluir=fuera),
        n_adjudicaciones=len(adjudicaciones),
        cpv=cpv,
        ccaa=ccaa,
    )


def _lideres(
    adjudicaciones: pd.DataFrame, *, excluir: set[str] | None = None, top: int = 5
) -> list[LiderSegmento]:
    """Los que más adjudican en el segmento, con su cuota.

    Es el otro consumidor que le faltaba a `services/partners.py`. Va aparte de
    las sugerencias a propósito: el líder de un CPV rara vez busca socios, y
    proponerlo como uno sería una sugerencia que nadie puede accionar. Sirve
    para la pregunta contraria — contra quién se va.

    ``excluir`` quita a la propia organización de esa lista sin recalcular las
    cuotas: la cuota de mercado es del mercado entero —nosotros incluidos— y
    repartirla sólo entre los rivales convertiría un dato medido en uno
    inventado. Se descarta la fila, no el denominador.
    """
    try:
        ranking = segment_winners(adjudicaciones, top_n=top)
    except Exception:
        # Los líderes son información añadida: sin ellos la respuesta sigue
        # sirviendo. La traza distingue «no hay» de «no se pudo».
        log.warning("socios_lideres_error", exc_info=True)
        return []
    if ranking.empty:
        return []

    fuera = excluir or set()
    lideres: list[LiderSegmento] = []
    for bruta in ranking.head(top).to_dict("records"):
        fila: dict[str, Any] = {str(k): v for k, v in bruta.items()}
        clave = str(fila.get("empresa_key") or "")
        if not clave or clave in fuera:
            continue
        lideres.append(
            LiderSegmento(
                empresa=str(fila.get("empresa") or clave),
                empresa_key=clave,
                n_contratos=int(fila.get("n_contratos") or 0),
                importe_total=float(fila.get("importe_total") or 0.0),
                # Acotado: con un `importe_adjudicado` negativo por un dato
                # malo, la cuota podría salirse del rango que el DTO admite y
                # tumbar toda la respuesta por una fila corrupta.
                cuota_pct=max(0.0, min(100.0, float(fila.get("cuota_pct") or 0.0))),
            )
        )
    return lideres


def socios_del_segmento(
    *,
    cpv: str | None = None,
    ccaa: str | None = None,
    limit: int = 10,
    user_id: int | None = None,
    organization_id: int | None = None,
) -> SugerenciaSocios:
    """Punto de entrada del endpoint: carga el segmento y lo rankea.

    La carga vive aquí y no en la ruta para que nadie vuelva a alimentar
    `sugerir_socios` con filas sin resolver la identidad de empresa.

    ``user_id`` es quien pregunta y ``organization_id`` el ámbito explícito, si
    lo pidió. La resolución (`resolve_organization`) se hace aquí y no en la
    ruta por el mismo motivo que en `batallas_de_usuario`: `api/` no importa
    `resolve_organization` —lo audita `test_organization_sql_isolation`— y cada
    ruta que lo hiciera sería otro sitio donde equivocarse de ámbito.

    Sin ``user_id`` no hay organización que excluir y la lista sale como antes
    de S2.1, con todo el segmento dentro. Es un degradado consciente y no un
    error: un usuario anónimo o un job sin contexto no tiene identidad fiscal,
    y excluir a una organización arbitraria sería peor que no excluir a nadie.
    """
    return sugerir_socios(
        cargar_adjudicaciones_resueltas(ccaa=ccaa),
        cpv=cpv,
        ccaa=ccaa,
        identidad=_identidad_de(user_id, organization_id),
        limit=limit,
    )


def _identidad_de(user_id: int | None, organization_id: int | None) -> IdentidadFiscal | None:
    """La identidad fiscal de quien pregunta, o ``None`` si no se puede saber.

    Un fallo de lectura no tumba la pantalla: la lista de socios sigue siendo
    útil aunque no sepamos excluirnos, y quedarse sin ella porque falló
    ``organization_nifs`` sería cambiar un defecto por una caída. Sí deja traza
    — una exclusión que se salta en silencio es la clase de fallo que nadie ve
    hasta que un comercial se encuentra a su propia empresa entre los líderes
    del segmento.

    El permiso es la excepción a esa tolerancia: si alguien pide el ámbito de
    una organización que no es suya, eso es un 403 y se propaga. Tragárselo
    convertiría un error de autorización en una respuesta silenciosamente
    distinta de la que el usuario pidió.
    """
    if user_id is None:
        return None
    resuelta, _rol = resolve_organization(user_id, organization_id)
    try:
        return identidad_fiscal(resuelta)
    except Exception as exc:
        log.warning("socios_identidad_fiscal_error", error=str(exc)[:200])
        return None
