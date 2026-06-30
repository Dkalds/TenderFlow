"""Motor de búsqueda híbrido — extrae la lógica RAG de investigador.py.

Encapsula búsqueda FAISS (semántica) + FTS5/BM25 (léxica) + LIKE fallback
con reranking híbrido. Función pura y reutilizable.
"""

from __future__ import annotations

import re
import time
from typing import Any

from db.repositories.licitaciones import LicitacionRepository
from observability.logging import get_logger

log = get_logger(__name__)

_repo = LicitacionRepository()

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
    barata de especificidad). Reutilizado por ``escape_fts5`` (FTS5) y por el
    fallback LIKE del repositorio para que ambos caminos compartan la misma
    noción de "palabra relevante".
    """
    cleaned = re.sub(r'["*+\-():\^/¿¡!?,.;]', " ", query).lower()
    tokens = [t for t in cleaned.split() if len(t) > 2 and t not in FTS5_STOPWORDS]
    if not tokens:
        return []
    return sorted(set(tokens), key=len, reverse=True)[:12]


def escape_fts5(query: str) -> str:
    """Escapa y normaliza la query para SQLite FTS5 MATCH (semántica RAG).

    Dos bugs históricos que esta función corrige:

    1. **AND implícito**: FTS5 trata tokens separados por espacio como AND
       lógico (``sap licitaciones`` exige docs con *ambas* palabras). Para
       preguntas en lenguaje natural eso devuelve 0 resultados casi siempre,
       forzando el fallback LIKE con peor relevancia. Unimos los tokens con
       ``OR`` explícito para semántica "cualquiera de estas palabras", que es
       lo correcto para recuperación RAG (BM25 ya prioriza términos raros).

    2. **Ruido de stopwords**: palabras interrogativas, conectores y términos
       que definen el corpus (``cuántas``, ``de``, ``licitaciones``,
       ``importe``...) inflaban la query y saturaban el ranking con documentos
       genéricos. Se filtran vía ``extract_keywords`` antes de construir la
       query.

    Cada token se encierra entre comillas dobles (con las comillas internas
    escapadas) para neutralizar operadores FTS5 y prevenir inyección; las
    comillas con ``OR`` entre ellas siguen produciendo disyunción de frases de
    una sola palabra (``"foo" OR "bar"``), no proximidad.
    """
    keywords = extract_keywords(query)
    if not keywords:
        return '""'
    quoted = [f'"{t.replace(chr(34), chr(34) * 2)}"' for t in keywords]
    return " OR ".join(quoted)


def faiss_search(question: str, top_k: int, embedding_model: str) -> list[tuple[str, float]]:
    """Búsqueda semántica FAISS. Devuelve (id_externo, score ∈ [0,1])."""
    try:
        from services.faiss_index import FaissIndex

        idx = FaissIndex.load()
        return idx.search(question, k=top_k, threshold=0.25)
    except Exception as exc:
        log.warning("search_engine.faiss_failed", error=str(exc))
        return []


def fts5_search(question: str, top_k: int) -> list[tuple[str, float]]:
    """Búsqueda léxica FTS5/BM25. Devuelve (id_externo, score ∈ [0,1]) normalizado."""
    return _repo.fts5_bm25_search(question, top_k)


def like_search(question: str, top_k: int) -> list[tuple[str, float]]:
    """LIKE fallback para cuando FTS5 no está disponible."""
    return _repo.like_fallback_search(question, top_k)


def hybrid_rerank(
    faiss_hits: list[tuple[str, float]],
    fts_hits: list[tuple[str, float]],
    alpha: float = 0.70,
    top_k: int = 10,
) -> list[tuple[str, float]]:
    """Reranking híbrido: alpha·FAISS + (1-alpha)·FTS5."""
    faiss_map = dict(faiss_hits)
    fts_map = dict(fts_hits)
    all_ids = set(faiss_map) | set(fts_map)
    combined = {
        id_: alpha * faiss_map.get(id_, 0.0) + (1 - alpha) * fts_map.get(id_, 0.0)
        for id_ in all_ids
    }
    return sorted(combined.items(), key=lambda x: x[1], reverse=True)[:top_k]


def fetch_docs(ids: list[str], allowed_ids: set[str] | None = None) -> dict[str, dict[str, Any]]:
    """Recupera metadatos de la BD para una lista de IDs, filtrando por allowed_ids."""
    return _repo.fetch_metadata_by_ids(ids, allowed_ids)


def rag_query(
    question: str,
    *,
    top_k: int = 5,
    allowed_ids: set[str] | None = None,
    embedding_model: str = "",
) -> tuple[list[dict[str, Any]], str]:
    """Búsqueda híbrida FAISS+FTS5 con reranking.

    Returns:
        (docs, source_badge) donde source_badge indica el motor usado.
    """
    t0 = time.perf_counter()
    faiss_hits = faiss_search(question, top_k * 2, embedding_model)
    fts_hits = fts5_search(question, top_k * 2)

    if faiss_hits and fts_hits:
        ranked = hybrid_rerank(faiss_hits, fts_hits, alpha=0.70, top_k=top_k)
        source = "🟣 FAISS+FTS5"
    elif faiss_hits:
        ranked = sorted(faiss_hits, key=lambda x: x[1], reverse=True)[:top_k]
        source = "🟣 FAISS"
    elif fts_hits:
        ranked = sorted(fts_hits, key=lambda x: x[1], reverse=True)[:top_k]
        source = "🔵 FTS5"
    else:
        ranked = like_search(question, top_k)
        source = "⚪ LIKE"

    ids = [id_ for id_, _ in ranked]
    docs_map = fetch_docs(ids, allowed_ids)

    docs: list[dict[str, Any]] = []
    for id_, score in ranked:
        if id_ in docs_map:
            doc = dict(docs_map[id_])
            doc["_score"] = score
            docs.append(doc)

    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    log.debug(
        "search_engine.rag_query",
        question=question[:80],
        n=len(docs),
        source=source,
        elapsed_ms=elapsed_ms,
        allowed=len(allowed_ids) if allowed_ids is not None else "all",
    )
    return docs, source
