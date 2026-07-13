"""Chunking determinista de texto extraído de pliegos (plan Pliegos+RAG, F8).

Puro: sin I/O, sin dependencias de modelo. La determinismo importa porque el
job de embeddings (``scheduler/jobs/documentos_embeddings.py``) compara los
chunks recién calculados contra los ya persistidos para decidir si hace falta
recalcular embeddings — la misma entrada debe producir siempre la misma
salida (mismo número de chunks, mismos límites exactos).
"""

from __future__ import annotations

# Rango pedido por el plan: ~1.200-1.500 caracteres, solape ~15%.
DEFAULT_CHUNK_SIZE = 1400
DEFAULT_OVERLAP_RATIO = 0.15


def chunk_text(
    texto: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap_ratio: float = DEFAULT_OVERLAP_RATIO,
) -> list[str]:
    """Divide ``texto`` en fragmentos de ``~chunk_size`` caracteres con solape.

    Evita cortar a mitad de palabra cuando es posible (retrocede hasta el
    último espacio dentro de la ventana) — mejora la calidad semántica del
    chunk sin sacrificar el tamaño objetivo de forma significativa.

    Args:
        texto: Texto a fragmentar (se recorta con ``.strip()``).
        chunk_size: Tamaño objetivo en caracteres por chunk.
        overlap_ratio: Fracción de ``chunk_size`` que se solapa entre chunks
            consecutivos (0.0 = sin solape, debe ser < 1.0).

    Returns:
        Lista de chunks en orden; vacía si ``texto`` está vacío tras strip.
    """
    texto = texto.strip()
    if not texto:
        return []
    if chunk_size <= 0:
        raise ValueError(f"chunk_size debe ser > 0, recibido {chunk_size}")
    if not (0.0 <= overlap_ratio < 1.0):
        raise ValueError(f"overlap_ratio debe estar en [0.0, 1.0), recibido {overlap_ratio}")

    n = len(texto)
    if n <= chunk_size:
        return [texto]

    overlap = int(chunk_size * overlap_ratio)
    chunks: list[str] = []
    start = 0
    while start < n:
        end = min(start + chunk_size, n)
        if end < n:
            # Evitar cortar a mitad de palabra: retroceder al último espacio
            # dentro de la ventana (solo si hay uno razonablemente cerca).
            last_space = texto.rfind(" ", start, end)
            if last_space > start:
                end = last_space
        chunk = texto[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        next_start = end - overlap
        if next_start <= start:
            # Palabra larga + overlap grande podría no avanzar -- forzar
            # progreso para garantizar terminación.
            next_start = end
        start = next_start
    return chunks
