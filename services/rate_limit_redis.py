"""Backend Redis para rate limiting (F4).

Lo elige ``services.rate_limiting.get_rate_limiter`` cuando ``RATE_LIMIT_BACKEND``
vale ``auto`` (el valor por defecto) o ``redis`` y hay ``REDIS_URL``. Mantiene API
compatible con ``db.rate_limits.check_rate_limit_db``: si Redis no está
disponible devuelve ``None`` y quien llama resuelve contra la base de datos.

Diseño:

* Ventana deslizante en un sorted set por clave: ``ZREMRANGEBYSCORE`` purga lo
  que salió de la ventana, ``ZADD`` apunta la petición y ``ZCARD`` cuenta, en una
  transacción ``MULTI``/``EXEC`` de un solo viaje.
* Una petición **denegada no consume cuota**: se retira del set con ``ZREM``.
  Es lo que hace el backend de BD, que solo inserta cuando permite. Sin esto,
  pasar de BD a Redis (el ``auto`` lo hace solo en cuanto hay ``REDIS_URL``)
  cambiaba la regla en producción: un cliente que reintenta por encima del
  límite no volvía a pasar nunca, porque cada 429 alargaba su propia ventana.
* TTL sobre la clave igual a la ventana, para evitar fugas en claves
  abandonadas.
* Las claves llevan el prefijo ``rl:``. El Redis es el mismo que el de la caché
  de respuestas (``shared/cache.py``, namespace ``api:``), y una clave de cuota
  como ``api:ip:1.2.3.4`` compartiría espacio de nombres con las suyas.

Fallos: **nunca abren el límite.** Cualquier error de Redis —al conectar o en
una operación— devuelve ``None`` (esa comprobación la resuelve la BD) y deja
Redis en enfriamiento durante :data:`ENFRIAMIENTO_S`: mientras dura, no se
reintenta la conexión. Antes de 2026-09 cada petición volvía a intentar
conectar con un timeout de 1 s, así que un Redis caído sumaba hasta un segundo
a **cada** request (y con el limitador llamado desde el event loop, lo paraba
entero). El cliente tampoco reintenta por su cuenta más de una vez: redis-py
≥ 6 trae por defecto tres reintentos con backoff exponencial, que con un Redis
colgado convertían una comprobación de milisegundos en ~10 s.

Dependencia: el paquete ``redis`` no es un extra. Está en ``dependencies`` de
``pyproject.toml`` y en ``requirements.in`` y ``requirements-api.in`` (este
último lo hereda ``requirements-pipeline.in``), así que cualquier instalación
desde esos ficheros lo trae.
"""

from __future__ import annotations

import itertools
import os
import threading
import time

from observability.logging import get_logger

log = get_logger(__name__)

# El ``except`` solo corre en un intérprete al que le falta el paquete ``redis``
# (una instalación que no salió de los ficheros de dependencias). Entonces
# ``has_redis()`` da False, ``check_rate_limit_redis`` devuelve None y tanto
# ``check_rate_limit`` como ``services.rate_limiting`` usan la base de datos, en
# vez de fallar con ImportError al importar este módulo. En los tests ``redis``
# está instalado y el ``except`` no corre: de ahí los ``pragma: no cover``.
try:  # pragma: no cover
    import redis

    _REDIS_AVAILABLE = True
except ImportError:  # pragma: no cover
    redis = None  # type: ignore[assignment]  # import redis tipa el nombre como módulo (py.typed); el fallback lo deja en None y los tests parchean ese nombre
    _REDIS_AVAILABLE = False


#: Segundos sin volver a intentar Redis tras un fallo. Cubre un reinicio o un
#: mantenimiento del servicio sin castigar cada petición con un timeout; durante
#: el enfriamiento las comprobaciones van a la BD.
ENFRIAMIENTO_S = 30.0

#: Prefijo de las claves de cuota en Redis (ver el docstring del módulo).
PREFIJO_CLAVE = "rl:"

_lock = threading.Lock()
_client: redis.Redis | None = None
#: Instante (``time.monotonic``) hasta el que no se reintenta conectar.
_sin_redis_hasta = 0.0
#: Desempata dos peticiones del mismo proceso en el mismo microsegundo, que ahora
#: es posible: la comprobación corre en hilos, no serializada en el event loop.
#: Con el mismo miembro, el ``ZADD`` de la segunda solo actualizaba el score y
#: esa petición no contaba.
_secuencia = itertools.count()


def has_redis() -> bool:
    return _REDIS_AVAILABLE and bool(os.getenv("REDIS_URL"))


def reset_client() -> None:
    """Olvida el cliente y el enfriamiento. Para tests y cambios de configuración."""
    global _client, _sin_redis_hasta
    with _lock:
        anterior, _client = _client, None
        _sin_redis_hasta = 0.0
    if anterior is not None:
        try:
            anterior.close()
        except Exception:
            log.debug("ratelimit_redis_close_failed", exc_info=True)


def _get_client() -> redis.Redis | None:
    """Cliente compartido, o ``None`` si no hay Redis o está en enfriamiento."""
    global _client
    if not has_redis():
        return None
    cliente = _client
    if cliente is not None:
        return cliente
    if time.monotonic() < _sin_redis_hasta:
        return None
    # Conecta un solo hilo. Los demás no esperan a su timeout (hasta 1 s más el
    # ping): resuelven su petición contra la BD, que es correcto, solo más lento.
    if not _lock.acquire(blocking=False):
        return None
    try:
        if _client is not None:
            return _client
        if time.monotonic() < _sin_redis_hasta:
            return None
        url = os.getenv("REDIS_URL", "")
        nuevo: redis.Redis | None = None
        try:
            from redis.backoff import NoBackoff
            from redis.retry import Retry

            nuevo = redis.Redis.from_url(
                url,
                socket_connect_timeout=1.0,
                socket_timeout=1.0,
                decode_responses=False,
                # Un reintento inmediato cubre una conexión del pool que el
                # servidor cerró; más, con backoff, es tiempo de petición.
                retry=Retry(NoBackoff(), 1),
                # Como `llm/budget.py`: la contraseña puede venir aparte de la
                # URL (`REDIS_PASSWORD`, obligatoria en prod). Si la URL ya la
                # trae, redis-py da prioridad a la de la URL.
                password=os.getenv("REDIS_PASSWORD") or None,
            )
            nuevo.ping()
        except Exception as exc:
            log.warning(
                "ratelimit_redis_unavailable", error=str(exc), reintento_en_s=ENFRIAMIENTO_S
            )
            # Un ping que falla tras conectar (p. ej. por AUTH) deja un socket
            # abierto en el pool del cliente descartado: se cierra aquí.
            _entrar_en_enfriamiento(nuevo)
            return None
        _client = nuevo
        log.info("ratelimit_redis_connected", url_host=url.split("@")[-1])
        return nuevo
    finally:
        _lock.release()


def _entrar_en_enfriamiento(cliente: redis.Redis | None) -> None:
    """Redis falló: se deja de intentar durante :data:`ENFRIAMIENTO_S`.

    El log lo pone quien llama, en su propio ``except``: así cada fallo conserva
    su evento (``ratelimit_redis_unavailable`` al conectar,
    ``ratelimit_redis_op_failed`` en una operación) y el guardarraíl de
    ``tests/test_swallowed_exceptions_guard.py`` ve la constancia donde la busca.

    Sin el lock a propósito: puede llamarse desde un hilo cuya operación falló
    mientras otro intenta reconectar, y esperar a ese intento es justo el
    retraso que el enfriamiento quiere evitar. Las carreras posibles (dos hilos
    que fallan a la vez) solo repiten asignaciones idempotentes.
    """
    global _client, _sin_redis_hasta
    _sin_redis_hasta = time.monotonic() + ENFRIAMIENTO_S
    if cliente is not None:
        if _client is cliente:
            _client = None
        try:
            cliente.close()
        except Exception:
            log.debug("ratelimit_redis_close_failed", exc_info=True)


def check_rate_limit_redis(
    key: str,
    *,
    max_calls: int = 120,
    window_seconds: float = 60.0,
) -> bool | None:
    """Versión Redis de :func:`db.rate_limits.check_rate_limit_db`.

    Devuelve:
        * ``True`` si el request está permitido.
        * ``False`` si excede el límite.
        * ``None`` si Redis no está disponible (caller debe usar fallback).
    """
    client = _get_client()
    if client is None:
        return None

    now = time.time()
    window_start = now - window_seconds
    clave = f"{PREFIJO_CLAVE}{key}"
    member = f"{now:.6f}:{os.getpid()}:{next(_secuencia)}"

    try:
        pipe = client.pipeline()
        pipe.zremrangebyscore(clave, 0, window_start)
        pipe.zadd(clave, {member: now})
        pipe.zcard(clave)
        pipe.expire(clave, int(window_seconds) + 1)
        _, _, count, _ = pipe.execute()
    except Exception as exc:
        log.warning("ratelimit_redis_op_failed", error=str(exc), reintento_en_s=ENFRIAMIENTO_S)
        _entrar_en_enfriamiento(client)
        return None

    allowed = int(count) <= max_calls
    if not allowed:
        # La denegada sale del set: no consume cuota (ver el docstring del
        # módulo). Si esto falla la decisión ya está tomada y sigue siendo 429;
        # lo único que se pierde es que este intento cuente de más.
        try:
            client.zrem(clave, member)
        except Exception as exc:
            log.warning("ratelimit_redis_op_failed", error=str(exc), reintento_en_s=ENFRIAMIENTO_S)
            _entrar_en_enfriamiento(client)
        log.info("ratelimit_redis_exceeded", key=key, count=int(count), limit=max_calls)
    return allowed


def check_rate_limit(
    key: str,
    *,
    max_calls: int = 120,
    window_seconds: float = 60.0,
) -> bool:
    """Dispatcher: Redis si configurado y operativo; BD como fallback.

    Sigue la misma regla que ``services.rate_limiting.get_rate_limiter``:
    ``RATE_LIMIT_BACKEND=auto`` (por defecto) o ``redis`` intentan Redis y caen
    a la BD; ``db`` (o su alias histórico ``sqlite``) va siempre a la BD.
    """
    backend = os.getenv("RATE_LIMIT_BACKEND", "auto").strip().lower()
    if backend not in ("db", "sqlite"):
        result = check_rate_limit_redis(key, max_calls=max_calls, window_seconds=window_seconds)
        if result is not None:
            return result
        log.debug("ratelimit_redis_fallback_to_db", key=key)

    from db.rate_limits import check_rate_limit_db

    return check_rate_limit_db(key, max_calls=max_calls, window_seconds=window_seconds)


__all__ = [
    "ENFRIAMIENTO_S",
    "PREFIJO_CLAVE",
    "check_rate_limit",
    "check_rate_limit_redis",
    "has_redis",
    "reset_client",
]
