"""Embeddings semánticos para similitud de licitaciones.

Usa sentence-transformers si está disponible; si no, cae a fallback
basado en coincidencia de substrings (como portfolio_match actual).

Modelo por defecto: paraphrase-multilingual-MiniLM-L12-v2
(soporta español nativo, modelo ligero ~400 MB).

El modelo activo se lee de ``config.settings.EMBEDDING_MODEL`` — se puede
cambiar a ``paraphrase-multilingual-mpnet-base-v2`` para mayor calidad.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, cast

import numpy as np

from config import settings
from observability import get_logger

log = get_logger(__name__)

# Resolved from settings at import time so lru_cache works correctly
_MODEL_NAME = settings.EMBEDDING_MODEL

try:  # pragma: no cover - fallback when Streamlit runtime no disponible
    import streamlit as _st

    _cache_resource = _st.cache_resource(ttl=settings.DASHBOARD_CACHE_TTL or None)
except Exception:  # pragma: no cover

    def _cache_resource(fn: Callable[..., Any]) -> Callable[..., Any]:  # type: ignore[misc]
        return fn

# ── Lazy model loading ──────────────────────────────────────────────────


def _has_sentence_transformers() -> bool:
    try:
        import sentence_transformers  # noqa: F401

        return True
    except ImportError:
        return False


@_cache_resource
def _load_model() -> Any:
    """Carga el modelo sentence-transformers (cached en memoria)."""
    from sentence_transformers import SentenceTransformer

    log.info("embeddings.loading_model", model=_MODEL_NAME)
    return SentenceTransformer(_MODEL_NAME)


def embeddings_available() -> bool:
    """Indica si el motor de embeddings está disponible."""
    return _has_sentence_transformers()


# ── Core functions ──────────────────────────────────────────────────────


def encode_texts(texts: list[str], batch_size: int = 64) -> np.ndarray:
    """Codifica una lista de textos en embeddings.

    Returns:
        ndarray de shape (n, dim) con embeddings normalizados.
    """
    if not _has_sentence_transformers():
        msg = "sentence-transformers no instalado — usa `pip install sentence-transformers`"
        raise ImportError(msg)

    model = _load_model()
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=False,
        normalize_embeddings=True,
    )
    return np.asarray(embeddings)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Calcula similitud coseno entre vectores (normalizados = dot product)."""
    if a.ndim == 1:
        a = a.reshape(1, -1)
    if b.ndim == 1:
        b = b.reshape(1, -1)
    return cast(np.ndarray, a @ b.T)


def semantic_match(
    query: str,
    corpus: list[str],
    threshold: float = 0.5,
) -> list[tuple[int, float]]:
    """Encuentra textos del corpus similares a la query.

    Args:
        query: Texto de búsqueda.
        corpus: Lista de textos candidatos.
        threshold: Similitud mínima (0-1).

    Returns:
        Lista de (índice, score) ordenados por score desc.
    """
    if not corpus:
        return []

    q_emb = encode_texts([query])
    c_emb = encode_texts(corpus)
    scores = cosine_similarity(q_emb, c_emb).flatten()

    results = [(int(i), float(scores[i])) for i in range(len(scores)) if scores[i] >= threshold]
    results.sort(key=lambda x: x[1], reverse=True)
    return results


# ── Fallback basado en substrings ───────────────────────────────────────

_WORD_RE = re.compile(r"[a-záéíóúñü0-9/\-]+", re.IGNORECASE)


def substring_match(
    query: str,
    corpus: list[str],
    threshold: float = 0.3,
) -> list[tuple[int, float]]:
    """Fallback: similitud basada en % de palabras de la query presentes en el texto."""
    if not corpus:
        return []

    q_words = set(_WORD_RE.findall(query.lower()))
    if not q_words:
        return []

    results = []
    for i, text in enumerate(corpus):
        t_words = set(_WORD_RE.findall(text.lower()))
        overlap = len(q_words & t_words) / len(q_words) if q_words else 0
        if overlap >= threshold:
            results.append((i, overlap))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


def smart_match(
    query: str,
    corpus: list[str],
    threshold: float = 0.5,
) -> list[tuple[int, float]]:
    """Usa embeddings si están disponibles, sino fallback a substrings."""
    if embeddings_available():
        try:
            return semantic_match(query, corpus, threshold=threshold)
        except Exception:
            log.warning("embeddings.fallback", reason="error in semantic_match")

    return substring_match(query, corpus, threshold=max(0.3, threshold - 0.2))
