"""Clustering semántico de licitaciones basado en embeddings.

Agrupa licitaciones por similitud semántica usando KMeans (o MiniBatchKMeans
para datasets grandes) sobre los embeddings de ``dashboard.embeddings``.
Si sentence-transformers no está disponible, usa TF-IDF como fallback.

Refactor F1+F3:
    - Imports a nivel de módulo (sklearn está en core requirements).
    - Excepciones estrechas (ImportError, ValueError, RuntimeError).
    - Stopwords cargadas desde ``shared/stopwords_es.txt``.
    - MiniBatchKMeans cuando ``n_samples > _MINIBATCH_THRESHOLD``.
    - ``k_max ≤ sqrt(n)/2`` para evitar over-clustering.
    - Etiquetado por **c-TF-IDF** (class-based TF-IDF) en vez de simple
      ``Counter`` de palabras.

Uso típico:
    from dashboard.clustering import cluster_licitaciones

    result = cluster_licitaciones(df, n_clusters=8)
    # result: DataFrame con columnas cluster_id, cluster_label añadidas
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from sklearn.cluster import KMeans, MiniBatchKMeans
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import normalize

from observability import get_logger

log = get_logger(__name__)

_MIN_ROWS = 10
_DEFAULT_CLUSTERS = 8
_MAX_CLUSTERS = 20
_MINIBATCH_THRESHOLD = 50_000
_MINIBATCH_BATCH_SIZE = 4_096

_STOPWORDS_PATH = Path(__file__).resolve().parent.parent / "shared" / "stopwords_es.txt"


@lru_cache(maxsize=1)
def _stopwords() -> frozenset[str]:
    """Carga las stopwords desde ``shared/stopwords_es.txt``."""
    try:
        text = _STOPWORDS_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("stopwords_load_failed", path=str(_STOPWORDS_PATH), error=str(exc))
        return frozenset()
    words = {
        line.strip().lower()
        for line in text.splitlines()
        if line.strip() and not line.startswith("#")
    }
    return frozenset(words)


def _df_cache_fingerprint(df: pd.DataFrame) -> tuple[object, ...]:
    """Fingerprint compacto para caché de clustering.

    Evita el hashing profundo por defecto de Streamlit sobre DataFrames grandes.
    Usa señales estables y baratas (shape/columnas + hash parcial de ids/fechas).
    """
    cols = tuple(df.columns)
    n_rows = len(df)
    if n_rows == 0:
        return (n_rows, cols)

    id_hash: int | None = None
    if "id_externo" in df.columns:
        try:
            id_hash = int(pd.util.hash_pandas_object(df["id_externo"], index=False).sum())
        except (TypeError, ValueError):
            id_hash = None

    date_max: str | None = None
    if "fecha_publicacion" in df.columns:
        try:
            date_max = str(pd.to_datetime(df["fecha_publicacion"], errors="coerce").max())
        except (TypeError, ValueError):
            date_max = None

    imp_sum: float | None = None
    if "importe" in df.columns:
        try:
            imp_sum = float(pd.to_numeric(df["importe"], errors="coerce").fillna(0).sum())
        except (TypeError, ValueError):
            imp_sum = None

    return (n_rows, cols, id_hash, date_max, imp_sum)


def _tfidf_embeddings(texts: list[str], n_features: int = 256) -> np.ndarray:
    """Fallback: TF-IDF sparse → dense para cuando no hay sentence-transformers."""
    vec = TfidfVectorizer(
        max_features=n_features,
        ngram_range=(1, 2),
        min_df=2,
        sublinear_tf=True,
        stop_words=list(_stopwords()),
    )
    mat = vec.fit_transform(texts)
    dense = mat.toarray().astype(np.float32)
    return normalize(dense)  # type: ignore[no-any-return]


def _get_embeddings(texts: list[str]) -> np.ndarray:
    """Devuelve embeddings semánticos o TF-IDF según disponibilidad."""
    try:
        from dashboard.embeddings import embeddings_available, encode_texts
    except ImportError as exc:
        log.warning("clustering_embeddings_module_missing", error=str(exc))
        return _tfidf_embeddings(texts)

    if embeddings_available():
        try:
            return encode_texts(texts)
        except (RuntimeError, ValueError) as exc:
            log.warning("clustering_embeddings_failed", error=str(exc))

    log.info("clustering_using_tfidf_fallback")
    return _tfidf_embeddings(texts)


def _kmeans_factory(k: int, n_samples: int) -> KMeans | MiniBatchKMeans:
    """Devuelve KMeans o MiniBatchKMeans según el tamaño del dataset."""
    if n_samples >= _MINIBATCH_THRESHOLD:
        log.info("clustering_using_minibatch", n=n_samples, k=k)
        return MiniBatchKMeans(
            n_clusters=k,
            random_state=42,
            batch_size=_MINIBATCH_BATCH_SIZE,
            n_init=5,
            max_iter=100,
        )
    return KMeans(n_clusters=k, random_state=42, n_init=10)


def _k_max_for(n_samples: int, hard_cap: int = _MAX_CLUSTERS) -> int:
    """k_max ≤ sqrt(n)/2 (regla heurística del plan F3)."""
    soft = max(2, int(math.sqrt(n_samples) / 2))
    return min(hard_cap, soft, max(2, n_samples - 1))


def _optimal_k(embeddings: np.ndarray, k_min: int = 3, k_max: int | None = None) -> int:
    """Elige el número óptimo de clusters via silhouette score."""
    n_samples = len(embeddings)
    if k_max is None:
        k_max = _k_max_for(n_samples)
    k_max = min(k_max, n_samples - 1)
    if k_max < k_min:
        return max(2, k_min)

    best_k = k_min
    best_score = -1.0
    for k in range(k_min, k_max + 1):
        km = _kmeans_factory(k, n_samples)
        labels = km.fit_predict(embeddings)
        try:
            score = float(
                silhouette_score(embeddings, labels, sample_size=min(1000, n_samples))
            )
        except ValueError:
            score = -1.0
        if score > best_score:
            best_score = score
            best_k = k
    return best_k


_TOKEN_RE = re.compile(r"\b[a-záéíóúñ]{4,}\b")


def _ctfidf_labels(
    texts: Iterable[str],
    labels: np.ndarray,
    top_n: int = 3,
) -> dict[int, str]:
    """Etiquetado de clusters con c-TF-IDF (class-based TF-IDF).

    Agrupa los documentos por cluster (un "documento" por cluster), aplica
    TF-IDF sobre esos agregados y elige los ``top_n`` términos con mayor peso.
    Más robusto que un simple ``Counter`` de palabras: penaliza términos
    comunes a todos los clusters y favorece términos distintivos.
    """
    texts_list = list(texts)
    unique = sorted(set(labels.tolist()))
    if not unique:
        return {}

    grouped: dict[int, str] = {cid: "" for cid in unique}
    for txt, cid in zip(texts_list, labels.tolist(), strict=False):
        grouped[int(cid)] += " " + (txt or "")

    docs = [grouped[cid] for cid in unique]
    if not any(d.strip() for d in docs):
        return {cid: "otros" for cid in unique}

    vec = TfidfVectorizer(
        token_pattern=_TOKEN_RE.pattern,
        ngram_range=(1, 2),
        min_df=1,
        sublinear_tf=True,
        stop_words=list(_stopwords()),
        lowercase=True,
        max_features=5_000,
    )
    try:
        mat = vec.fit_transform(docs)
    except ValueError:
        return {cid: "otros" for cid in unique}

    terms = np.array(vec.get_feature_names_out())
    out: dict[int, str] = {}
    for idx, cid in enumerate(unique):
        row = mat.getrow(idx).toarray().ravel()
        if not row.any():
            out[int(cid)] = "otros"
            continue
        top_idx = np.argsort(row)[::-1][:top_n]
        out[int(cid)] = ", ".join(terms[top_idx])
    return out


def _cluster_keywords(texts: list[str], top_n: int = 3) -> str:
    """Etiqueta un cluster aislado vía CountVectorizer + stopwords externas.

    Mantenido por retrocompatibilidad con tests/llamadores externos.
    """
    if not texts:
        return "otros"
    vec = CountVectorizer(
        token_pattern=_TOKEN_RE.pattern,
        stop_words=list(_stopwords()),
        lowercase=True,
        max_features=1_000,
    )
    try:
        mat = vec.fit_transform(texts)
    except ValueError:
        return "otros"
    sums = np.asarray(mat.sum(axis=0)).ravel()
    if not sums.any():
        return "otros"
    terms = np.array(vec.get_feature_names_out())
    top_idx = np.argsort(sums)[::-1][:top_n]
    return ", ".join(terms[top_idx])


@st.cache_data(
    ttl=1800,
    show_spinner="Calculando clusters semánticos…",
    hash_funcs={pd.DataFrame: _df_cache_fingerprint},
)  # 30 min cache
def cluster_licitaciones(
    df: pd.DataFrame,
    n_clusters: int | None = None,
    auto_k: bool = False,
) -> pd.DataFrame:
    """Agrupa licitaciones por similitud semántica.

    Intenta primero usar los clusters pre-computados desde ``mat_clusters``
    (generados por el scheduler). Si no están disponibles o no cubren los IDs
    del DataFrame actual, recalcula online.

    Args:
        df: DataFrame con columnas ``titulo`` y ``descripcion``.
        n_clusters: Número de clusters deseados. Si None y auto_k=False, usa DEFAULT.
        auto_k: Si True, calcula el k óptimo via silhouette (más lento).

    Returns:
        DataFrame original con columnas añadidas: ``cluster_id``, ``cluster_label``.
    """
    result = df.copy()
    result["cluster_id"] = 0
    result["cluster_label"] = "sin_cluster"

    if len(df) < _MIN_ROWS:
        log.warning("clustering_too_few_rows", n=len(df))
        return result

    # ── Fast path: usar clusters pre-computados si están disponibles ──────
    if not auto_k and n_clusters in (None, _DEFAULT_CLUSTERS):
        try:
            from dashboard.data_loader import load_mat_clusters

            mat = load_mat_clusters()
        except ImportError as exc:
            log.debug("clustering_precomputed_unavailable", error=str(exc))
            mat = pd.DataFrame()

        if not mat.empty and "id_externo" in mat.columns:
            merged = result.merge(
                mat[["id_externo", "cluster_id", "cluster_label"]],
                on="id_externo",
                how="left",
                suffixes=("", "_mat"),
            )
            coverage = merged["cluster_id_mat"].notna().mean()
            if coverage >= 0.8:
                result["cluster_id"] = merged["cluster_id_mat"].fillna(0).astype(int)
                result["cluster_label"] = merged["cluster_label_mat"].fillna("sin_cluster")
                log.info(
                    "clustering_used_precomputed",
                    coverage=round(coverage, 2),
                    n_rows=len(result),
                )
                return result

    # ── Online clustering ─────────────────────────────────────────────────
    desc_col = df["descripcion"].fillna("") if "descripcion" in df.columns else ""
    texts = (df["titulo"].fillna("") + " " + desc_col).tolist()

    try:
        embeddings = _get_embeddings(texts)
    except (RuntimeError, ValueError, MemoryError) as exc:
        log.warning("clustering_embeddings_failed", error=str(exc))
        return result

    k_max = _k_max_for(len(df))
    if auto_k:
        k = _optimal_k(embeddings, k_min=3, k_max=k_max)
    else:
        # Cuando el usuario pasa n_clusters explícito, respetamos la petición
        # (sólo se aplica el cap suave sqrt(n)/2 al modo auto_k).
        k = n_clusters or _DEFAULT_CLUSTERS
        k = min(k, _MAX_CLUSTERS, len(df) - 1)
        k = max(2, k)

    try:
        km = _kmeans_factory(k, len(df))
        labels = km.fit_predict(embeddings)
    except (ValueError, RuntimeError) as exc:
        log.warning("clustering_kmeans_failed", error=str(exc))
        return result

    result["cluster_id"] = labels
    label_map = _ctfidf_labels(texts, labels)
    result["cluster_label"] = result["cluster_id"].map(label_map).fillna("otros")
    log.info("clustering_done", n_clusters=k, n_rows=len(df))
    return result


def cluster_summary(clustered_df: pd.DataFrame) -> pd.DataFrame:
    """Resumen estadístico por cluster."""
    if "cluster_id" not in clustered_df.columns:
        return pd.DataFrame()

    agg = (
        clustered_df.groupby(["cluster_id", "cluster_label"])
        .agg(
            n=("id_externo", "count"),
            importe_medio=("importe", "mean"),
            importe_total=("importe", "sum"),
        )
        .reset_index()
        .sort_values("n", ascending=False)
    )
    agg["importe_medio"] = agg["importe_medio"].round(0)
    agg["importe_total"] = agg["importe_total"].round(0)
    return agg
