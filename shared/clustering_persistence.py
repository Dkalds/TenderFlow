"""Persistencia de modelos de clustering (F2).

Guarda y carga ``KMeans``/``MiniBatchKMeans`` ajustados + sus centroides
en ``data/models/clustering/`` con un manifiesto JSON paralelo. Registra
metadata en :mod:`db.model_registry` para auditoría y A/B testing.

Uso típico::

    from shared.clustering_persistence import save_clustering, load_clustering

    info = save_clustering(km, vectorizer=vec, dataset_hash="...", metrics={"silhouette": 0.42})
    km_loaded, manifest = load_clustering(info["version"])
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from db.model_registry import get_active, register_version
from observability.logging import get_logger

log = get_logger(__name__)

_DEFAULT_DIR = Path("data/models/clustering")
_MODEL_NAME = "clustering_kmeans"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def save_clustering(
    model: Any,
    *,
    vectorizer: Any | None = None,
    dataset_hash: str,
    metrics: dict[str, float] | None = None,
    n_samples: int | None = None,
    base_dir: Path | str = _DEFAULT_DIR,
    activate: bool = True,
) -> dict[str, Any]:
    """Persiste el modelo + centroides + manifiesto y registra la versión.

    Devuelve el manifiesto (incluye ``version``, ``path``, ``sha256``).
    """
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    pkg_path = base / f"{_MODEL_NAME}_{ts}.joblib"
    centroids_path = base / f"{_MODEL_NAME}_{ts}_centroids.npy"

    bundle = {"model": model, "vectorizer": vectorizer}
    joblib.dump(bundle, pkg_path, compress=3)

    centroids = getattr(model, "cluster_centers_", None)
    if centroids is not None:
        np.save(centroids_path, np.asarray(centroids, dtype=np.float32))

    sha = _sha256_file(pkg_path)
    manifest = {
        "model_name": _MODEL_NAME,
        "created_at": datetime.now(UTC).isoformat(),
        "path": str(pkg_path),
        "centroids_path": str(centroids_path) if centroids is not None else None,
        "sha256": sha,
        "dataset_hash": dataset_hash,
        "metrics": metrics or {},
        "n_samples": n_samples,
        "n_clusters": getattr(model, "n_clusters", None),
        "algorithm": type(model).__name__,
    }
    manifest_path = pkg_path.with_suffix(".json")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    version = register_version(
        name=_MODEL_NAME,
        path=str(pkg_path),
        sha256=sha,
        metrics=metrics,
        n_samples=n_samples,
        notes=f"algo={manifest['algorithm']} k={manifest['n_clusters']}",
        activate=activate,
    )
    manifest["version"] = version
    log.info("clustering_saved", version=version, path=str(pkg_path), sha256=sha[:12])
    return manifest


def load_clustering(version: int | None = None) -> tuple[Any | None, dict[str, Any] | None]:
    """Carga el modelo activo (o una versión concreta) + su manifiesto.

    Devuelve ``(None, None)`` si no hay versión registrada o el fichero falta.
    """
    active = get_active(_MODEL_NAME)
    if active is None:
        return None, None
    path = Path(active["path"])
    if not path.is_file():
        log.warning("clustering_load_missing_file", path=str(path))
        return None, active
    try:
        bundle = joblib.load(path)
    except (OSError, ValueError, EOFError) as exc:
        log.warning("clustering_load_failed", path=str(path), error=str(exc))
        return None, active
    return bundle, active


__all__ = ["load_clustering", "save_clustering"]
