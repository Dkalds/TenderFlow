"""Predecesor y expedientes similares (C1.3).

``services/embeddings.py`` sabía buscar textos parecidos desde siempre y
**ninguna ruta de la API ni pantalla del frontend lo exponía**. El único uso del
concepto de incumbente estaba dentro del modelo de retención.

Lo que este módulo añade son dos preguntas distintas, y la diferencia importa
porque una de las dos es una afirmación fuerte:

**Predecesor** — «este contrato ya se licitó antes, y lo ganó X». Exige mismo
órgano, mismo CPV4 y anterioridad. Es la que da la información accionable: quién
es el incumbente, por cuánto se adjudicó y con qué baja. Y es la que no se puede
equivocar: decirle a alguien que el incumbente es X cuando no lo es le hace
preparar la oferta contra un competidor imaginario.

**Similares** — «qué más se compra parecido a esto». Cualquier órgano, mismo
CPV4, ordenado por parecido del texto. Aquí un falso positivo cuesta una fila de
más en una lista, así que el listón es más bajo.

Método y alcance declarados
---------------------------
El resultado dice siempre **cómo** se calculó (`metodo`) y **sobre cuántos**
candidatos (`n`). Sin embeddings instalados el orden cae a coincidencia de
términos, que es peor y hay que decirlo: una lista ordenada por un criterio que
el consumidor no conoce no se puede interpretar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from db.repositories import similares as repo
from observability.logging import get_logger
from services.embeddings import embeddings_available, semantic_match

log = get_logger(__name__)

#: Cómo se ordenaron los candidatos.
Metodo = Literal["embedding", "fts"]

#: Solapamiento mínimo de términos para que dos objetos de contrato se
#: consideren el mismo trabajo, cuando no hay embeddings.
#:
#: 0,35 y no más: los objetos de contrato repiten mucha palabra administrativa
#: («servicio», «suministro», «mantenimiento») y un listón alto dejaría fuera
#: renovaciones reales cuyo título cambió de redacción entre convocatorias.
UMBRAL_SOLAPE_FTS = 0.35

#: Similitud mínima del embedding para proponer un **predecesor**.
#:
#: Más alto que el de similares porque la afirmación es más fuerte: proponer un
#: incumbente equivocado hace que alguien prepare su oferta contra un competidor
#: que no existe.
UMBRAL_PREDECESOR = 0.72

_PALABRA = re.compile(r"[a-záéíóúñü0-9]{4,}", re.IGNORECASE)

#: Palabras que aparecen en casi todo objeto de contrato público y por tanto no
#: distinguen nada. Sin quitarlas, «servicio de mantenimiento» se parece a
#: cualquier cosa.
_VACIAS = frozenset(
    {
        "servicio",
        "servicios",
        "suministro",
        "suministros",
        "contrato",
        "contratacion",
        "contratación",
        "mantenimiento",
        "adquisicion",
        "adquisición",
        "prestacion",
        "prestación",
        "mediante",
        "para",
        "expediente",
        "lote",
        "lotes",
    }
)


@dataclass(frozen=True, slots=True)
class Candidato:
    """Un expediente propuesto como predecesor o similar."""

    id_externo: str
    titulo: str
    organo_contratacion: str | None
    cpv: str | None
    importe: float | None
    estado: str | None
    fecha_publicacion: str | None
    score: float
    #: Solo en el predecesor: quién lo ganó y por cuánto.
    adjudicatario: str | None = None
    importe_adjudicado: float | None = None
    fecha_adjudicacion: str | None = None
    baja_pct: float | None = None


@dataclass(frozen=True, slots=True)
class Similares:
    """Respuesta de `/licitaciones/{id}/similares`."""

    licitacion_id: str
    #: `None` cuando no hay ninguno que cumpla las tres condiciones. **No se
    #: rellena con «el más parecido»**: un predecesor dudoso es peor que ninguno.
    predecesor: Candidato | None
    similares: list[Candidato] = field(default_factory=list)
    metodo: Metodo = "fts"
    #: Candidatos evaluados. Sin este número, un `similares: []` no distingue
    #: «no hay nada parecido» de «no había contra qué comparar».
    n: int = 0


def _terminos(texto: str | None) -> set[str]:
    if not texto:
        return set()
    return {p.lower() for p in _PALABRA.findall(texto)} - _VACIAS


def _solape(a: str | None, b: str | None) -> float:
    ta, tb = _terminos(a), _terminos(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _cpv4(cpv: str | None) -> str | None:
    if not cpv:
        return None
    digitos = cpv.strip()[:4]
    return digitos if len(digitos) == 4 and digitos.isdigit() else None


def _baja(importe: float | None, adjudicado: float | None) -> float | None:
    """Baja del predecesor, o `None` si no se puede calcular con honestidad.

    Usa `importe_base_sin_iva` cuando la fila la trae (C1.1): mezclar bases haría
    que una baja del 21 % pudiera ser exactamente el IVA — el defecto que
    ADR-032 corrigió y que no tiene sentido reintroducir aquí.
    """
    if not importe or not adjudicado or importe <= 0:
        return None
    return round((importe - adjudicado) / importe * 100, 2)


def _ordenar(
    objetivo_texto: str, filas: list[dict[str, Any]]
) -> tuple[list[tuple[dict[str, Any], float]], Metodo]:
    """Ordena candidatos por parecido con el objetivo. Declara el método.

    Con embeddings instalados usa similitud semántica; sin ellos, solapamiento
    de términos. El segundo es peor y por eso el método viaja en la respuesta.
    """
    if not filas:
        return [], "embedding" if embeddings_available() else "fts"

    if embeddings_available():
        corpus = [str(f.get("titulo") or "") for f in filas]
        try:
            emparejados = semantic_match(objetivo_texto, corpus, threshold=0.0)
            puntuados = [(filas[i], score) for i, score in emparejados]
            return puntuados, "embedding"
        except Exception:
            # El fallback no es cosmético: sin él, un fallo del modelo dejaría
            # la ficha sin similares en vez de con similares peores.
            log.warning("similares_embedding_fallo", exc_info=True)

    puntuados = [(f, _solape(objetivo_texto, f.get("titulo"))) for f in filas]
    puntuados.sort(key=lambda par: par[1], reverse=True)
    return puntuados, "fts"


def _a_candidato(fila: dict[str, Any], score: float, *, con_adjudicacion: bool) -> Candidato:
    importe = fila.get("importe_base_sin_iva") or fila.get("importe")
    adjudicado = fila.get("importe_adjudicado") if con_adjudicacion else None
    return Candidato(
        id_externo=str(fila["id_externo"]),
        titulo=str(fila.get("titulo") or ""),
        organo_contratacion=fila.get("organo_contratacion"),
        cpv=fila.get("cpv"),
        importe=importe,
        estado=fila.get("estado"),
        fecha_publicacion=fila.get("fecha_publicacion"),
        score=round(float(score), 4),
        adjudicatario=fila.get("adjudicatario") if con_adjudicacion else None,
        importe_adjudicado=adjudicado,
        fecha_adjudicacion=fila.get("fecha_adjudicacion") if con_adjudicacion else None,
        baja_pct=_baja(importe, adjudicado) if con_adjudicacion else None,
    )


def buscar(id_externo: str, *, max_similares: int = 10) -> Similares | None:
    """Predecesor y hasta *max_similares* expedientes parecidos.

    Devuelve ``None`` si el expediente no existe.
    """
    objetivo = repo.objetivo(id_externo)
    if objetivo is None:
        return None

    texto = " ".join(str(objetivo.get(campo) or "") for campo in ("titulo", "descripcion")).strip()
    cpv4 = _cpv4(objetivo.get("cpv"))
    fecha = objetivo.get("fecha_publicacion")

    # ── Predecesor ──────────────────────────────────────────────────────────
    previos = repo.candidatos_a_predecesor(
        id_externo=id_externo,
        organo_id=objetivo.get("organo_id"),
        organo_contratacion=objetivo.get("organo_contratacion"),
        cpv4=cpv4,
        antes_de=fecha,
    )
    puntuados_previos, metodo = _ordenar(texto, previos)
    predecesor: Candidato | None = None
    if puntuados_previos:
        mejor, score = puntuados_previos[0]
        umbral = UMBRAL_PREDECESOR if metodo == "embedding" else UMBRAL_SOLAPE_FTS
        if score >= umbral:
            predecesor = _a_candidato(mejor, score, con_adjudicacion=True)

    # ── Similares ───────────────────────────────────────────────────────────
    otros = repo.candidatos_a_similar(id_externo=id_externo, cpv4=cpv4)
    puntuados_otros, metodo_similares = _ordenar(texto, otros)
    similares = [
        _a_candidato(fila, score, con_adjudicacion=False)
        for fila, score in puntuados_otros[:max_similares]
    ]

    return Similares(
        licitacion_id=id_externo,
        predecesor=predecesor,
        similares=similares,
        metodo=metodo_similares,
        n=len(previos) + len(otros),
    )
