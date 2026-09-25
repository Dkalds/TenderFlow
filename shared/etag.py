"""Fórmula y comparación de las ETag que emite la API.

Vive en ``shared`` y no en ``api/middleware.py`` porque la usan dos capas: el
``ETagMiddleware`` etiqueta las respuestas GET JSON que llegan sin ``ETag``, y
la caché de respuestas (``shared/cache.py``) puede adjuntar la etiqueta ya
calculada a lo que sirve desde Redis, para que el middleware no tenga que
hashear el cuerpo en cada acierto. Las dos tienen que dar **la misma etiqueta
para el mismo cuerpo**: si no, un cliente que revalida con la ETag de un fallo
de caché recibe un 200 completo en el siguiente acierto, y viceversa.
``shared`` no puede importar ``api`` (inversión de capas), así que la fórmula
baja aquí.
"""

from __future__ import annotations

import hashlib


def etag_debil(cuerpo: bytes) -> str:
    """ETag débil (``W/"…"``) de los bytes exactos que viajan en la respuesta.

    Débil porque la compresión (Brotli/GZip) va por fuera del middleware: el
    mismo recurso sale en varias codificaciones con la misma etiqueta, y eso
    solo es correcto con una etiqueta débil (RFC 9110 §8.8.1).

    BLAKE2b con 16 bytes de salida: no es una firma, es una huella de contenido.
    Es más barato que el SHA-256 truncado que había, y 128 bits sobran para que
    dos cuerpos distintos no colisionen por accidente.
    """
    return 'W/"' + hashlib.blake2b(cuerpo, digest_size=16).hexdigest() + '"'


def coincide_if_none_match(etag: str, if_none_match: str) -> bool:
    """``True`` si ``If-None-Match`` nombra la misma etiqueta que ``etag``.

    Comparación débil, la que manda RFC 9110 §13.1.2 para ``If-None-Match``:
    ``W/"x"`` y ``"x"`` son la misma etiqueta. La cabecera puede traer varias,
    separadas por comas.
    """
    if not if_none_match:
        return False
    buscada = _opaca(etag)
    return any(_opaca(candidata) == buscada for candidata in if_none_match.split(","))


def _opaca(etiqueta: str) -> str:
    """La etiqueta sin espacios ni el prefijo ``W/`` de débil."""
    etiqueta = etiqueta.strip()
    return etiqueta[2:] if etiqueta.startswith("W/") else etiqueta


__all__ = ["coincide_if_none_match", "etag_debil"]
