"""Tests para services/faiss_index.py con faiss falso inyectado via sys.modules."""

from __future__ import annotations

import sys
import types

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def fake_faiss(monkeypatch):
    """Inyecta un módulo faiss falso con IndexFlatIP que usa numpy."""
    mod = types.ModuleType("faiss")

    class IndexFlatIP:
        def __init__(self, dim: int) -> None:
            self.dim = dim
            self.d = dim
            self.vectors: list[np.ndarray] = []
            self.ntotal = 0

        def add(self, vecs: np.ndarray) -> None:
            for v in vecs:
                self.vectors.append(v.copy())
            self.ntotal = len(self.vectors)

        def search(self, query: np.ndarray, k: int):
            if not self.vectors:
                empty_scores = np.zeros((1, 0), dtype=np.float32)
                empty_idx = np.full((1, 0), -1, dtype=np.int64)
                return empty_scores, empty_idx
            mat = np.array(self.vectors, dtype=np.float32)  # (N, dim)
            scores = (mat @ query.T).flatten()  # (N,)
            k_actual = min(k, len(scores))
            top_idx = np.argsort(scores)[::-1][:k_actual]
            return scores[top_idx].reshape(1, -1), top_idx.astype(np.int64).reshape(1, -1)

    mod.IndexFlatIP = IndexFlatIP  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faiss", mod)
    # Asegurar que el módulo se reimporta con el fake cuando ya está cargado
    if "services.faiss_index" in sys.modules:
        del sys.modules["services.faiss_index"]
    yield mod


@pytest.fixture()
def encode_stub(monkeypatch):
    """Vectores deterministas (norma 1) para N textos — sin sentence-transformers."""

    def _encode(texts: list[str]) -> np.ndarray:
        dim = 32
        vecs = []
        for i in range(len(texts)):
            v = np.zeros(dim, dtype=np.float32)
            v[i % dim] = 1.0
            vecs.append(v)
        return np.array(vecs, dtype=np.float32)

    monkeypatch.setattr("services.embeddings.encode_texts", _encode)
    return _encode


@pytest.fixture()
def sample_df():
    """DataFrame mínimo con 10 filas para satisfacer _MIN_TEXTS."""
    import pandas as pd

    return pd.DataFrame(
        {
            "id_externo": [f"X{i:03d}" for i in range(10)],
            "titulo": [f"SAP FI implantacion modulo {i}" for i in range(10)],
            "descripcion": [f"Proyecto erp sap {i} mantenimiento" for i in range(10)],
        }
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_index(tmp_path, monkeypatch, df, encode_stub_fn):
    """Construye un FaissIndex con ruta temporal y encode stub activos."""
    from pathlib import Path

    import services.faiss_index as fi_mod

    index_path = tmp_path / "idx.npz"
    monkeypatch.setattr(fi_mod, "_INDEX_PATH", Path(index_path))
    fi_mod.FaissIndex._load_cached.cache_clear()
    idx = fi_mod.FaissIndex.build(df)
    return idx, fi_mod, Path(index_path)


# ---------------------------------------------------------------------------
# FaissIndex.build
# ---------------------------------------------------------------------------


def test_faiss_construye_desde_dataframe(tmp_path, monkeypatch, sample_df, encode_stub):
    """FaissIndex.build con 10 filas (>= _MIN_TEXTS) construye el índice."""
    from pathlib import Path

    import services.faiss_index as fi_mod

    monkeypatch.setattr(fi_mod, "_INDEX_PATH", Path(tmp_path / "idx.npz"))
    fi_mod.FaissIndex._load_cached.cache_clear()

    idx = fi_mod.FaissIndex.build(sample_df)

    assert len(idx.ids) == 10
    assert idx.embeddings.shape[0] == 10
    assert idx._index is not None


def test_faiss_build_menos_que_min_texts(tmp_path, monkeypatch, encode_stub):
    """FaissIndex.build con < _MIN_TEXTS filas lanza ValueError."""
    from pathlib import Path

    import pandas as pd

    import services.faiss_index as fi_mod

    monkeypatch.setattr(fi_mod, "_INDEX_PATH", Path(tmp_path / "idx.npz"))
    fi_mod.FaissIndex._load_cached.cache_clear()

    df_small = pd.DataFrame(
        {
            "id_externo": ["A001", "A002", "A003"],
            "titulo": ["SAP uno", "SAP dos", "SAP tres"],
            "descripcion": ["desc1", "desc2", "desc3"],
        }
    )

    with pytest.raises(ValueError, match=r"al menos \d+"):
        fi_mod.FaissIndex.build(df_small)


# ---------------------------------------------------------------------------
# FaissIndex.search
# ---------------------------------------------------------------------------


def test_faiss_search_devuelve_ids(tmp_path, monkeypatch, sample_df, encode_stub):
    """search devuelve lista de (id_externo, score) para query con matches."""
    from pathlib import Path

    import services.faiss_index as fi_mod

    monkeypatch.setattr(fi_mod, "_INDEX_PATH", Path(tmp_path / "idx.npz"))
    fi_mod.FaissIndex._load_cached.cache_clear()

    idx = fi_mod.FaissIndex.build(sample_df)
    results = idx.search("SAP FI implantacion", k=5, threshold=0.0)

    assert isinstance(results, list)
    assert len(results) > 0
    for id_ext, score in results:
        assert isinstance(id_ext, str)
        assert isinstance(score, float)


def test_faiss_search_threshold_filtra(tmp_path, monkeypatch, sample_df, encode_stub):
    """search con threshold muy alto filtra todos los resultados."""
    from pathlib import Path

    import services.faiss_index as fi_mod

    monkeypatch.setattr(fi_mod, "_INDEX_PATH", Path(tmp_path / "idx.npz"))
    fi_mod.FaissIndex._load_cached.cache_clear()

    idx = fi_mod.FaissIndex.build(sample_df)
    # threshold=2.0 es imposible para similitud coseno (max=1.0)
    results = idx.search("SAP modulo", k=5, threshold=2.0)
    assert results == []


# ---------------------------------------------------------------------------
# FaissIndex.load_or_build / save
# ---------------------------------------------------------------------------


def test_faiss_guarda_y_crea_npz(tmp_path, monkeypatch, sample_df, encode_stub):
    """build + save crea el archivo .npz en disco."""
    from pathlib import Path

    import services.faiss_index as fi_mod

    index_path = Path(tmp_path / "idx.npz")
    monkeypatch.setattr(fi_mod, "_INDEX_PATH", index_path)
    fi_mod.FaissIndex._load_cached.cache_clear()

    idx = fi_mod.FaissIndex.build(sample_df)
    saved = idx.save(index_path)

    assert saved == index_path
    assert index_path.exists()


def test_faiss_load_or_build_sin_archivo(tmp_path, monkeypatch, sample_df, encode_stub):
    """load_or_build cuando no existe archivo construye el índice y lo guarda."""
    from pathlib import Path

    import services.faiss_index as fi_mod

    index_path = Path(tmp_path / "idx.npz")
    monkeypatch.setattr(fi_mod, "_INDEX_PATH", index_path)
    fi_mod.FaissIndex._load_cached.cache_clear()

    assert not index_path.exists()
    idx = fi_mod.FaissIndex.load_or_build(sample_df, path=index_path)

    assert index_path.exists()
    assert len(idx.ids) == 10


def test_faiss_load_o_build_fresco_no_recodifica(tmp_path, monkeypatch, sample_df):
    """load_or_build con índice fresco usa load() sin llamar a encode_texts."""
    from pathlib import Path

    import services.faiss_index as fi_mod

    index_path = Path(tmp_path / "idx.npz")
    monkeypatch.setattr(fi_mod, "_INDEX_PATH", index_path)
    fi_mod.FaissIndex._load_cached.cache_clear()

    # Primera llamada: build real con encode stub
    encode_call_count = 0

    def _counting_encode(texts: list[str]) -> np.ndarray:
        nonlocal encode_call_count
        encode_call_count += 1
        dim = 32
        vecs = []
        for i in range(len(texts)):
            v = np.zeros(dim, dtype=np.float32)
            v[i % dim] = 1.0
            vecs.append(v)
        return np.array(vecs, dtype=np.float32)

    monkeypatch.setattr("services.embeddings.encode_texts", _counting_encode)

    # Asegurar que el centinela de stale no existe
    monkeypatch.setattr(fi_mod, "_is_index_stale", lambda path: False)

    idx1 = fi_mod.FaissIndex.load_or_build(sample_df, path=index_path)
    calls_after_build = encode_call_count

    fi_mod.FaissIndex._load_cached.cache_clear()

    # Segunda llamada: debe cargar del disco sin recodificar
    idx2 = fi_mod.FaissIndex.load_or_build(sample_df, path=index_path)
    calls_after_reload = encode_call_count

    assert calls_after_build > 0  # la primera sí codificó
    assert calls_after_reload == calls_after_build  # la segunda no añadió llamadas


# ---------------------------------------------------------------------------
# _is_index_stale
# ---------------------------------------------------------------------------


def test_faiss_is_index_stale_sin_signal(tmp_path):
    """_is_index_stale devuelve False cuando no existe el archivo centinela."""
    import services.faiss_index as fi_mod

    fake_index = tmp_path / "idx.npz"
    fake_index.write_bytes(b"")  # crear archivo vacío para que exista mtime

    result = fi_mod._is_index_stale(fake_index)
    # Sin centinela debe devolver False (no hay señal de stale)
    assert result is False


# ---------------------------------------------------------------------------
# rebuild_index sin faiss
# ---------------------------------------------------------------------------


def test_faiss_rebuild_sin_faiss_devuelve_none(tmp_path, monkeypatch, sample_df):
    """rebuild_index devuelve None cuando faiss no está disponible."""
    import services.faiss_index as fi_mod

    # Hacer que _faiss_available() devuelva False
    monkeypatch.setattr(fi_mod, "_faiss_available", lambda: False)

    result = fi_mod.rebuild_index(sample_df)
    assert result is None
