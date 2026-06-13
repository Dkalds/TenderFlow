"""Índice FAISS para búsqueda semántica de licitaciones.

Construye un índice de similitud coseno sobre los embeddings de títulos y
descripciones de licitaciones, persistido en disco para evitar recalcular
en cada inicio.

Dependencia: faiss-cpu (o faiss-gpu).
Fallback: si FAISS no está disponible, usa ``smart_match`` de embeddings.py.

**Actualizaciones incrementales**:
En lugar de reconstruir el índice completo en cada ingesta, ``update()``
añade solo los vectores nuevos/modificados al índice existente. La
reconstrucción completa sigue disponible como ``build()`` y se ejecuta
automáticamente si el índice no existe o si se detecta que más del
``_FULL_REBUILD_THRESHOLD`` de los IDs están desactualizados.

Uso:
    # Construir o actualizar el índice (tras un scraping):
    python -m services.faiss_index build

    # Buscar desde código:
    from services.faiss_index import FaissIndex
    idx = FaissIndex.load_or_build(df)
    results = idx.search("migración SAP S/4HANA", k=10)
    # results: lista de (id_externo, score)
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from filelock import FileLock

from observability.logging import get_logger

if TYPE_CHECKING:
    import pandas as pd

log = get_logger(__name__)

_INDEX_PATH = Path(__file__).parents[1] / "data" / "models" / "faiss_index.npz"
_INDEX_LOCK_PATH = _INDEX_PATH.with_suffix(".lock")  # filelock para rebuild concurrente
_META_SUFFIX = "_meta.json"  # companion file alongside .npz
_MIN_TEXTS = 10  # mínimo de textos para construir un índice útil
# Si más del 20% de los IDs son nuevos/modificados, reconstruir completo
_FULL_REBUILD_THRESHOLD = 0.20


def _utc_iso() -> str:
    """ISO-8601 con tz UTC (helper local para evitar import circular)."""
    return datetime.now(UTC).isoformat()


def _is_index_stale(index_path: Path) -> bool:
    """True si el archivo centinela de invalidación es más reciente que el índice.

    Compara el mtime del archivo ``.cache_invalidation`` (escrito por el
    scraper) con el mtime del índice FAISS. Si el centinela es más reciente,
    el índice está desactualizado y debe reconstruirse.
    Si no existe el centinela (nunca hubo ingesta) devuelve False.
    """
    try:
        from shared.cache_signal import _signal_path

        signal = _signal_path()
        if not signal.exists():
            return False
        return signal.stat().st_mtime > index_path.stat().st_mtime
    except Exception:
        return False


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
        from services.embeddings import encode_texts

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

    def update(self, df_new: pd.DataFrame) -> int:
        """Añade entradas nuevas/modificadas al índice existente sin reconstruirlo.

        Compara los IDs de ``df_new`` con los IDs ya indexados. Solo encodea y
        añade los IDs que no están en el índice actual. Los IDs modificados
        (que ya existen) no se actualizan en esta llamada — para actualizar
        embeddings de entradas existentes, usar ``build()``.

        Si la proporción de IDs nuevos supera ``_FULL_REBUILD_THRESHOLD``,
        lanza una advertencia sugiriendo una reconstrucción completa.

        Args:
            df_new: DataFrame con columnas id_externo, titulo, descripcion.
                    Puede incluir entradas ya indexadas (se filtrarán).

        Returns:
            Número de entradas añadidas al índice.
        """
        from services.embeddings import encode_texts

        existing_ids = set(self.ids)
        df_clean = df_new.dropna(subset=["id_externo"]).copy()
        df_add = df_clean[~df_clean["id_externo"].isin(existing_ids)]

        if df_add.empty:
            log.debug("faiss_index.update_no_new_entries")
            return 0

        n_new = len(df_add)
        n_total = len(existing_ids)
        ratio = n_new / max(n_total, 1)

        if ratio > _FULL_REBUILD_THRESHOLD:
            log.warning(
                "faiss_index.update_large_batch",
                n_new=n_new,
                n_existing=n_total,
                ratio=round(ratio, 2),
                hint="Considera hacer una reconstrucción completa con FaissIndex.build()",
            )

        texts = (
            (df_add["titulo"].fillna("") + " " + df_add["descripcion"].fillna(""))
            .str.strip()
            .tolist()
        )
        new_ids = df_add["id_externo"].tolist()

        log.info("faiss_index.update_encoding", n=len(texts))
        new_embeddings = encode_texts(texts).astype(np.float32)

        # Añadir al índice FAISS existente (IndexFlatIP soporta add() incremental)
        self._index.add(new_embeddings)  # type: ignore[attr-defined]

        # Actualizar listas internas
        self.ids = self.ids + new_ids
        self.embeddings = np.vstack([self.embeddings, new_embeddings])

        log.info("faiss_index.update_done", added=n_new, total=len(self.ids))
        return n_new

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
        from services.embeddings import encode_texts

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
        """Guarda el índice en disco (numpy .npz + JSON de metadata).

        Usa escritura atómica (write-to-tmp + os.replace) y un FileLock para
        prevenir condiciones de carrera cuando múltiples procesos reconstruyen
        el índice simultáneamente.
        """
        target = path or _INDEX_PATH
        lock_path = target.with_suffix(".lock")
        target.parent.mkdir(parents=True, exist_ok=True)
        metadata: dict[str, Any] = {
            "ids": self.ids,
            "embedding_version": getattr(self, "embedding_version", "v1"),
            "embedding_model": getattr(self, "embedding_model", "default"),
            "created_at": _utc_iso(),
            "n_records": len(self.ids),
        }

        with FileLock(str(lock_path), timeout=120):
            # Escritura atómica: escribir a .tmp y luego renombrar.
            # np.savez_compressed añade ".npz" automáticamente si el path no
            # termina en ".npz", así que usamos un directorio temporal explícito.
            import tempfile

            with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".npz", delete=False) as tf:
                tmp_npz = Path(tf.name)
            np.savez_compressed(str(tmp_npz.with_suffix("")), embeddings=self.embeddings)
            os.replace(tmp_npz, target)

            # ids + metadata en JSON legible y seguro
            meta_path = target.with_name(target.stem + _META_SUFFIX)
            tmp_meta = meta_path.with_suffix(".json.tmp")
            tmp_meta.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(tmp_meta, meta_path)

        # Invalidar caché en memoria
        try:
            self.__class__._load_cached.cache_clear()
        except Exception:
            pass
        log.info("faiss_index.saved", path=str(target), n=len(self.ids), **metadata)
        return target

    @staticmethod
    @lru_cache(maxsize=4)
    def _load_cached(path_str: str, mtime_ns: int) -> FaissIndex:
        """Carga cacheada por ruta + mtime para compartir el índice entre reruns."""
        _ = mtime_ns  # parte de la key de caché para invalidar al cambiar el archivo
        p = Path(path_str)
        if p.suffix != ".npz":
            raise ValueError(
                f"Formato de índice no soportado: '{p.suffix}'. "
                "Solo se admite el formato .npz. "
                "Si tienes un índice legacy .pkl, ejecútalo a través de: "
                "python -m services.faiss_index build"
            )
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
        obj = FaissIndex(ids=ids, embeddings=embeddings)
        obj.embedding_version = meta.get("embedding_version", "v1")
        obj.embedding_model = meta.get("embedding_model", "default")
        return obj

    @classmethod
    def load(cls, path: Path | None = None) -> FaissIndex:
        """Carga el índice desde disco con caché compartida entre sesiones.

        Solo admite el formato numpy (.npz). El formato legacy .pkl fue
        eliminado en 2026-05 por riesgo de ejecución arbitraria de código.
        Si solo tienes un .pkl, reconstruye el índice con:
            python -m services.faiss_index build
        """
        target = path or _INDEX_PATH
        if not target.exists():
            raise FileNotFoundError(
                f"No se encontró el índice FAISS en '{target}'. "
                "Genera uno con: python -m services.faiss_index build"
            )
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
        """True si existe un índice guardado en disco (formato .npz)."""
        target = path or _INDEX_PATH
        return target.exists()

    @classmethod
    def load_or_build(cls, df: pd.DataFrame, path: Path | None = None) -> FaissIndex:
        """Carga el índice si existe y no está obsoleto; si no, lo construye.

        La obsolescencia se detecta comparando el mtime del archivo centinela
        ``.cache_invalidation`` (escrito por el scraper tras cada ingesta) con
        el mtime del índice FAISS.

        **Estrategia de actualización**:
        - Si el índice no existe → ``build()`` completo.
        - Si el índice existe y está stale y hay pocos IDs nuevos (≤ 20%) →
          ``update()`` incremental (más rápido).
        - Si el índice existe y está stale y hay muchos IDs nuevos (> 20%) →
          ``build()`` completo.
        - Si el índice existe y no está stale → ``load()`` directo.

        Preferir ``build()`` explícito en producción para controlar cuándo
        se reconstruye. Este método es conveniente para desarrollo y tests.
        """
        target = path or _INDEX_PATH
        if target.exists():
            try:
                stale = _is_index_stale(target)
                if not stale:
                    return cls.load(target)

                # Índice stale — intentar actualización incremental primero
                log.info("faiss_index.stale_detected", path=str(target))
                existing = cls.load(target)
                existing_ids = set(existing.ids)
                df_clean = df.dropna(subset=["id_externo"])
                new_ids = set(df_clean["id_externo"].tolist()) - existing_ids
                ratio = len(new_ids) / max(len(existing_ids), 1)

                if ratio <= _FULL_REBUILD_THRESHOLD and new_ids:
                    # Pocos IDs nuevos: actualización incremental
                    log.info(
                        "faiss_index.incremental_update",
                        n_new=len(new_ids),
                        ratio=round(ratio, 2),
                    )
                    df_new_only = df_clean[df_clean["id_externo"].isin(new_ids)]
                    added = existing.update(df_new_only)
                    if added > 0:
                        existing.save(target)
                    return existing
                else:
                    # Muchos IDs nuevos o ninguno nuevo: reconstrucción completa
                    log.info(
                        "faiss_index.full_rebuild",
                        n_new=len(new_ids),
                        ratio=round(ratio, 2),
                    )
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
    from services.embeddings import smart_match

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
    import time

    from observability.runtime_metrics import faiss_rebuild_duration_seconds, faiss_rebuild_total

    if not _faiss_available():
        log.info("faiss_index.skip_rebuild", reason="faiss not installed")
        return None
    started = time.monotonic()
    try:
        from services.embeddings import embeddings_available

        if not embeddings_available():
            log.info("faiss_index.skip_rebuild", reason="sentence-transformers not installed")
            return None
        idx = FaissIndex.build(df)
        idx.save()
        elapsed = time.monotonic() - started
        faiss_rebuild_total.labels(status="success").inc()
        faiss_rebuild_duration_seconds.observe(elapsed)
        return idx
    except Exception as e:
        elapsed = time.monotonic() - started
        log.warning("faiss_index.rebuild_error", error=str(e))
        faiss_rebuild_total.labels(status="error").inc()
        faiss_rebuild_duration_seconds.observe(elapsed)
        return None


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd == "build":
        import pandas as pd

        from services.licitaciones import load_licitaciones_for_index

        print("Construyendo índice FAISS desde la BD...")
        df = load_licitaciones_for_index()
        idx = FaissIndex.build(df)
        path = idx.save()
        print(f"Índice guardado: {path} ({len(idx.ids)} licitaciones)")
    elif cmd == "info":
        if FaissIndex.is_available():
            idx = FaissIndex.load()
            print(f"Índice disponible: {_INDEX_PATH} ({len(idx.ids)} licitaciones)")
        else:
            print("No hay índice. Ejecuta: python -m services.faiss_index build")
    else:
        print(f"Comando desconocido: {cmd}. Usa 'build' o 'info'.")
        sys.exit(1)
