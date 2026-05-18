"""Tests para dashboard.faiss_index.

Cubre:
- T1a: cache hit — dos llamadas a _load_cached con mismo (path, mtime) devuelven
       la *misma* instancia (sin volver a deserializar).
- T1b: invalidación de cache — cuando el mtime cambia, _load_cached devuelve
       una instancia *distinta* (cache miss).
- T1c: FaissIndex.load_or_build con índice en disco carga correctamente.
- T1d: FaissIndex.save() persiste metadata (embedding_version, embedding_model).
"""

from __future__ import annotations

import pickle
import time
from pathlib import Path

import numpy as np
import pytest

faiss = pytest.importorskip("faiss", reason="faiss-cpu no instalado; omitiendo tests FAISS")

# Importar DESPUÉS de confirmar que faiss está disponible
from dashboard.faiss_index import FaissIndex  # noqa: E402, I001


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_index(n: int = 20, dim: int = 32, tmp_path: Path | None = None) -> FaissIndex:
    """Crea un FaissIndex mínimo para pruebas (sin embeddings reales)."""
    ids = [f"LIC-{i:04d}" for i in range(n)]
    rng = np.random.default_rng(42)
    embs = rng.standard_normal((n, dim)).astype(np.float32)
    # Normalizar para similitud coseno
    norms = np.linalg.norm(embs, axis=1, keepdims=True)
    embs = embs / np.where(norms == 0, 1, norms)
    return FaissIndex(ids=ids, embeddings=embs)


def _save_index(idx: FaissIndex, path: Path) -> Path:
    """Guarda el índice usando pickle directamente (evita clear() de Streamlit)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "embedding_version": idx.embedding_version,
        "embedding_model": idx.embedding_model,
        "created_at": "2025-01-01T00:00:00+00:00",
        "n_records": len(idx.ids),
    }
    with open(path, "wb") as f:
        pickle.dump({"ids": idx.ids, "embeddings": idx.embeddings, "metadata": metadata}, f, protocol=5)
    return path


# ---------------------------------------------------------------------------
# T1a: cache hit
# ---------------------------------------------------------------------------

def test_load_cached_cache_hit(tmp_path: Path) -> None:
    """_load_cached con mismo (path, mtime) debe devolver la misma instancia."""
    idx = _make_index()
    fpath = tmp_path / "test_index.pkl"
    _save_index(idx, fpath)

    # Limpiar cache del módulo para asegurar estado fresco
    FaissIndex._load_cached.clear()

    mtime = fpath.stat().st_mtime_ns
    first = FaissIndex._load_cached(str(fpath), mtime)
    second = FaissIndex._load_cached(str(fpath), mtime)

    # Con caché activa deben ser el mismo objeto
    assert first is second


# ---------------------------------------------------------------------------
# T1b: invalidación por mtime
# ---------------------------------------------------------------------------

def test_load_cached_cache_invalidated_on_mtime_change(tmp_path: Path) -> None:
    """Cuando el mtime cambia, _load_cached debe devolver una instancia distinta."""
    idx = _make_index()
    fpath = tmp_path / "test_index.pkl"
    _save_index(idx, fpath)

    FaissIndex._load_cached.clear()

    mtime_old = fpath.stat().st_mtime_ns
    first = FaissIndex._load_cached(str(fpath), mtime_old)

    # Esperar y re-escribir para asegurar mtime diferente
    time.sleep(0.05)
    _save_index(idx, fpath)
    mtime_new = fpath.stat().st_mtime_ns

    # En sistemas con resolución baja puede que mtime no cambie en 50 ms;
    # forzar diferencia manualmente si es necesario.
    if mtime_new == mtime_old:
        mtime_new = mtime_old + 1

    second = FaissIndex._load_cached(str(fpath), mtime_new)

    # Distinto mtime → debe ser instancia diferente
    assert first is not second


# ---------------------------------------------------------------------------
# T1c: FaissIndex.load — atributos correctos
# ---------------------------------------------------------------------------

def test_faiss_load_metadata(tmp_path: Path) -> None:
    """load() debe restaurar embedding_version y embedding_model correctamente."""
    idx = _make_index()
    idx.embedding_version = "v42"
    idx.embedding_model = "test-model"

    fpath = tmp_path / "meta_index.pkl"
    _save_index(idx, fpath)

    FaissIndex._load_cached.clear()
    loaded = FaissIndex.load(fpath)

    assert loaded.embedding_version == "v42"
    assert loaded.embedding_model == "test-model"
    assert len(loaded.ids) == len(idx.ids)
    assert loaded.embeddings.shape == idx.embeddings.shape


# ---------------------------------------------------------------------------
# T1d: FaissIndex.save persiste metadata
# ---------------------------------------------------------------------------

def test_faiss_save_metadata(tmp_path: Path) -> None:
    """save() debe persistir embedding_version y embedding_model en JSON companion."""
    idx = _make_index()
    idx.embedding_version = "v99"
    idx.embedding_model = "my-encoder"

    fpath = tmp_path / "saved_index.npz"
    saved = idx.save(fpath)

    assert saved == fpath
    # Embeddings stored in npz (no object arrays, allow_pickle=False safe)
    arr = np.load(fpath, allow_pickle=False)
    assert arr["embeddings"].shape == idx.embeddings.shape
    # ids + metadata stored in companion JSON
    import json
    meta_path = fpath.with_name("saved_index_meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["ids"] == idx.ids
    assert meta["embedding_version"] == "v99"
    assert meta["embedding_model"] == "my-encoder"
    assert meta["n_records"] == len(idx.ids)


# ---------------------------------------------------------------------------
# T1e: FaissIndex.__init__ inicializa atributos correctamente
# ---------------------------------------------------------------------------

def test_faiss_index_init_defaults() -> None:
    """Los atributos de tipado deben tener defaults tras __init__."""
    idx = _make_index()
    assert idx.embedding_version == "v1"
    assert idx.embedding_model == "default"
    assert len(idx.ids) == 20
    assert idx.embeddings.shape == (20, 32)
