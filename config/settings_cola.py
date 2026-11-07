"""Ajustes de la cola de trabajo, el worker y el despachador del outbox (ADR-027/028).

Salen de ``config/settings.py`` (P3 «Los dos módulos-dios») y ``config.settings``
los reexporta, así que ``from config.settings import jobs_max_intentos`` sigue
valiendo.
"""

from __future__ import annotations

import os

# ── ANCLA S5 — cola de trabajo y worker ──────────────────────────────────
#
# Fuera de `Settings` y no dentro, por el mismo motivo que `database_admin_url`
# de arriba: son ajustes de un componente (el consumidor de la cola) que la API
# solo necesita para decidir un umbral, no parámetros del entorno de datos. Se
# leen de `os.environ` en cada llamada para que un test los mueva sin
# reconstruir el singleton, que es exactamente lo que hace `test_s5_cola.py`.

#: Segundos que un job puede quedarse ``running`` sin que su worker dé señales
#: antes de que otro lo reclame. Es el tiempo máximo que un despliegue a mitad
#: de una extracción retrasa el trabajo del usuario, así que no puede ser mucho
#: mayor que la extracción más larga (la ficha del pliego: 8 PDFs + LLM).
JOBS_LOCK_TTL_SEGUNDOS_DEFAULT = 900

#: Intentos totales por job, reclamación incluida. Tres son dos reintentos: con
#: el backoff de abajo, la última oportunidad llega ~90 s después de la primera.
JOBS_MAX_INTENTOS_DEFAULT = 3

#: Base del backoff exponencial entre reintentos (30 s, 60 s, 120 s…).
JOBS_BACKOFF_BASE_SEGUNDOS_DEFAULT = 30

#: Espera del worker cuando la cola está vacía. Cinco segundos es el retardo
#: máximo que ve un usuario que acaba de pulsar «Extraer ficha»; bajarlo cuesta
#: una consulta más por segundo contra el pooler.
JOBS_WORKER_POLL_SEGUNDOS_DEFAULT = 5.0

#: A partir de cuántas filas pedidas ``GET /exports/download?format=pdf`` deja
#: de renderizar en la request y encola (S5.2). El umbral se aplica sobre el
#: `limit` PEDIDO y no sobre las filas reales: contar antes exigiría ejecutar la
#: consulta, que es justo el trabajo del que se quiere sacar a la request.
#:
#: 20 000 y no un número menor porque el `limit` por defecto de la ruta es
#: 10 000: con el umbral por debajo de ese valor, la petición **por defecto**
#: cambiaría de devolver un fichero a devolver un 202, y todo cliente que hoy
#: espera el PDF en la respuesta se rompería sin haber pedido nada distinto.
#: Solo una petición explícitamente grande cruza al camino encolado.
JOBS_EXPORT_UMBRAL_FILAS_DEFAULT = 20000


def _entero_env(nombre: str, defecto: int, *, minimo: int = 1) -> int:
    """Entero de entorno con suelo. Un valor ilegible NO tumba el proceso.

    Un typo en una variable de tuning del worker no puede impedir que el
    servicio arranque: se ignora y se usa el defecto, que es un valor seguro.
    """
    crudo = os.environ.get(nombre, "").strip()
    if not crudo:
        return defecto
    try:
        valor = int(crudo)
    except ValueError:
        return defecto
    return max(minimo, valor)


def _flotante_env(nombre: str, defecto: float, *, minimo: float = 0.1) -> float:
    """Igual que :func:`_entero_env` para valores fraccionarios."""
    crudo = os.environ.get(nombre, "").strip()
    if not crudo:
        return defecto
    try:
        valor = float(crudo)
    except ValueError:
        return defecto
    return max(minimo, valor)


def jobs_lock_ttl_segundos() -> int:
    return _entero_env("JOBS_LOCK_TTL_SEGUNDOS", JOBS_LOCK_TTL_SEGUNDOS_DEFAULT, minimo=10)


def jobs_max_intentos() -> int:
    return _entero_env("JOBS_MAX_INTENTOS", JOBS_MAX_INTENTOS_DEFAULT, minimo=1)


def jobs_backoff_base_segundos() -> int:
    return _entero_env("JOBS_BACKOFF_BASE_SEGUNDOS", JOBS_BACKOFF_BASE_SEGUNDOS_DEFAULT, minimo=1)


def jobs_worker_poll_segundos() -> float:
    return _flotante_env("JOBS_WORKER_POLL_SEGUNDOS", JOBS_WORKER_POLL_SEGUNDOS_DEFAULT, minimo=0.1)


def jobs_export_umbral_filas() -> int:
    return _entero_env("JOBS_EXPORT_UMBRAL_FILAS", JOBS_EXPORT_UMBRAL_FILAS_DEFAULT, minimo=1)


def jobs_consumidor_en_api(env: str) -> bool:
    """¿El proceso de la API consume él mismo la cola a demanda? (ADR-028 §G)

    ADR-028 da la cola a demanda (la ficha del pliego, los embeddings de un
    expediente, el PDF grande) a un servicio ``tenderflow-worker``: hasta el
    2026-10-01 no existía y los jobs ``ficha_pliego`` se encolaban sin que nadie
    los reclamara (la pestaña Pliego decía «Extrayendo…» para siempre). Desde
    entonces la API los consume en un hilo propio, y desde el 2026-10-19, en que
    el worker se retiró, es el único consumidor en producción.

    Por defecto sí en ``prod``/``staging`` y no en el resto: en ``dev`` y
    ``test`` un hilo reclamando jobs desde el lifespan de cada ``TestClient``
    ejecutaría handlers reales en mitad de tests que encolan para mirar la
    fila. ``JOBS_CONSUMIDOR_EN_API=0`` lo apaga, solo si vuelve a haber un
    worker dedicado (``render.yaml`` lo declara ``sync: false`` en
    ``tenderflow-api``: lo decide el dashboard); ``=1`` lo enciende en local. Dos consumidores a la
    vez no son un fallo —``SKIP LOCKED``—: apagarlo solo devuelve ese trabajo a
    su proceso.
    """
    crudo = os.environ.get("JOBS_CONSUMIDOR_EN_API", "").strip().lower()
    if not crudo:
        return env in ("prod", "staging")
    return crudo not in ("0", "false", "no", "off")


def jobs_cierre_por_cola() -> bool:
    """¿El cierre post-ingesta encola sus pasos en vez de ejecutarlos en línea?

    Por defecto sí (S5.4): cada paso deja una fila en ``jobs`` con su resultado,
    así que una pasada cortada a mitad se puede leer paso a paso en vez de
    reconstruirla del log de un runner efímero. ``JOBS_CIERRE_POR_COLA=0``
    devuelve el cierre al camino en línea — la salida de escape si la cola diera
    problemas en producción, sin desplegar código.
    """
    crudo = os.environ.get("JOBS_CIERRE_POR_COLA", "").strip().lower()
    if not crudo:
        return True
    return crudo not in ("0", "false", "no", "off")


# ── Despachador del outbox (S4.1) ────────────────────────────────────────────

#: Antigüedad máxima, en horas, de un evento que el despachador todavía entrega.
#:
#: El despachador estuvo escrito y sin cablear desde S4.1: cuando se enchufó, la
#: cola traía semanas de ``domain_events`` sin repartir. Entregarlos habría sido
#: un aluvión de correos y webhooks sobre cosas que ya no importan —«te han
#: asignado» una oportunidad que se cerró hace diez días—, así que lo que supera
#: esta antigüedad se marca como despachado **sin** entregarse, con su conteo en
#: el log y en ``ops_events``. 48 h cubren un fin de semana con el cierre caído
#: sin tirar nada que todavía se pueda leer como noticia.
EVENT_DISPATCH_MAX_AGE_HOURS_DEFAULT = 48


def event_dispatch_enabled() -> bool:
    """¿El cierre reparte el outbox de ``domain_events``?

    Por defecto sí, en todos los entornos: un aviso que no sale es un fallo que
    nadie ve. ``EVENT_DISPATCH_ENABLED=0`` lo apaga sin desplegar código —la
    salida de escape si el reparto diera problemas—; los eventos se siguen
    escribiendo y esperan en la cola, sujetos a la antigüedad máxima cuando se
    vuelva a encender.
    """
    crudo = os.environ.get("EVENT_DISPATCH_ENABLED", "").strip().lower()
    if not crudo:
        return True
    return crudo not in ("0", "false", "no", "off")


def event_dispatch_max_age_hours() -> int:
    """Horas tras las que un evento pendiente caduca sin entregarse (mínimo 1)."""
    return _entero_env(
        "EVENT_DISPATCH_MAX_AGE_HOURS", EVENT_DISPATCH_MAX_AGE_HOURS_DEFAULT, minimo=1
    )
