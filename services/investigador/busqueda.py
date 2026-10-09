"""Búsqueda por texto del Investigador: anuncios y pliegos, con la frase entendida.

Lo comparten ``POST /search/semantic`` (la lista de resultados) y el modo
general de ``POST /ask`` (el contexto del asistente): la respuesta se apoya en
los mismos expedientes que la lista enseña, no en una recuperación aparte que
podía contradecirla.

El orden de los resultados tiene tres escalones, y cada resultado dice en cuál
está:

1. **El anuncio casa con todos los términos** (título, descripción o CPV).
2. **Un pasaje del pliego contiene todos los términos**, aunque el anuncio no:
   «baja temeraria» no está en el título de casi ningún expediente y sí en el
   pliego de cláusulas de muchos.
3. **El anuncio casa con parte de los términos**; el resultado dice cuáles
   faltan.

Dentro de cada escalón manda el orden de ``db.repositories.investigador``.
Si nada casa, queda un último recurso por subcadena (``like``).

``preparar`` es pura; ``buscar_por_texto`` es la que consulta.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from db.repositories import investigador as repo
from db.repositories.investigador import MARCA_FIN, MARCA_INICIO, Ambito
from observability.logging import get_logger
from services.investigador.consulta import ConsultaInterpretada, interpretar

log = get_logger(__name__)

# Caminos posibles, de más a menos informado. Son las claves que etiqueta el
# Investigador (``web/.../investigador/_lib/source-label.ts``);
# ``tests/test_search_semantic_source.py`` comprueba que no se separen.
FUENTE_FUSION = "rrf"
FUENTE_TEXTO = "fts"
FUENTE_LITERAL = "like"
FUENTE_FILTROS = "filtros"
FUENTES: tuple[str, ...] = (FUENTE_FUSION, FUENTE_TEXTO, FUENTE_LITERAL, FUENTE_FILTROS)

EN_ANUNCIO = "anuncio"
EN_PLIEGO = "pliego"

#: Columnas de un expediente que viajan en cada resultado.
_CAMPOS = (
    "id_externo",
    "titulo",
    "organo_contratacion",
    "importe",
    "descripcion",
    "url",
    "fecha_publicacion",
    "fecha_limite",
    "ccaa",
    "estado",
    "tecnologia",
)

_ESPACIOS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class Resultado:
    """Lo que devolvió una búsqueda y por qué camino."""

    hits: list[dict[str, Any]]
    #: Camino REALMENTE ejecutado: uno de :data:`FUENTES`.
    fuente: str


def preparar(
    q: str,
    *,
    ccaa: Sequence[str] = (),
    tecnologia: Sequence[str] = (),
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    interpretar_filtros: bool = True,
    hoy: date | None = None,
) -> tuple[ConsultaInterpretada, Ambito]:
    """La consulta entendida y el ámbito con el que se va a buscar.

    Los filtros que llegan explícitos —los de la barra de ámbito— mandan sobre
    los que salen de la frase, dimensión a dimensión: con «Madrid» marcado en la
    barra, un «en Andalucía» escrito no ensancha ni cambia el ámbito. La
    consulta que se devuelve trae solo lo que **sí** se aplicó desde la frase,
    que es lo que la pantalla enseña como «entendido».
    """
    consulta = interpretar(q, hoy=hoy, filtros=interpretar_filtros)
    regiones = tuple(c.strip() for c in ccaa if c and c.strip())
    tecnologias = tuple(t.strip() for t in tecnologia if t and t.strip())
    con_fechas = bool(fecha_desde or fecha_hasta)
    if regiones:
        consulta = dataclasses.replace(consulta, ccaa=())
    if con_fechas:
        consulta = dataclasses.replace(consulta, fecha_desde=None, fecha_hasta=None)
    ambito = Ambito(
        ccaa=regiones,
        ccaa_del_texto=consulta.ccaa,
        tecnologia=tecnologias,
        fecha_desde=fecha_desde if con_fechas else consulta.fecha_desde,
        fecha_hasta=fecha_hasta if con_fechas else consulta.fecha_hasta,
        importe_min=consulta.importe_min,
        importe_max=consulta.importe_max,
        solo_abiertas=consulta.solo_abiertas,
    )
    return consulta, ambito


def filtros_de_fusion(ambito: Ambito) -> dict[str, Any]:
    """El ámbito en la forma de ``hybrid_search_docs``, solo lo que acota.

    La fusión no distingue las comunidades de la barra de las de la frase: las
    recibe juntas, como igualdad.
    """
    filtros: dict[str, Any] = {}
    if regiones := [*ambito.ccaa, *ambito.ccaa_del_texto]:
        filtros["ccaa"] = regiones
    if ambito.tecnologia:
        filtros["tecnologia"] = list(ambito.tecnologia)
    if ambito.fecha_desde:
        filtros["fecha_desde"] = ambito.fecha_desde
    if ambito.fecha_hasta:
        filtros["fecha_hasta"] = ambito.fecha_hasta
    if ambito.importe_min is not None:
        filtros["importe_min"] = ambito.importe_min
    if ambito.importe_max is not None:
        filtros["importe_max"] = ambito.importe_max
    if ambito.solo_abiertas:
        filtros["solo_abiertas"] = True
    return filtros


def tramos(marcado: str | None) -> list[dict[str, Any]]:
    """Texto con marcas de ``ts_headline`` → ``[{texto, resaltado}]``.

    Las marcas no salen de aquí: el contrato lleva tramos tipados y quien pinta
    decide cómo se ve un resaltado. Los saltos de línea de un PDF se colapsan
    en espacios, que es como se lee un extracto de una línea.
    """
    if not marcado:
        return []
    plano = _ESPACIOS_RE.sub(" ", marcado).strip()
    partes = plano.split(MARCA_INICIO)
    salida: list[dict[str, Any]] = []
    if partes[0]:
        salida.append({"texto": partes[0], "resaltado": False})
    for parte in partes[1:]:
        dentro, _, fuera = parte.partition(MARCA_FIN)
        if dentro:
            salida.append({"texto": dentro, "resaltado": True})
        if fuera:
            salida.append({"texto": fuera, "resaltado": False})
    return salida


def _con_resaltado(lista: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Los tramos, o nada si ninguno resalta: un extracto sin coincidencia es
    el arranque del texto, y eso no explica por qué salió el resultado."""
    return lista if any(t["resaltado"] for t in lista) else []


def _base(fila: dict[str, Any]) -> dict[str, Any]:
    return {campo: fila.get(campo) for campo in _CAMPOS}


def _pasaje(fragmento: dict[str, Any]) -> dict[str, Any]:
    return {
        "documento_id": fragmento.get("documento_id"),
        "tipo": fragmento.get("tipo"),
        "filename": fragmento.get("filename"),
        "page_number": fragmento.get("page_number"),
        "tramos": tramos(fragmento.get("extracto")),
    }


def _chunk(fragmento: dict[str, Any]) -> dict[str, Any]:
    """El fragmento en la forma que cita ``/ask`` (``llm.prompts._doc_block``)."""
    return {
        "documento_id": fragmento.get("documento_id"),
        "chunk_index": fragmento.get("chunk_index"),
        "page_number": fragmento.get("page_number"),
        "tipo": fragmento.get("tipo"),
        "filename": fragmento.get("filename"),
        "texto": fragmento.get("texto") or "",
    }


def _pasajes_seguro(
    consulta: ConsultaInterpretada, ambito: Ambito, limit: int
) -> list[tuple[str, int]]:
    """Expedientes con pasaje, o ``[]`` si la consulta falla.

    Los pliegos suman, no sostienen: una instalación sin ``documento_chunks``
    (anterior a v56) o un fallo de esa consulta no puede tumbar la búsqueda en
    los anuncios, que es la que casi siempre responde.
    """
    try:
        return repo.licitaciones_con_pasaje(
            consulta.texto, ambito, expresion=consulta.con_operadores, limit=limit
        )
    except Exception:
        log.warning("investigador.pasajes_failed", exc_info=True)
        return []


def _mejores_seguro(ids: list[str], consulta: ConsultaInterpretada) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    try:
        return repo.mejores_pasajes(ids, consulta.texto, expresion=consulta.con_operadores)
    except Exception:
        log.warning("investigador.mejores_pasajes_failed", exc_info=True)
        return {}


def _proporcion(fila: dict[str, Any]) -> float:
    """Parte de los términos que casan en el anuncio, en ``[0, 1]``."""
    total = int(fila.get("n_terminos") or 0)
    if total <= 0:
        return 1.0
    return round(min(1.0, int(fila.get("cobertura") or 0) / total), 6)


def _por_texto(
    consulta: ConsultaInterpretada, ambito: Ambito, top_k: int, *, con_pliegos: bool
) -> list[dict[str, Any]]:
    recientes = consulta.orden == "recientes"
    if consulta.con_operadores:
        anuncios = repo.anuncios_por_expresion(
            consulta.texto, ambito, limit=top_k, recientes=recientes
        )
    else:
        anuncios = repo.anuncios_por_terminos(
            consulta.terminos, ambito, limit=top_k, recientes=recientes
        )
    pasajes = _pasajes_seguro(consulta, ambito, top_k) if con_pliegos else []

    por_id = {str(a["id_externo"]): a for a in anuncios}
    con_pasaje = {id_ for id_, _ in pasajes}

    def _completo(fila: dict[str, Any]) -> bool:
        return consulta.con_operadores or fila.get("cobertura") == fila.get("n_terminos")

    orden: dict[str, None] = {}
    for a in anuncios:
        if _completo(a):
            orden.setdefault(str(a["id_externo"]), None)
    for id_, _ in pasajes:
        orden.setdefault(id_, None)
    for a in anuncios:
        orden.setdefault(str(a["id_externo"]), None)
    ids = list(orden)[:top_k]

    # Un expediente que solo llegó por su pliego no trae fila de anuncio.
    if faltan := [i for i in ids if i not in por_id]:
        por_id.update(repo.anuncios_por_id(faltan))
    mejores = _mejores_seguro([i for i in ids if i in con_pasaje], consulta)

    hits: list[dict[str, Any]] = []
    for id_ in ids:
        fila = por_id.get(id_)
        if fila is None:
            # El índice de pliegos apunta a un expediente que ya no existe: no
            # se inventa un resultado sin datos.
            continue
        en_anuncio = "cobertura" in fila or (consulta.con_operadores and "rank" in fila)
        en_pliego = id_ in con_pasaje
        hit = _base(fila)
        hit["coincide_en"] = [
            lugar for lugar, si in ((EN_ANUNCIO, en_anuncio), (EN_PLIEGO, en_pliego)) if si
        ]
        hit["terminos_ausentes"] = [] if en_pliego else list(fila.get("ausentes") or [])
        hit["titulo_tramos"] = tramos(fila.get("titulo_marcado"))
        hit["extracto"] = _con_resaltado(tramos(fila.get("extracto")))
        hit["score"] = 1.0 if en_pliego else _proporcion(fila)
        fragmento = mejores.get(id_)
        hit["pasaje"] = _pasaje(fragmento) if fragmento else None
        hit["chunks"] = [_chunk(fragmento)] if fragmento else []
        hits.append(hit)
    return hits


def _simples(filas: list[dict[str, Any]], *, con_proporcion: bool) -> list[dict[str, Any]]:
    """Resultados sin marcas ni pasaje: el último recurso y el de solo filtros."""
    hits: list[dict[str, Any]] = []
    for fila in filas:
        hit = _base(fila)
        hit["coincide_en"] = [EN_ANUNCIO] if con_proporcion else []
        hit["terminos_ausentes"] = []
        hit["titulo_tramos"] = []
        hit["extracto"] = []
        hit["score"] = _proporcion(fila) if con_proporcion else 0.0
        hit["pasaje"] = None
        hit["chunks"] = []
        hits.append(hit)
    return hits


def buscar_por_texto(
    consulta: ConsultaInterpretada,
    ambito: Ambito,
    top_k: int,
    *,
    con_pliegos: bool = True,
) -> Resultado:
    """Busca ``consulta`` dentro de ``ambito`` y dice por qué camino respondió.

    Sin texto que buscar —la frase eran solo filtros, o «las más recientes»—
    devuelve lo más reciente del ámbito (``filtros``). Sin texto **ni** ámbito
    no hay nada que preguntar a la base, y la lista sale vacía en vez de
    devolver el corpus entero ordenado por fecha a quien escribió «de la».
    """
    if not consulta.tiene_texto:
        if ambito.vacio and consulta.orden != "recientes":
            return Resultado([], FUENTE_TEXTO)
        filas = repo.anuncios_del_ambito(ambito, limit=top_k)
        return Resultado(_simples(filas, con_proporcion=False), FUENTE_FILTROS)

    hits = _por_texto(consulta, ambito, top_k, con_pliegos=con_pliegos)
    if hits or consulta.con_operadores:
        return Resultado(hits, FUENTE_TEXTO)

    literales = repo.anuncios_literales(consulta.terminos, ambito, limit=top_k)
    return Resultado(_simples(literales, con_proporcion=True), FUENTE_LITERAL)


def documentos_de_contexto(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Los resultados en la forma que ``/ask`` manda al modelo.

    Las columnas del expediente y, si un pasaje del pliego casó, ese fragmento
    entero en ``chunks``: es lo que el asistente puede citar. Los campos de
    presentación (tramos, escalón) no viajan al modelo.
    """
    docs: list[dict[str, Any]] = []
    for hit in hits:
        doc = _base(hit)
        if hit.get("chunks"):
            doc["chunks"] = hit["chunks"]
        docs.append(doc)
    return docs
