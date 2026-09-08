"""¿Existe ya esta columna? — para leer sin depender del orden del despliegue.

Por qué hace falta
------------------
Las migraciones de producción se aplican **sólo a mano**
(``.github/workflows/migrate.yml`` es ``workflow_dispatch`` a propósito: migrar
es una decisión, no un efecto colateral de un push), mientras que el código
llega con el despliegue. La ventana entre las dos cosas es real y ya mordió:
el propio workflow lo cuenta —``column "lote_id" of relation "adjudicaciones"
does not exist`` en los runs de ``scrape-daily`` del 31 de julio.

Una lectura que nombra una columna nueva revienta entera durante esa ventana. Y
no revienta en el sitio donde se ve venir: revienta en el hilo de comentarios de
un equipo, o en la lista de favoritos, con un 500.

Este helper deja proyectar la columna sólo cuando existe. **No** es para
escrituras: un `INSERT` que se salta una columna nueva persiste dato incompleto
en silencio, que es peor que fallar. Para eso, la migración va antes y punto.

El caché
--------
Una consulta a ``information_schema`` por columna y proceso. La respuesta sólo
cambia cuando alguien migra, y el proceso se reinicia en el despliegue
siguiente; ``olvidar()`` existe para los tests, que crean y tiran esquemas.
"""

from __future__ import annotations

import threading

from observability.logging import get_logger

log = get_logger(__name__)

_lock = threading.Lock()
_cache: dict[tuple[str, str], bool] = {}


def existe(tabla: str, columna: str) -> bool:
    """``True`` si ``tabla.columna`` existe en el esquema activo.

    Ante cualquier error —sin base, sin permisos— devuelve ``False``: la lectura
    seguirá funcionando sin la columna, que es el modo degradado correcto.
    """
    clave = (tabla, columna)
    with _lock:
        if clave in _cache:
            return _cache[clave]
    try:
        from db.database import connect_read

        with connect_read() as conn:
            fila = conn.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = %s AND column_name = %s LIMIT 1",
                (tabla, columna),
            ).fetchone()
        presente = fila is not None
    except Exception:
        log.debug("columna_existe_no_verificable", tabla=tabla, columna=columna, exc_info=True)
        presente = False
    with _lock:
        _cache[clave] = presente
    return presente


def proyeccion(tabla: str, columna: str, *, alias: str | None = None, prefijo: str = "") -> str:
    """Fragmento ``SELECT`` para la columna, o un ``NULL`` con su nombre.

    Devuelve ``"c.nota"`` si existe y ``"NULL AS nota"`` si no, de modo que la
    forma de la fila —y por tanto el DTO— no cambia entre las dos situaciones.
    Un consumidor que reciba ``None`` no puede distinguir «no hay dato» de «la
    columna aún no existe», y para esto es exactamente lo que se quiere: ambas
    cosas se presentan igual y se arreglan solas al migrar.
    """
    nombre = alias or columna
    if existe(tabla, columna):
        return f"{prefijo}{columna} AS {nombre}" if prefijo else f"{columna} AS {nombre}"
    return f"NULL AS {nombre}"


def olvidar() -> None:
    """Vacía el caché. Para tests que crean y tiran esquemas."""
    with _lock:
        _cache.clear()
