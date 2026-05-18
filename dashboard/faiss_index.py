"""Índice FAISS para búsqueda semántica de licitaciones.

Construye un índice de similitud coseno sobre los embeddings de títulos y
descripciones de licitaciones, persistido en disco para evitar recalcular
en cada inicio del dashboard.

Dependencia: faiss-cpu (o faiss-gpu).
Fallback: si FAISS no está disponible, usa ``smart_match`` de embeddings.py.

Uso:
    # Construir o actualizar el índice (tras un scraping):
    python -m dashboard.faiss_index build

    # Buscar desde código:
    from dashboard.faiss_index import FaissIndex
    idx = FaissIndex.load_or_build(df)
    results = idx.search("migración SAP S/4HANA", k=10)
    # results: lista de (id_externo, score)
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from observability.logging import get_logger

if TYPE_CHECKING:
    import pandas as pd

log = get_logger(__name__)

_INDEX_PATH = Path(__file__).parents[1] / "data" / "models" / "faiss_index.npz"
_INDEX_PATH_LEGACY = Path(__file__).parents[1] / "data" / "models" / "faiss_index.pkl"
_META_SUFFIX = "_meta.json"  # companion file alongside .npz
_MIN_TEXTS = 10  # mínimo de textos para construir un índice útil

try:  # pragma: no cover - fallback when Streamlit runtime no disponible
    import streamlit as _st

    _cache_resource = _st.cache_resource
except Exception:  # pragma: no cover

    def _cache_resource(*args: Any, **kwargs: Any) -> Callable[[Any], Any]:  # type: ignore[misc]
        def _decorator(fn: Any) -> Any:
            return fn

        return _decorator


def _utc_iso() -> str:
    """ISO-8601 con tz UTC (helper local para evitar import circular)."""
    return datetime.now(UTC).isoformat()


def _faiss_available() -> bool:
    try:
        import faiss  # noqa: F401

        return True
    except ImportError:
        return False


class FaissIndex:
    """Índice de similitud coseno sobre embeddings de licitaciones."""

    def __init__(self, ids: list[str], embeddings: np.ndarray) -> None:
        """
        Args:
            ids: Lista de id_externo en el mismo orden que las filas de embeddings.
            embeddings: Array (n, dim) de embeddings normalizados.
        """
        self.ids = ids
        self.embeddings = embeddings
        self._index = self._build_faiss_index(embeddings)
        self.embedding_version: str = "v1"
        self.embedding_model: str = "default"

    # ── Construcción ──────────────────────────────────────────────────────

    @staticmethod
    def _build_faiss_index(embeddings: np.ndarray) -> object:
        """Construye un IndexFlatIP (coseno sobre vectores normalizados)."""
        import faiss

        dim = embeddings.shape[1]
        index = faiss.IndexFlatIP(dim)
        index.add(embeddings.astype(np.float32))
        return index

    @classmethod
    def build(cls, df: pd.DataFrame) -> FaissIndex:
        """Construye el índice a partir del DataFrame de licitaciones.

        Args:
            df: Debe tener columnas id_externo, titulo, descripcion.
        """
        from dashboard.embeddings import encode_texts

        df_clean = df.dropna(subset=["id_externo"]).copy()
        texts = (
            (df_clean["titulo"].fillna("") + " " + df_clean["descripcion"].fillna(""))
            .str.strip()
            .tolist()
        )
        ids = df_clean["id_externo"].tolist()

        if len(texts) < _MIN_TEXTS:
            raise ValueError(
                f"Se necesitan al menos {_MIN_TEXTS} licitaciones para construir el índice "
                f"(hay {len(texts)})."
            )

        log.info("faiss_index.encoding", n=len(texts))
        embeddings = encode_texts(texts).astype(np.float32)

        log.info("faiss_index.built", n=len(ids), dim=embeddings.shape[1])
        instance = cls(ids=ids, embeddings=embeddings)
        # Record which model + version was used to build this index
        from config import settings as _settings

        instance.embedding_model = _settings.EMBEDDING_MODEL
        instance.embedding_version = _settings.EMBEDDING_VERSION
        return instance

    # ── Búsqueda ──────────────────────────────────────────────────────────

    def search(self, query: str, k: int = 10, threshold: float = 0.4) -> list[tuple[str, float]]:
        """Busca las k licitaciones más similares a la query.

        Args:
            query: Texto de búsqueda en lenguaje natural.
            k: Número máximo de resultados.
            threshold: Similitud mínima (coseno normalizado, [0, 1]).

        Returns:
            Lista de (id_externo, score) ordenados por similitud desc.
        """
        from dashboard.embeddings import encode_texts

        q_emb = encode_texts([query]).astype(np.float32)
        k_actual = min(k, len(self.ids))
        scores, indices = self._index.search(q_emb, k_actual)  # type: ignore[attr-defined]

        results = []
        for score, idx in zip(scores[0], indices[0], strict=False):
            if idx < 0 or float(score) < threshold:
                continue
            results.append((self.ids[idx], float(score)))
        return results

    # ── Persistencia ──────────────────────────────────────────────────────

    def save(self, path: Path | None = None) -> Path:
        """Guarda el índice en disco (numpy .npz + JSON de metadata)."""
        target = path or _INDEX_PATH
        # Normalizar extensión: siempre .npz
        if target.suffix == ".pkl":
            target = target.with_suffix(".npz")
        target.parent.mkdir(parents=True, exist_ok=True)
        metadata: dict[str, Any] = {
            "ids": self.ids,
            "embedding_version": getattr(self, "embedding_version", "v1"),
            "embedding_model": getattr(self, "embedding_model", "default"),
            "created_at": _utc_iso(),
            "n_records": len(self.ids),
        }
        # Guardar sólo embeddings numéricos en .npz (allow_pickle=False seguro)
        np.savez_compressed(target, embeddings=self.embeddings)
        # ids + metadata en JSON legible y seguro
        meta_path = target.with_name(target.stem + _META_SUFFIX)
        meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        # Invalidar caché Streamlit
        try:
            self.__class__._load_cached.clear()
        except Exception:
            pass
        log.info("faiss_index.saved", path=str(target), n=len(self.ids), **metadata)
        return target

    @staticmethod
    @_cache_resource(show_spinner=False)
    def _load_cached(path_str: str, mtime_ns: int) -> FaissIndex:
        """Carga cacheada por ruta + mtime para compartir el índice entre reruns."""
        _ = mtime_ns  # parte de la key de caché para invalidar al cambiar el archivo
        p = Path(path_str)
        if p.suffix == ".npz":
            data = np.load(p, allow_pickle=False)
            embeddings: np.ndarray = data["embeddings"]
            meta_path = p.with_name(p.stem + _META_SUFFIX)
            meta: dict[str, Any] = {}
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            ids: list[str] = meta.pop("ids", [])
        else:
            # Fallback legacy pickle (read-only, never write)
            import pickle

            with open(p, "rb") as f:
                raw = pickle.load(f)  # noqa: S301
            ids = raw["ids"]
            embeddings = raw["embeddings"]
            meta = raw.get("metadata") or {}
        obj = FaissIndex(ids=ids, embeddings=embeddings)
        obj.embedding_version = meta.get("embedding_version", "v1")
        obj.embedding_model = meta.get("embedding_model", "default")
        return obj

    @classmethod
    def load(cls, path: Path | None = None) -> FaissIndex:
        """Carga el índice desde disco con caché compartida entre sesiones.

        Intenta el formato numpy (.npz) primero; si no existe, prueba el
        legacy .pkl para compatibilidad con índices previos.
        """
        target = path or _INDEX_PATH
        # Migración automática: si sólo existe el .pkl legacy, usarlo
        if not target.exists() and target.suffix == ".npz" and _INDEX_PATH_LEGACY.exists():
            target = _INDEX_PATH_LEGACY
        mtime_ns = target.stat().st_mtime_ns
        obj: FaissIndex = cls._load_cached(str(target), mtime_ns)
        log.info(
            "faiss_index.loaded",
            path=str(target),
            n=len(obj.ids),
            embedding_version=obj.embedding_version,
        )
        return obj

    @classmethod
    def is_available(cls, path: Path | None = None) -> bool:
        """True si existe un índice guardado en disco (nuevo o legacy)."""
        target = path or _INDEX_PATH
        return target.exists() or _INDEX_PATH_LEGACY.exists()

    @classmethod
    def load_or_build(cls, df: pd.DataFrame, path: Path | None = None) -> FaissIndex:
        """Carga el índice si existe; si no, lo construye y guarda.

        Preferir ``build()`` explícito en producción para controlar cuándo
        se reconstruye. Este método es conveniente para desarrollo y tests.
        """
        target = path or _INDEX_PATH
        if target.exists():
            try:
                return cls.load(target)
            except Exception as e:
                log.warning("faiss_index.load_error", error=str(e), path=str(target))

        idx = cls.build(df)
        idx.save(target)
        return idx


# ── API de alto nivel (con fallback automático) ───────────────────────────────


def search_similar(
    query: str,
    df: pd.DataFrame,
    k: int = 10,
    threshold: float = 0.4,
) -> list[tuple[str, float]]:
    """Busca licitaciones similares usando FAISS o fallback a smart_match.

    Args:
        query: Texto de búsqueda.
        df: DataFrame completo de licitaciones (para construir índice si hace falta).
        k: Número máximo de resultados.
        threshold: Similitud mínima.

    Returns:
        Lista de (id_externo, score).
    """
    if _faiss_available():
        try:
            idx = FaissIndex.load_or_build(df)
            return idx.search(query, k=k, threshold=threshold)
        except Exception as e:
            log.warning("faiss_index.fallback", error=str(e))

    # Fallback: smart_match sobre títulos
    from dashboard.embeddings import smart_match

    corpus = (df["titulo"].fillna("") + " " + df["descripcion"].fillna("")).tolist()
    ids = df["id_externo"].tolist()
    matches = smart_match(query, corpus, threshold=threshold)[:k]
    return [(ids[i], score) for i, score in matches]


def rebuild_index(df: pd.DataFrame) -> FaissIndex | None:
    """Reconstruye y guarda el índice FAISS desde cero.

    Diseñado para llamarse al final del pipeline de scraping.
    Si FAISS no está disponible o los embeddings no están instalados,
    loguea un aviso y retorna None sin propagar la excepción.
    """
    if not _faiss_available():
        log.info("faiss_index.skip_rebuild", reason="faiss not installed")
        return None
    try:
        from dashboard.embeddings import embeddings_available

        if not embeddings_available():
            log.info("faiss_index.skip_rebuild", reason="sentence-transformers not installed")
            return None
        idx = FaissIndex.build(df)
        idx.save()
        return idx
    except Exception as e:
        log.warning("faiss_index.rebuild_error", error=str(e))
        return None


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd == "build":
        import pandas as pd

        from db.database import connect, init_db

        print("Construyendo índice FAISS desde la BD...")
        init_db()
        with connect() as c:
            cursor = c.execute("SELECT id_externo, titulo, descripcion FROM licitaciones")
            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description]
        df = pd.DataFrame(rows, columns=cols)
        idx = FaissIndex.build(df)
        path = idx.save()
        print(f"Índice guardado: {path} ({len(idx.ids)} licitaciones)")
    elif cmd == "info":
        if FaissIndex.is_available():
            idx = FaissIndex.load()
            print(f"Índice disponible: {_INDEX_PATH} ({len(idx.ids)} licitaciones)")
        else:
            print("No hay índice. Ejecuta: python -m dashboard.faiss_index build")
    else:
        print(f"Comando desconocido: {cmd}. Usa 'build' o 'info'.")
        sys.exit(1)
