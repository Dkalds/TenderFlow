"""Clustering semántico de licitaciones basado en embeddings.

Agrupa licitaciones por similitud semántica usando KMeans sobre los
embeddings de ``dashboard.embeddings``. Si sentence-transformers no está
disponible, usa TF-IDF como fallback.

Uso típico:
    from dashboard.clustering import cluster_licitaciones

    result = cluster_licitaciones(df, n_clusters=8)
    # result: DataFrame con columnas cluster_id, cluster_label añadidas
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd
import streamlit as st

from observability import get_logger

log = get_logger(__name__)

_MIN_ROWS = 10
_DEFAULT_CLUSTERS = 8
_MAX_CLUSTERS = 20


def _df_cache_fingerprint(df: pd.DataFrame) -> tuple[object, ...]:
    """Fingerprint compacto para caché de clustering.

    Evita el hashing profundo por defecto de Streamlit sobre DataFrames grandes.
    Usa señales estables y baratas (shape/columnas + hash parcial de ids/fechas).
    """
    try:
        cols = tuple(df.columns)
        n_rows = len(df)

        if n_rows == 0:
            return (n_rows, cols)

        import pandas as _pd

        id_hash = None
        if "id_externo" in df.columns:
            id_hash = int(_pd.util.hash_pandas_object(df["id_externo"], index=False).sum())

        date_max = None
        if "fecha_publicacion" in df.columns:
            date_max = str(_pd.to_datetime(df["fecha_publicacion"], errors="coerce").max())

        imp_sum = None
        if "importe" in df.columns:
            imp_sum = float(_pd.to_numeric(df["importe"], errors="coerce").fillna(0).sum())

        return (n_rows, cols, id_hash, date_max, imp_sum)
    except Exception:
        # Fallback ultraseguro: tamaño + columnas.
        return (len(df), tuple(df.columns))


def _tfidf_embeddings(texts: list[str], n_features: int = 256) -> np.ndarray:
    """Fallback: TF-IDF sparse → dense para cuando no hay sentence-transformers."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.preprocessing import normalize

    vec = TfidfVectorizer(
        max_features=n_features,
        ngram_range=(1, 2),
        min_df=2,
        sublinear_tf=True,
    )
    mat = vec.fit_transform(texts)
    dense = mat.toarray().astype(np.float32)
    return normalize(dense)  # type: ignore[no-any-return]


def _get_embeddings(texts: list[str]) -> np.ndarray:
    """Devuelve embeddings semánticos o TF-IDF según disponibilidad."""
    try:
        from dashboard.embeddings import embeddings_available, encode_texts

        if embeddings_available():
            return encode_texts(texts)
    except Exception as exc:
        log.warning("clustering_embeddings_unavailable", error=str(exc))

    log.info("clustering_using_tfidf_fallback")
    return _tfidf_embeddings(texts)


def _optimal_k(embeddings: np.ndarray, k_min: int = 3, k_max: int = 12) -> int:
    """Elige el número óptimo de clusters via silhouette score."""
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    k_max = min(k_max, len(embeddings) - 1)
    if k_max < k_min:
        return k_min

    best_k = k_min
    best_score = -1.0
    for k in range(k_min, k_max + 1):
        km = KMeans(n_clusters=k, random_state=42, n_init=5)
        labels = km.fit_predict(embeddings)
        try:
            score = float(
                silhouette_score(embeddings, labels, sample_size=min(1000, len(embeddings)))
            )
        except Exception:
            score = -1.0
        if score > best_score:
            best_score = score
            best_k = k
    return best_k


def _cluster_keywords(texts: list[str], top_n: int = 3) -> str:
    """Extrae las palabras más frecuentes de un conjunto de textos para etiquetar el cluster."""
    from collections import Counter

    _STOPWORDS = {
        "de",
        "del",
        "la",
        "el",
        "los",
        "las",
        "un",
        "una",
        "y",
        "en",
        "para",
        "con",
        "por",
        "a",
        "al",
        "se",
        "que",
        "es",
        "o",
        "e",
        "su",
        "sus",
        "sistema",
        "servicio",
        "servicios",
        "contrato",
        "licitación",
        "proyecto",
    }
    words: list[str] = []
    for text in texts:
        tokens = re.findall(r"\b[a-záéíóúñ]{4,}\b", text.lower())
        words.extend(t for t in tokens if t not in _STOPWORDS)
    if not words:
        return "otros"
    top = Counter(words).most_common(top_n)
    return ", ".join(w for w, _ in top)


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
    from sklearn.cluster import KMeans

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
        except Exception as exc:
            log.debug("clustering_precomputed_unavailable", error=str(exc))

    # ── Online clustering ─────────────────────────────────────────────────
    desc_col = df["descripcion"].fillna("") if "descripcion" in df.columns else ""
    texts = (df["titulo"].fillna("") + " " + desc_col).tolist()

    try:
        embeddings = _get_embeddings(texts)
    except Exception as exc:
        log.warning("clustering_embeddings_failed", error=str(exc))
        return result

    if auto_k:
        k = _optimal_k(embeddings, k_min=3, k_max=min(_MAX_CLUSTERS, len(df) // 5))
    else:
        k = n_clusters or _DEFAULT_CLUSTERS
        k = min(k, len(df) - 1, _MAX_CLUSTERS)

    try:
        km = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = km.fit_predict(embeddings)
    except Exception as exc:
        log.warning("clustering_kmeans_failed", error=str(exc))
        return result

    result["cluster_id"] = labels

    # Generar labels descriptivos por cluster
    label_map: dict[int, str] = {}
    for cid in range(k):
        mask = labels == cid
        cluster_texts = [t for t, m in zip(texts, mask, strict=False) if m]
        label_map[cid] = _cluster_keywords(cluster_texts)

    result["cluster_label"] = result["cluster_id"].map(label_map)
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
