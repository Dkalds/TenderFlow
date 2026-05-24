"""Tests para dashboard.faiss_index.

Cubre:
- T1a: cache hit — dos llamadas a _load_cached con mismo (path, mtime) devuelven
       la *misma* instancia (sin volver a deserializar).
- T1b: invalidación de cache — cuando el mtime cambia, _load_cached devuelve
       una instancia *distinta* (cache miss).
- T1c: FaissIndex.load con índice en disco carga correctamente.
- T1d: FaissIndex.save() persiste metadata (embedding_version, embedding_model).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

faiss = pytest.importorskip("faiss", reason="faiss-cpu no instalado; omitiendo tests FAISS")

# Importar DESPUÉS de confirmar que faiss está disponible
from dashboard.faiss_index import FaissIndex  # noqa: I001


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
    """Guarda el índice en formato .npz usando FaissIndex.save()."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return idx.save(path)


# ---------------------------------------------------------------------------
# T1a: cache hit
# ---------------------------------------------------------------------------


def test_load_cached_cache_hit(tmp_path: Path) -> None:
    """_load_cached con mismo (path, mtime) debe devolver la misma instancia."""
    idx = _make_index()
    fpath = tmp_path / "test_index.npz"
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
    fpath = tmp_path / "test_index.npz"
    _save_index(idx, fpath)

    FaissIndex._load_cached.clear()

    mtime_old = fpath.stat().st_mtime_ns
    first = FaissIndex._load_cached(str(fpath), mtime_old)

    # Re-escribir para asegurar mtime diferente; forzar diferencia si la
    # resolución del filesystem no cambia en tiempo real.
    _save_index(idx, fpath)
    mtime_new = fpath.stat().st_mtime_ns
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

    fpath = tmp_path / "meta_index.npz"
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


# ---------------------------------------------------------------------------
# T2a: FaissIndex.update() — actualización incremental
# ---------------------------------------------------------------------------


def test_update_adds_new_entries() -> None:
    """update() añade IDs nuevos al índice sin duplicar los existentes."""
    from unittest.mock import patch

    import pandas as pd

    idx = _make_index(n=10, dim=32)
    n_original = len(idx.ids)

    # 5 IDs nuevos
    new_ids = [f"NEW-{i:04d}" for i in range(5)]
    df_new = pd.DataFrame(
        {
            "id_externo": new_ids,
            "titulo": [f"Nuevo {i}" for i in range(5)],
            "descripcion": ["desc"] * 5,
        }
    )

    rng = np.random.default_rng(99)
    fake_embs = rng.standard_normal((5, 32)).astype(np.float32)
    norms = np.linalg.norm(fake_embs, axis=1, keepdims=True)
    fake_embs = fake_embs / norms

    with patch("dashboard.embeddings.encode_texts", return_value=fake_embs):
        added = idx.update(df_new)

    assert added == 5
    assert len(idx.ids) == n_original + 5
    assert all(nid in idx.ids for nid in new_ids)


def test_update_skips_existing_ids() -> None:
    """update() no duplica IDs que ya están en el índice."""

    import pandas as pd

    idx = _make_index(n=10, dim=32)

    # DataFrame con IDs ya existentes
    existing_ids = idx.ids[:3]
    df_existing = pd.DataFrame(
        {
            "id_externo": existing_ids,
            "titulo": ["Titulo"] * 3,
            "descripcion": ["desc"] * 3,
        }
    )

    added = idx.update(df_existing)
    assert added == 0
    assert len(idx.ids) == 10  # sin cambios


def test_update_no_new_entries_returns_zero() -> None:
    """update() con DataFrame vacío retorna 0."""
    import pandas as pd

    idx = _make_index(n=10, dim=32)
    df_empty = pd.DataFrame({"id_externo": [], "titulo": [], "descripcion": []})
    added = idx.update(df_empty)
    assert added == 0


def test_update_embeddings_shape_consistent() -> None:
    """Tras update(), la shape de embeddings es consistente con len(ids)."""
    from unittest.mock import patch

    import pandas as pd

    idx = _make_index(n=10, dim=32)
    new_ids = ["EXTRA-001", "EXTRA-002"]
    df_new = pd.DataFrame(
        {
            "id_externo": new_ids,
            "titulo": ["T1", "T2"],
            "descripcion": ["D1", "D2"],
        }
    )

    rng = np.random.default_rng(7)
    fake_embs = rng.standard_normal((2, 32)).astype(np.float32)
    fake_embs = fake_embs / np.linalg.norm(fake_embs, axis=1, keepdims=True)

    with patch("dashboard.embeddings.encode_texts", return_value=fake_embs):
        idx.update(df_new)

    assert idx.embeddings.shape[0] == len(idx.ids)
    assert idx.embeddings.shape[1] == 32
