"""Techo de ``statement_timeout`` para las rutas de analítica.

Dependencia de router de ``/analytics`` y ``/competitive``: fija en el contexto
de la petición el techo ``API_ANALYTICS_STATEMENT_TIMEOUT_MS`` para todas las
lecturas que no pidan el suyo (``db.connection.fijar_techo_de_sentencia``).

Va en el contexto de la petición, y no en ``db/repositories/aggregates.py``,
porque esas mismas funciones las llaman los jobs de precálculo
(``scheduler/kpi_precompute``), que necesitan justo las consultas largas que el
techo cortaría. Con el setting a 0 —su valor por defecto, ver
``config/settings.py``— la dependencia no cambia nada.
"""

from __future__ import annotations

from config.settings import settings
from db.connection import fijar_techo_de_sentencia


async def techo_sentencia_analitica() -> None:
    """Fija el techo de sentencia de la analítica para el resto de la petición.

    Es ``async`` a propósito: FastAPI resuelve las dependencias asíncronas en
    la misma tarea que el endpoint, así que el ``ContextVar`` lo ven el handler
    y los hilos que despache (anyio copia el contexto). Una dependencia
    síncrona correría en un hilo del threadpool y el valor moriría con él.
    """
    fijar_techo_de_sentencia(settings.API_ANALYTICS_STATEMENT_TIMEOUT_MS or None)
