"""Embeddings semánticos para similitud de licitaciones.

Dos motores para el mismo modelo, ``config.settings.EMBEDDING_MODEL``
(``paraphrase-multilingual-MiniLM-L12-v2``, 384 dimensiones):

- **sentence-transformers** (extra ``[ml]``, arrastra PyTorch). Es con el que
  el plano de ingesta embebe ``documento_chunks``, así que si está instalado
  manda él.
- **ONNX** (``services/embeddings_onnx.py``: ``onnxruntime`` + ``tokenizers``),
  activo si ``EMBEDDINGS_ONNX_DIR`` apunta a un modelo. Es el de la imagen de la
  API, que no instala PyTorch (C3.1), y existe para codificar la **consulta**
  de la búsqueda por significado.

Sin ninguno de los dos, ``smart_match`` cae a coincidencia de substrings y
quien llama a ``encode_texts`` recibe ``ImportError``.

Codificar una consulta es barato con cualquiera de los dos; codificar un corpus
de cientos o miles de textos dentro de una petición no lo es (ver
``embeddings_masivos_disponibles``).
"""

from __future__ import annotations

import importlib.util
import re
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, cast

import numpy as np

from config import settings
from observability import get_logger
from services.embeddings_onnx import CodificadorOnnx, leer_repo_de_origen, modelo_onnx_presente

log = get_logger(__name__)

# Resolved from settings at import time so lru_cache works correctly
_MODEL_NAME = settings.EMBEDDING_MODEL

#: Motor con el que se codifica, en orden de preferencia.
Backend = Literal["sentence_transformers", "onnx"]

# ── Lazy model loading ──────────────────────────────────────────────────


def _has_sentence_transformers() -> bool:
    try:
        import sentence_transformers  # noqa: F401

        return True
    except ImportError:
        return False


@lru_cache(maxsize=1)
def _load_model() -> Any:
    """Carga el modelo sentence-transformers (cached en memoria)."""
    from sentence_transformers import SentenceTransformer

    log.info("embeddings.loading_model", model=_MODEL_NAME)
    return SentenceTransformer(_MODEL_NAME)


# Estado del motor ONNX. Se carga una vez por proceso y bajo cerrojo: son
# ~470 MB, y dos peticiones simultáneas no deben cargarlo dos veces. Si la carga
# falla se recuerda el directorio y el motor queda apagado hasta reiniciar: un
# modelo roto no se reintenta en cada petición (cada intento relee el fichero
# entero), y ``embeddings_available()`` pasa a decir la verdad.
_onnx_lock = threading.Lock()
_onnx_codificador: CodificadorOnnx | None = None
_onnx_directorio_cargado: Path | None = None
_onnx_directorio_fallido: Path | None = None
_onnx_avisos: set[str] = set()


def _reiniciar_onnx() -> None:
    """Olvida el modelo ONNX cargado y los fallos recordados (para tests)."""
    global _onnx_codificador, _onnx_directorio_cargado, _onnx_directorio_fallido
    with _onnx_lock:
        _onnx_codificador = None
        _onnx_directorio_cargado = None
        _onnx_directorio_fallido = None
        _onnx_avisos.clear()


def _avisar_una_vez(evento: str, **campos: object) -> None:
    clave = f"{evento}:{sorted(campos.items())}"
    if clave not in _onnx_avisos:
        _onnx_avisos.add(clave)
        log.warning(evento, **campos)


def _has_onnx_runtime() -> bool:
    return (
        importlib.util.find_spec("onnxruntime") is not None
        and importlib.util.find_spec("tokenizers") is not None
    )


def _mismo_modelo(repo: str, modelo: str) -> bool:
    """``sentence-transformers/paraphrase-…`` y ``paraphrase-…`` son el mismo."""
    return repo == modelo or repo.endswith("/" + modelo) or modelo.endswith("/" + repo)


def _directorio_onnx() -> Path | None:
    """El directorio del modelo ONNX si está configurado y es utilizable.

    Se lee de ``settings`` en cada llamada (y no al importar) para que un
    cambio de configuración en tests o en caliente no requiera recargar el
    módulo. Las comprobaciones son de sistema de ficheros: baratas.
    """
    configurado = str(getattr(settings, "EMBEDDINGS_ONNX_DIR", "") or "").strip()
    if not configurado:
        return None
    directorio = Path(configurado)
    if directorio == _onnx_directorio_fallido:
        return None
    if not modelo_onnx_presente(directorio):
        _avisar_una_vez("embeddings.onnx_sin_modelo", directorio=configurado)
        return None
    repo = leer_repo_de_origen(directorio)
    if repo is not None and not _mismo_modelo(repo, str(settings.EMBEDDING_MODEL)):
        # Un vector de otro modelo no es comparable con los guardados: la
        # fusión devolvería vecinos sin sentido con aspecto de resultado.
        _avisar_una_vez(
            "embeddings.onnx_otro_modelo", repo=repo, embedding_model=settings.EMBEDDING_MODEL
        )
        return None
    if not _has_onnx_runtime():
        _avisar_una_vez("embeddings.onnx_sin_runtime", directorio=configurado)
        return None
    return directorio


def _cargar_codificador_onnx(directorio: Path) -> CodificadorOnnx:
    return CodificadorOnnx.desde_directorio(directorio)


def _codificador_onnx(directorio: Path) -> CodificadorOnnx:
    global _onnx_codificador, _onnx_directorio_cargado, _onnx_directorio_fallido
    with _onnx_lock:
        if _onnx_codificador is not None and _onnx_directorio_cargado == directorio:
            return _onnx_codificador
        log.info("embeddings.loading_model", model=_MODEL_NAME, backend="onnx")
        try:
            codificador = _cargar_codificador_onnx(directorio)
        except Exception:
            _onnx_directorio_fallido = directorio
            log.error("embeddings.onnx_carga_fallida", directorio=str(directorio), exc_info=True)
            raise
        _onnx_codificador = codificador
        _onnx_directorio_cargado = directorio
        return codificador


def backend_embeddings() -> Backend | None:
    """El motor con el que ``encode_texts`` codificaría ahora, o ``None``."""
    if _has_sentence_transformers():
        return "sentence_transformers"
    if _directorio_onnx() is not None:
        return "onnx"
    return None


def embeddings_available() -> bool:
    """Indica si hay con qué codificar (sentence-transformers u ONNX)."""
    return backend_embeddings() is not None


def embeddings_masivos_disponibles() -> bool:
    """True si se puede codificar un **corpus** dentro de una petición.

    El motor ONNX está en la API para la consulta: un texto por búsqueda.
    Con él, las rutas que codifican cientos o miles de textos por petición
    —la afinidad del Radar puntúa ~1.600 candidatas en cada carga, el ranking
    del RAG hasta 120 fragmentos, el embebido de un expediente en el worker de
    la API— pasarían de no usar embeddings a tardar decenas de segundos de CPU
    en el mismo proceso que sirve las peticiones. Esas rutas siguen gateadas
    por sentence-transformers, como antes de que existiera el motor ONNX; lo
    que les falta para usar significado en la API es leer vectores ya
    guardados, no calcularlos al vuelo (backlog P2 «La búsqueda por significado
    no corre en producción»).

    Se define a partir de ``embeddings_available()`` para que los tests que
    parchean esa función sigan gobernando también estas rutas.
    """
    return embeddings_available() and backend_embeddings() != "onnx"


# ── Core functions ──────────────────────────────────────────────────────


def encode_texts(texts: list[str], batch_size: int = 64) -> np.ndarray:
    """Codifica una lista de textos en embeddings.

    Returns:
        ndarray de shape (n, dim) con embeddings normalizados.
    """
    backend = backend_embeddings()
    if backend == "onnx":
        directorio = _directorio_onnx()
        if directorio is not None:
            return _codificador_onnx(directorio).codificar(texts, batch_size=batch_size)
    if backend != "sentence_transformers":
        msg = (
            "Sin motor de embeddings: instala sentence-transformers (extra `[ml]`) "
            "o configura EMBEDDINGS_ONNX_DIR con el modelo ONNX"
        )
        raise ImportError(msg)

    model = _load_model()
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=False,
        normalize_embeddings=True,
    )
    return np.asarray(embeddings)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Calcula similitud coseno entre vectores (normalizados = dot product)."""
    if a.ndim == 1:
        a = a.reshape(1, -1)
    if b.ndim == 1:
        b = b.reshape(1, -1)
    return cast(np.ndarray, a @ b.T)


def semantic_match(
    query: str,
    corpus: list[str],
    threshold: float = 0.5,
) -> list[tuple[int, float]]:
    """Encuentra textos del corpus similares a la query.

    Args:
        query: Texto de búsqueda.
        corpus: Lista de textos candidatos.
        threshold: Similitud mínima (0-1).

    Returns:
        Lista de (índice, score) ordenados por score desc.
    """
    if not corpus:
        return []

    q_emb = encode_texts([query])
    c_emb = encode_texts(corpus)
    scores = cosine_similarity(q_emb, c_emb).flatten()

    results = [(int(i), float(scores[i])) for i in range(len(scores)) if scores[i] >= threshold]
    results.sort(key=lambda x: x[1], reverse=True)
    return results


# ── Fallback basado en substrings ───────────────────────────────────────

_WORD_RE = re.compile(r"[a-záéíóúñü0-9/\-]+", re.IGNORECASE)


def substring_match(
    query: str,
    corpus: list[str],
    threshold: float = 0.3,
) -> list[tuple[int, float]]:
    """Fallback: similitud basada en % de palabras de la query presentes en el texto."""
    if not corpus:
        return []

    q_words = set(_WORD_RE.findall(query.lower()))
    if not q_words:
        return []

    results = []
    for i, text in enumerate(corpus):
        t_words = set(_WORD_RE.findall(text.lower()))
        overlap = len(q_words & t_words) / len(q_words) if q_words else 0
        if overlap >= threshold:
            results.append((i, overlap))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


def smart_match(
    query: str,
    corpus: list[str],
    threshold: float = 0.5,
) -> list[tuple[int, float]]:
    """Usa embeddings si están disponibles, sino fallback a substrings.

    Codifica el corpus entero al vuelo, así que exige un motor apto para
    corpus (``embeddings_masivos_disponibles``), no solo para la consulta.
    """
    if embeddings_masivos_disponibles():
        try:
            return semantic_match(query, corpus, threshold=threshold)
        except Exception:
            log.warning("embeddings.fallback", reason="error in semantic_match")

    return substring_match(query, corpus, threshold=max(0.3, threshold - 0.2))
