"""Piezas compartidas de la búsqueda: la fusión RRF y la noción de palabra relevante.

- ``hybrid_search``: fusión Reciprocal Rank Fusion de la lista de texto completo
  y la de similitud vectorial sobre ``documento_chunks`` (pgvector), con el peso
  relativo de ambas gobernado por ``alpha``. La consume
  :func:`services.investigador.busqueda.buscar`, que con ella completa la
  lista del motor de texto.
- ``extract_keywords`` y ``FTS5_STOPWORDS``: qué cuenta como palabra relevante.
  Se definen en :mod:`shared.palabras_clave` (los usa también la persistencia)
  y se reexportan aquí.

FAISS se eliminó en la Fase 3 del plan de reducción de superficie
(2026-07-04). El camino FTS → LIKE de ``rag_query`` (con ``escape_fts5``,
``fts5_search``, ``like_search`` y ``fetch_docs``) se retiró el 2026-10-17: la
búsqueda del Investigador y ``/ask`` responden con el motor de
:mod:`services.investigador.busqueda` desde 2026-10-09 y no le quedaban
llamantes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from observability.logging import get_logger
from shared.palabras_clave import FTS5_STOPWORDS as FTS5_STOPWORDS
from shared.palabras_clave import extract_keywords as extract_keywords

log = get_logger(__name__)


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
