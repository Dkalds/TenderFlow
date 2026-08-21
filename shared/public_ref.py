"""Referencia pública de una licitación: ``id_externo`` en forma apta para una URL.

El problema que resuelve
------------------------
Los ``id_externo`` reales de PLACSP contienen **espacios y barras**. El ejemplo
que usa el propio repositorio en sus tests es ``"PA-S 2026/000058"``
(``tests/test_ask_route.py``). Una barra dentro de un identificador no se puede
meter en un segmento de ruta: crea segmentos fantasma, y por eso las rutas
internas necesitan el conversor ``:path`` de Starlette (ver el catch-all
deliberado de ``api/app.py``).

En la API interna eso se resuelve con ``:path`` porque el consumidor es la
propia aplicación. En una URL **pública e indexable** no vale: la ruta la
construye el frontend, la reescribe Next, la almacena Google y la copia un
humano en un correo. Necesita ser opaca, estable y sin caracteres que ningún
tramo del camino vaya a reinterpretar.

Por qué base64url y no otra cosa
--------------------------------
- **Reversible sin base de datos.** No hace falta ni una columna nueva ni un
  índice: decodificar devuelve el ``id_externo`` exacto. Un hash obligaría a
  una migración de schema (que además requiere aprobación humana) o a un escaneo
  completo por cada visita de un rastreador.
- **Estable.** El mismo expediente produce siempre la misma referencia, así que
  la URL no cambia entre despliegues y los enlaces no se rompen.
- **Sin relleno ni caracteres reservados.** Se descarta el ``=`` final y el
  alfabeto ``-_`` no colisiona con nada del path ni de la query.

La referencia no aporta nada al SEO y no pretende hacerlo: el peso semántico de
la URL lo lleva el slug del título, que va delante. Esto es solo el ancla que
identifica el expediente sin ambigüedad.
"""

from __future__ import annotations

import base64
import binascii

__all__ = ["codificar_ref", "decodificar_ref"]

# Un `id_externo` legítimo no llega a esto ni de lejos; el tope corta entradas
# inventadas antes de decodificarlas. Es defensa contra basura, no validación.
_MAX_LONGITUD_REF = 512


def codificar_ref(id_externo: str) -> str:
    """Convierte un ``id_externo`` en su referencia pública.

    Args:
        id_externo: identificador tal cual está en la base de datos, con sus
            espacios y barras si los tiene.

    Returns:
        Cadena base64url sin relleno, apta para un segmento de URL.
    """
    crudo = base64.urlsafe_b64encode(id_externo.encode("utf-8"))
    return crudo.decode("ascii").rstrip("=")


def decodificar_ref(ref: str) -> str | None:
    """Recupera el ``id_externo`` a partir de su referencia pública.

    Devuelve ``None`` ante cualquier entrada que no sea una referencia válida,
    en vez de lanzar. El llamante es un endpoint público: la entrada viene de
    internet y una referencia inventada tiene que acabar en un 404 limpio, no
    en un 500. El ratchet ``scripts/fuzz_api_contract.py`` exige justamente eso
    —ninguna operación puede devolver 5xx ante entrada fuzzeada—, así que el
    fallo silencioso aquí es deliberado.

    Args:
        ref: el segmento de URL producido por :func:`codificar_ref`.

    Returns:
        El ``id_externo`` original, o ``None`` si ``ref`` no es decodificable.
    """
    if not ref or len(ref) > _MAX_LONGITUD_REF:
        return None

    # base64url sin relleno: se repone antes de decodificar. `b64decode` con
    # validate=True rechaza cualquier carácter fuera del alfabeto.
    relleno = "=" * (-len(ref) % 4)
    try:
        crudo = base64.urlsafe_b64decode(ref + relleno)
    except (binascii.Error, ValueError):
        return None

    try:
        id_externo = crudo.decode("utf-8")
    except UnicodeDecodeError:
        return None

    # El byte NUL no puede llegar a Postgres (ver `SafeStr` en shared/dto.py):
    # psycopg lo rechaza y la excepción saldría como 500.
    if not id_externo or "\x00" in id_externo:
        return None

    return id_externo
