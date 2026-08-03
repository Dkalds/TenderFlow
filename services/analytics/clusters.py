"""Clusters analytics — real semantic clustering for the API layer.

Server-side implementation of the pure sklearn clustering logic in
``services.clustering_engine`` (KMeans / MiniBatchKMeans over TF-IDF
embeddings with c-TF-IDF keyword labels). Returns per-cluster summaries,
importe box-plot statistics and a bounded sample of tenders for drill-down.

ADR-023 (excepción justificada): el clustering en sí NO es expresable en SQL,
así que este módulo sigue en pandas/sklearn — pero sobre la proyección
ACOTADA ``AggregateRepository.clustering_universe`` (7 columnas, filtros en el
``WHERE`` y tope de ``_MAX_ROWS`` filas recientes), no sobre la tabla
completa. Hasta 2026-08 cargaba el full-table cacheado — bloqueado en Render
por el cortacircuitos, que dejaba este endpoint vacío en producción.

sklearn/scipy (~60 MB RSS) are imported lazily inside the functions that
need them rather than at module level, since this module is loaded
unconditionally by ``api/routes/analytics.py`` and the clusters endpoint
is rarely used — most API processes never pay that cost.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, SupportsInt, cast

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from db.repositories.aggregates import AggregateRepository, LicitacionesFilters
from observability.logging import get_logger
from services.classification import cpv_label, estado_label

if TYPE_CHECKING:
    # Solo para type hints — el import real es lazy (ver docstring del modulo).
    from sklearn.cluster import KMeans, MiniBatchKMeans

log = get_logger(__name__)

_repo = AggregateRepository()

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
    cpv_dominante: str | None = None
    organo_dominante: str | None = None
    importe_box: ImporteBox | None = None
    items: list[ClusterItem] = Field(default_factory=list)


class ClustersResult(BaseModel):
    """Combined clusters response."""

    n_clusters_detectados: int = 0
    total: int = 0
    # Calidad de la partición: silhouette medio [-1, 1] (mayor = clusters mejor
    # separados). None si no calculable (k<2 o corpus degenerado).
    silhouette: float | None = None
    clusters: list[ClusterEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Pure clustering helpers shared with services.clustering_engine
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
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.preprocessing import normalize

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
    from sklearn.cluster import KMeans, MiniBatchKMeans

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
    from sklearn.metrics import silhouette_score

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
    from sklearn.feature_extraction.text import TfidfVectorizer

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


def _to_repo_filters(filters: ClustersFilters) -> LicitacionesFilters:
    return LicitacionesFilters(
        fecha_desde=filters.fecha_desde.isoformat() if filters.fecha_desde else None,
        fecha_hasta=filters.fecha_hasta.isoformat() if filters.fecha_hasta else None,
        ccaa=filters.ccaa,
    )


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


def _dominant(grp: pd.DataFrame, col: str) -> str | None:
    """Valor más frecuente (moda) de una columna en el cluster, o None."""
    if col not in grp.columns:
        return None
    vals = grp[col].dropna().astype(str)
    vals = vals[vals.str.strip() != ""]
    if vals.empty:
        return None
    mode = vals.mode()
    return str(mode.iloc[0]) if not mode.empty else None


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
    # Proyección acotada (7 columnas, LIMIT _MAX_ROWS filas recientes); el
    # recorte determinista sustituye al sample aleatorio del camino full-table.
    rows, total = _repo.clustering_universe(_to_repo_filters(filters), max_rows=_MAX_ROWS)
    if total < _MIN_ROWS:
        log.info("analytics_clusters_too_few", total=total)
        return ClustersResult(total=total)

    work = pd.DataFrame(rows)
    work = work.assign(importe=pd.to_numeric(work["importe"], errors="coerce"))
    if total > len(work):
        log.info("analytics_clusters_sampled", n=len(work), total=total)

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

    # Calidad de la partición (guía para elegir K). Acotado con sample_size.
    from sklearn.metrics import silhouette_score

    silhouette: float | None
    try:
        silhouette = float(
            silhouette_score(embeddings, labels, sample_size=min(1000, len(work)), random_state=42)
        )
    except ValueError:
        silhouette = None

    clusters: list[ClusterEntry] = []
    for cid, grp in work.groupby("cluster_id"):
        cid_int = int(cast("SupportsInt", cid))  # cid es la etiqueta de cluster (numpy int)
        importes = grp["importe"]
        cpv_code = _dominant(grp, "cpv")
        clusters.append(
            ClusterEntry(
                cluster_id=cid_int,
                label=label_map.get(cid_int, "otros"),
                n=len(grp),
                importe_medio=float(importes.mean(skipna=True) or 0),
                importe_total=float(importes.sum(skipna=True)),
                cpv_dominante=cpv_label(cpv_code) if cpv_code else None,
                organo_dominante=_dominant(grp, "organo_contratacion"),
                importe_box=_box(importes),
                items=_cluster_items(grp),
            )
        )

    clusters.sort(key=lambda c: c.n, reverse=True)
    log.info("analytics_clusters_done", k=len(clusters), total=total, silhouette=silhouette)
    return ClustersResult(
        n_clusters_detectados=len(clusters),
        total=total,
        silhouette=silhouette,
        clusters=clusters,
    )
