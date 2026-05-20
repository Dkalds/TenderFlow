"""Motor de búsqueda híbrido — extrae la lógica RAG de investigador.py.

Encapsula búsqueda FAISS (semántica) + FTS5/BM25 (léxica) + LIKE fallback
con reranking híbrido. Función pura sin dependencia de Streamlit.
"""

from __future__ import annotations

import re
import time
from typing import Any

from db.database import connect
from observability.logging import get_logger

log = get_logger(__name__)


def escape_fts5(query: str) -> str:
    """Escapa la query para SQLite FTS5 MATCH, previniendo inyección de operadores."""
    tokens = re.sub(r'["*+\-():\^/]', " ", query).split()
    if not tokens:
        return '""'
    return " ".join(f'"{t.replace(chr(34), chr(34) * 2)}"' for t in tokens[:12])


def faiss_search(question: str, top_k: int, embedding_model: str) -> list[tuple[str, float]]:
    """Búsqueda semántica FAISS. Devuelve (id_externo, score ∈ [0,1])."""
    try:
        from dashboard.faiss_index import FaissIndex

        idx = FaissIndex.load()
        return idx.search(question, k=top_k, threshold=0.25)
    except Exception as exc:
        log.warning("search_engine.faiss_failed", error=str(exc))
        return []


def fts5_search(question: str, top_k: int) -> list[tuple[str, float]]:
    """Búsqueda léxica FTS5/BM25. Devuelve (id_externo, score ∈ [0,1]) normalizado."""
    escaped = escape_fts5(question)
    try:
        with connect() as c:
            cur = c.execute(
                "SELECT l.id_externo, bm25(licitaciones_fts) AS bm25_score "
                "FROM licitaciones_fts fts "
                "JOIN licitaciones l ON l.id_externo = fts.id_externo "
                f"WHERE licitaciones_fts MATCH ? ORDER BY bm25_score LIMIT {top_k * 2}",
                [escaped],
            )
            rows = cur.fetchall()
    except Exception as exc:
        log.warning("search_engine.fts5_failed", error=str(exc))
        return []

    if not rows:
        return []
    raw_scores = [abs(float(r[1])) for r in rows]
    max_s = max(raw_scores) if raw_scores else 1.0
    return [(r[0], s / max_s) for r, s in zip(rows, raw_scores, strict=False)]


def like_search(question: str, top_k: int) -> list[tuple[str, float]]:
    """LIKE fallback para cuando FTS5 no está disponible."""
    token = next(
        (w for w in question.split() if len(w) >= 4),
        question.split()[0] if question.split() else "",
    )
    if not token:
        return []
    try:
        with connect() as c:
            cur = c.execute(
                "SELECT id_externo FROM licitaciones "
                "WHERE titulo LIKE ? OR descripcion LIKE ? LIMIT ?",
                [f"%{token}%", f"%{token}%", top_k],
            )
            return [(r[0], 0.20) for r in cur.fetchall()]
    except Exception as exc:
        log.warning("search_engine.like_failed", error=str(exc))
        return []


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
    if not ids:
        return {}
    if allowed_ids is not None:
        ids = [i for i in ids if i in allowed_ids]
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    try:
        with connect() as c:
            cur = c.execute(
                f"SELECT id_externo, titulo, organo_contratacion, importe, "
                f"       descripcion, url, fecha_publicacion, ccaa, estado "
                f"FROM licitaciones WHERE id_externo IN ({placeholders})",
                ids,
            )
            cols = [d[0] for d in cur.description]
            return {r[0]: dict(zip(cols, r, strict=False)) for r in cur.fetchall()}
    except Exception as exc:
        log.warning("search_engine.fetch_docs_failed", error=str(exc))
        return {}


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
