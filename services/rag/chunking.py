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


def chunk_text_with_offsets(
    texto: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap_ratio: float = DEFAULT_OVERLAP_RATIO,
) -> list[tuple[str, int]]:
    """Como :func:`chunk_text`, pero cada chunk trae su offset en ``texto``.

    El offset es lo que permite decir **en qué página** cae un fragmento
    (C5.3): ``documento_pages`` guarda cada página con su ``start_offset`` sobre
    el mismo texto, así que la página del chunk es la última cuyo comienzo no lo
    supera. Sin esto, una cita del asistente solo puede apuntar al documento
    entero, y un pliego de 200 páginas no es una referencia.

    Es una función aparte y no un parámetro de :func:`chunk_text` porque el job
    de embeddings compara la salida de aquella contra los chunks persistidos
    para decidir si recalcula: cambiarle el tipo de retorno rompería esa
    comparación. Las dos comparten el mismo recorrido, verificado por un test de
    equivalencia — si se separasen, los offsets dejarían de señalar al chunk que
    dicen señalar sin que nada fallase.

    Returns:
        ``[(chunk, offset)]`` en orden; el offset es la posición del primer
        carácter del chunk dentro del texto ya recortado con ``.strip()``.
    """
    recortado = texto.strip()
    resultado: list[tuple[str, int]] = []
    cursor = 0
    for chunk in chunk_text(recortado, chunk_size=chunk_size, overlap_ratio=overlap_ratio):
        # `find` desde el cursor y no desde cero: con solape, el mismo texto
        # aparece dos veces y buscar desde el principio devolvería siempre la
        # primera aparición, colapsando todos los chunks a la misma página.
        pos = recortado.find(chunk, cursor)
        if pos < 0:  # pragma: no cover - `chunk_text` solo recorta espacios
            pos = cursor
        resultado.append((chunk, pos))
        cursor = pos + 1
    return resultado


def pagina_de_offset(offset: int, inicios_de_pagina: list[tuple[int, int]]) -> int | None:
    """Página que contiene ``offset``.

    Args:
        offset: Posición del chunk dentro del texto del documento.
        inicios_de_pagina: ``[(start_offset, page_number)]``, en cualquier orden.

    Returns:
        El ``page_number`` de la última página que empieza en o antes de
        ``offset``; ``None`` si el documento no tiene páginas persistidas o si
        el offset cae antes de la primera. Devolver la primera página «por si
        acaso» convertiría un dato ausente en una cita concreta y equivocada.
    """
    candidata: int | None = None
    mejor_inicio = -1
    for inicio, pagina in inicios_de_pagina:
        if inicio <= offset and inicio > mejor_inicio:
            mejor_inicio = inicio
            candidata = pagina
    return candidata


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
