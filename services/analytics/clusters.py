"""Clusters analytics — real semantic clustering for the API layer.

Server-side port of the pure sklearn logic in ``dashboard/clustering.py``
(KMeans / MiniBatchKMeans over TF-IDF embeddings with c-TF-IDF keyword
labels), with the Streamlit caching and the ``dashboard.embeddings`` /
``mat_clusters`` fast-path removed. Returns per-cluster summaries, importe
box-plot statistics and a bounded sample of tenders for drill-down.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import SupportsInt, cast

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
from sklearn.cluster import KMeans, MiniBatchKMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import normalize

from observability.logging import get_logger
from services.classification import estado_label
from services.licitaciones import load_stats_dataframe

log = get_logger(__name__)

_MIN_ROWS = 10
_DEFAULT_CLUSTERS = 8
_MAX_CLUSTERS = 20
_MINIBATCH_THRESHOLD = 50_000
_MINIBATCH_BATCH_SIZE = 4_096
_MAX_ROWS = 30_000  # soft cap for online clustering latency
_ITEMS_PER_CLUSTER = 50
_TOKEN_RE = re.compile(r"\b[a-záéíóúñ]{4,}\b")

_STOPWORDS_PATH = Path(__file__).resolve().parents[2] / "shared" / "stopwords_es.txt"


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class ClustersFilters(BaseModel):
    """Query filters for the clusters endpoint."""

    n_clusters: int | None = None
    auto_k: bool = False
    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None


class ClusterItem(BaseModel):
    """Single tender inside a cluster (drill-down)."""

    id_externo: str
    titulo: str | None = None
    organo_contratacion: str | None = None
    importe: float | None = None
    ccaa: str | None = None
    estado: str | None = None


class ImporteBox(BaseModel):
    """Five-number summary of importe for a cluster (box-plot)."""

    min: float
    q1: float
    median: float
    q3: float
    max: float


class ClusterEntry(BaseModel):
    """Per-cluster aggregate."""

    cluster_id: int
    label: str
    n: int
    importe_medio: float
    importe_total: float
    importe_box: ImporteBox | None = None
    items: list[ClusterItem] = Field(default_factory=list)


class ClustersResult(BaseModel):
    """Combined clusters response."""

    n_clusters_detectados: int = 0
    total: int = 0
    clusters: list[ClusterEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Pure clustering helpers (ported from dashboard/clustering.py)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _stopwords() -> tuple[str, ...]:
    try:
        text = _STOPWORDS_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("stopwords_load_failed", path=str(_STOPWORDS_PATH), error=str(exc))
        return ()
    return tuple(
        line.strip().lower()
        for line in text.splitlines()
        if line.strip() and not line.startswith("#")
    )


def _tfidf_embeddings(texts: list[str], n_features: int = 256) -> np.ndarray:
    """TF-IDF sparse → dense, L2-normalised."""
    try:
        vec = TfidfVectorizer(
            max_features=n_features,
            ngram_range=(1, 2),
            min_df=2,
            sublinear_tf=True,
            stop_words=list(_stopwords()),
        )
        mat = vec.fit_transform(texts)
    except ValueError:
        # Degenerate vocabulary (tiny / repetitive corpus) → relax min_df.
        vec = TfidfVectorizer(max_features=n_features, sublinear_tf=True)
        mat = vec.fit_transform(texts)
    dense = mat.toarray().astype(np.float32)
    return normalize(dense)  # type: ignore[no-any-return]


def _kmeans_factory(k: int, n_samples: int) -> KMeans | MiniBatchKMeans:
    if n_samples >= _MINIBATCH_THRESHOLD:
        return MiniBatchKMeans(
            n_clusters=k,
            random_state=42,
            batch_size=_MINIBATCH_BATCH_SIZE,
            n_init=5,
            max_iter=100,
        )
    return KMeans(n_clusters=k, random_state=42, n_init=10)


def _k_max_for(n_samples: int, hard_cap: int = _MAX_CLUSTERS) -> int:
    soft = max(2, int(math.sqrt(n_samples) / 2))
    return min(hard_cap, soft, max(2, n_samples - 1))


def _optimal_k(embeddings: np.ndarray, k_min: int = 3, k_max: int | None = None) -> int:
    n_samples = len(embeddings)
    if k_max is None:
        k_max = _k_max_for(n_samples)
    k_max = min(k_max, n_samples - 1)
    if k_max < k_min:
        return max(2, k_min)
    best_k, best_score = k_min, -1.0
    for k in range(k_min, k_max + 1):
        labels = _kmeans_factory(k, n_samples).fit_predict(embeddings)
        try:
            score = float(silhouette_score(embeddings, labels, sample_size=min(1000, n_samples)))
        except ValueError:
            score = -1.0
        if score > best_score:
            best_score, best_k = score, k
    return best_k


def _ctfidf_labels(texts: Iterable[str], labels: np.ndarray, top_n: int = 3) -> dict[int, str]:
    """Class-based TF-IDF keyword labels per cluster."""
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_df() -> pd.DataFrame:
    rows = load_stats_dataframe()
    df = pd.DataFrame(rows)
    if not df.empty:
        df["fecha_publicacion"] = pd.to_datetime(df["fecha_publicacion"], errors="coerce", utc=True)
        df["importe"] = pd.to_numeric(df["importe"], errors="coerce")
    return df


def _apply_filters(df: pd.DataFrame, filters: ClustersFilters) -> pd.DataFrame:
    if df.empty:
        return df
    if filters.fecha_desde is not None:
        df = df[df["fecha_publicacion"] >= pd.Timestamp(filters.fecha_desde, tz="UTC")]
    if filters.fecha_hasta is not None:
        df = df[df["fecha_publicacion"] <= pd.Timestamp(filters.fecha_hasta, tz="UTC")]
    if filters.ccaa:
        df = df[df["ccaa"] == filters.ccaa]
    return df


def _resolve_k(embeddings: np.ndarray, filters: ClustersFilters, n: int) -> int:
    if filters.auto_k:
        return _optimal_k(embeddings, k_min=3, k_max=_k_max_for(n))
    k = filters.n_clusters or _DEFAULT_CLUSTERS
    return max(2, min(k, _MAX_CLUSTERS, n - 1))


def _box(importes: pd.Series) -> ImporteBox | None:
    vals = importes.dropna()
    if vals.empty:
        return None
    arr = vals.to_numpy(dtype=float)
    return ImporteBox(
        min=float(np.min(arr)),
        q1=float(np.percentile(arr, 25)),
        median=float(np.percentile(arr, 50)),
        q3=float(np.percentile(arr, 75)),
        max=float(np.max(arr)),
    )


def _cluster_items(grp: pd.DataFrame) -> list[ClusterItem]:
    top = grp.sort_values("importe", ascending=False).head(_ITEMS_PER_CLUSTER)
    return [
        ClusterItem(
            id_externo=str(row.get("id_externo", "")),
            titulo=row.get("titulo") if pd.notna(row.get("titulo")) else None,
            organo_contratacion=(
                row.get("organo_contratacion") if pd.notna(row.get("organo_contratacion")) else None
            ),
            importe=float(row["importe"]) if pd.notna(row.get("importe")) else None,
            ccaa=row.get("ccaa") if pd.notna(row.get("ccaa")) else None,
            estado=estado_label(row.get("estado")) if pd.notna(row.get("estado")) else None,
        )
        for _, row in top.iterrows()
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_clusters(filters: ClustersFilters) -> ClustersResult:
    """Cluster tenders by title similarity and summarise each cluster."""
    log.info("analytics_clusters_start", filters=filters.model_dump(exclude_none=True))
    df = _load_df()
    df = _apply_filters(df, filters)

    if df.empty or "titulo" not in df.columns:
        return ClustersResult(total=len(df))

    work = df.dropna(subset=["titulo"]).copy()
    total = len(work)
    if total < _MIN_ROWS:
        log.info("analytics_clusters_too_few", total=total)
        return ClustersResult(total=total)

    # Bound latency on very large corpora (cache absorbs cold cost otherwise).
    if total > _MAX_ROWS:
        work = work.sample(_MAX_ROWS, random_state=42).reset_index(drop=True)
        log.info("analytics_clusters_sampled", n=_MAX_ROWS, total=total)

    texts = work["titulo"].fillna("").astype(str).tolist()

    try:
        embeddings = _tfidf_embeddings(texts)
        k = _resolve_k(embeddings, filters, len(work))
        labels = _kmeans_factory(k, len(work)).fit_predict(embeddings)
    except (ValueError, RuntimeError, MemoryError) as exc:
        log.warning("analytics_clusters_failed", error=str(exc))
        return ClustersResult(total=total)

    work = work.assign(cluster_id=labels)
    label_map = _ctfidf_labels(texts, labels)

    clusters: list[ClusterEntry] = []
    for cid, grp in work.groupby("cluster_id"):
        cid_int = int(cast("SupportsInt", cid))  # cid es la etiqueta de cluster (numpy int)
        importes = grp["importe"]
        clusters.append(
            ClusterEntry(
                cluster_id=cid_int,
                label=label_map.get(cid_int, "otros"),
                n=len(grp),
                importe_medio=float(importes.mean(skipna=True) or 0),
                importe_total=float(importes.sum(skipna=True)),
                importe_box=_box(importes),
                items=_cluster_items(grp),
            )
        )

    clusters.sort(key=lambda c: c.n, reverse=True)
    log.info("analytics_clusters_done", k=len(clusters), total=total)
    return ClustersResult(
        n_clusters_detectados=len(clusters),
        total=total,
        clusters=clusters,
    )
