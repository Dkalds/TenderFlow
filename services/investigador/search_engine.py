"""Piezas compartidas de la búsqueda: la fusión RRF y la noción de palabra relevante.

- ``hybrid_search``: fusión Reciprocal Rank Fusion de la lista de texto completo
  y la de similitud vectorial sobre ``documento_chunks`` (pgvector), con el peso
  relativo de ambas gobernado por ``alpha``. La consume
  :func:`services.investigador.busqueda.buscar`, que con ella completa la
  lista del motor de texto.
- ``extract_keywords`` y ``FTS5_STOPWORDS``: qué cuenta como palabra relevante.
  Los comparten el último recurso por subcadena de ``/ask``
  (``LicitacionRepository.search_like_for_ask``) y la interpretación de la
  frase (:mod:`services.investigador.consulta`).

FAISS se eliminó en la Fase 3 del plan de reducción de superficie
(2026-07-04). El camino FTS → LIKE de ``rag_query`` (con ``escape_fts5``,
``fts5_search``, ``like_search`` y ``fetch_docs``) se retiró el 2026-10-17: la
búsqueda del Investigador y ``/ask`` responden con el motor de
:mod:`services.investigador.busqueda` desde 2026-10-09 y no le quedaban
llamantes.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

# Stopwords en español: palabras interrogativas, conectores, verbos de petición y
# los pocos términos que *definen* el corpus (y por tanto no discriminan: aparecen
# en casi todos los documentos). Se filtran antes de construir la query FTS5/LIKE
# para evitar que saturen el ranking con documentos irrelevantes. Deliberadamente
# NO incluye sustantivos de dominio discriminantes (contrato, servicio, obra,
# pública...) — esos sí aportan señal en búsquedas por palabra clave.
# Compartido con el fallback LIKE del repositorio (search_like_for_ask).
FTS5_STOPWORDS: frozenset[str] = frozenset(
    {
        # Conectores y artículos
        "de",
        "la",
        "el",
        "y",
        "o",
        "u",
        "a",
        "en",
        "es",
        "que",
        "qué",
        "cuál",
        "cuáles",
        "cómo",
        "como",
        "donde",
        "dónde",
        "hay",
        "ha",
        "un",
        "una",
        "unos",
        "unas",
        "los",
        "las",
        "del",
        "por",
        "para",
        "con",
        "sin",
        "sobre",
        "entre",
        "hasta",
        "si",
        "no",
        "le",
        "lo",
        "su",
        "sus",
        "se",
        "al",
        "más",
        "pero",
        "este",
        "esta",
        "estos",
        "estas",
        "ese",
        "esa",
        "esos",
        "esas",
        "aquel",
        "aquella",
        "yo",
        "tú",
        "él",
        "ella",
        "nosotros",
        "vosotros",
        "ellos",
        "ellas",
        "mi",
        "tu",
        "mis",
        "tus",
        "nuestro",
        "vuestro",
        "nuestra",
        "vuestra",
        "son",
        "ser",
        "estar",
        "están",
        "fue",
        "sido",
        "sería",
        "tiene",
        "tienen",
        "tuvo",
        "tendrán",
        "sea",
        "sean",
        "todas",
        "todos",
        "toda",
        "todo",
        "ambos",
        "cada",
        "cuánto",
        "cuánta",
        "cuántos",
        "cuántas",
        # Verbos de petición comunes en preguntas RAG
        "dame",
        "dime",
        "muestra",
        "muéstrame",
        "mostrame",
        "lista",
        "listar",
        "busca",
        "buscar",
        "encuentra",
        "información",
        "info",
        "quiero",
        "necesito",
        "saber",
        "conocer",
        # Conectores de tema ("...relacionadas con X", "...sobre Y") que
        # sobreviven al filtro de longitud pero no aportan señal y, bajo
        # semántica OR, arrastran documentos irrelevantes.
        "relacionada",
        "relacionadas",
        "relacionado",
        "relacionados",
        "relativa",
        "relativas",
        "relativo",
        "relativos",
        "referente",
        "referentes",
        "acerca",
        "respecto",
        "vinculada",
        "vinculadas",
        "vinculado",
        "vinculados",
        # Términos que *definen* el corpus (un buscador de licitaciones: estas
        # palabras son el equivalente de buscar "email" dentro del buzón —
        # presentes en casi todo, no discriminan y saturan el OR).
        "licitación",
        "licitacion",
        "licitaciones",
        "expediente",
        "expedientes",
        "importe",
        "total",
    }
)


def extract_keywords(query: str) -> list[str]:
    """Extrae los tokens significativos de una query en lenguaje natural.

    Elimina metacaracteres, pasa a minúsculas, filtra stopwords y tokens de
    <=2 caracteres, y deduplica conservando los términos más largos (heurística
    barata de especificidad). Lo usa el último recurso LIKE de ``/ask``
    (``search_like_for_ask``).
    """
    cleaned = re.sub(r'["*+\-():\^/¿¡!?,.;]', " ", query).lower()
    tokens = [t for t in cleaned.split() if len(t) > 2 and t not in FTS5_STOPWORDS]
    if not tokens:
        return []
    return sorted(set(tokens), key=len, reverse=True)[:12]


def hybrid_search(
    question: str,
    top_k: int,
    *,
    alpha: float | None = None,
    filtros: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Fusión RRF (FTS + pgvector) para una consulta, o ``[]`` si no aplica.

    Devuelve licitaciones (las columnas del anuncio, más ``tecnologia``,
    ``rrf_score`` y ``chunks``) ya ordenadas por la fusión.

    ``[]`` significa «este camino no está disponible o no encontró nada» y el
    llamador debe degradar a FTS: no hay modelo de embeddings instalado
    (extra ``[ml]``), no hay un solo chunk embebido en la BD, la consulta no
    se pudo codificar, o el SQL falló (``hybrid_search_docs`` es fail-open).
    Las dos comprobaciones previas —modelo y corpus— son lo que permite al
    llamador etiquetar la fuente por el camino REALMENTE ejecutado en vez de
    por configuración.

    ``filtros`` son los del ámbito, en la forma de ``hybrid_search_docs``
    (``services.investigador.busqueda.filtros_de_fusion``): acotan las dos
    listas antes de fusionar. Hasta 2026-10 la ruta filtraba después, contra un
    conjunto de ids con tope, y un ámbito ancho perdía resultados.

    Nota: esto NO mira ``settings.RAG_HYBRID_ENABLED``. Ese flag existe para
    decidir si ``/ask`` cambia de recuperación por debajo de un LLM que ya
    responde; aquí la única pregunta es si hay embeddings con los que fusionar.
    """
    from services.embeddings import embeddings_available, encode_texts

    if not embeddings_available():
        return []

    from db.search_backend import document_embeddings_available, hybrid_search_docs

    if not document_embeddings_available():
        return []

    try:
        query_embedding = encode_texts([question])[0].tolist()
    except Exception as e:
        log.debug("hybrid_search.embed_failed", error=str(e))
        return []

    try:
        docs = hybrid_search_docs(
            question,
            query_embedding,
            limit=top_k,
            candidate_k=max(top_k, 50),
            alpha=alpha,
            **(filtros or {}),
        )
    except Exception as e:
        log.debug("hybrid_search.query_failed", error=str(e))
        return []
    return docs
