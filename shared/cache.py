"""Cache unificado con backends Memory (LRU+TTL) y Redis.

Reemplaza las implementaciones históricas de caché con una única implementación
thread-safe y correctamente testeada.

Uso::

    from shared.cache import get_cache

    cache = get_cache("api")          # namespace "api", backend auto-detectado
    cache.set("key", value, ttl=60)
    value = cache.get("key")
    cache.delete("key")

Backends:
  - **Memory** (default): ``OrderedDict`` con LRU eviction y TTL por entrada.
    Thread-safe con ``threading.Lock``.
  - **Redis** (si ``REDIS_URL`` está configurado): Compartido entre procesos/workers.
    Falla de forma silenciosa volviendo a Memory si Redis no está disponible: al
    arrancar (si el ``PING`` falla, el namespace se queda en memoria) y en
    caliente, con un cortacircuitos (ver :class:`_RedisBackend`).

Redis y el event loop
---------------------
El cliente Redis es **síncrono** (redis-py) y lo siguen usando llamadores
síncronos (jobs, ``run_db``). Desde un ``async def`` no se le llama directamente:
se usan los métodos ``a*`` de los backends (``aget``, ``aset``,
``aget_respuesta``…), que despachan la E/S a un hilo con
``anyio.to_thread.run_sync`` — el backend en memoria no tiene E/S y responde en
el propio loop. Se descartó ``redis.asyncio``: un cliente asíncrono queda atado
al loop que lo creó (la suite abre uno por ``TestClient``) y exigiría un segundo
pool de conexiones para los llamadores síncronos. Un salto a un hilo cuesta
décimas de milisegundo; lo que había que evitar era parar el loop, no el hilo.
``tests/test_async_handlers_no_blocking_io.py`` vigila los wrappers async de
este módulo.

Capas de caché del sistema
--------------------------

Este módulo es una de varias. La tabla existe porque la pregunta que más cuesta
responder tras una ingesta no es «¿hay caché?» sino «¿quién invalida cuál?», y
la respuesta estaba repartida por siete ficheros. ``api/cache.py`` —una fachada
de 57 líneas sobre este módulo, con su propio ``cache_key``— se retiró el
2026-09-03 justo por eso: era una capa más que contar sin ser una capa más.

============================== ==================================== =========================================
Capa                           Qué guarda                           Quién la invalida tras una ingesta
============================== ==================================== =========================================
``shared/cache`` (este)        Respuestas de endpoints por           **Nadie: expira por TTL.** Es la
                               namespace (``api``, ``analytics``,    decisión, no un olvido — la mayoría de
                               ``llm_resumen``…); las de             los namespaces tienen TTL de 60-300 s.
                               ``cache_response``, ya serializadas
                               y con su ``ETag``
                                                                     Las invalidaciones puntuales por acción
                                                                     del usuario (no por ingesta) usan
                                                                     :func:`invalidate_user_scoped` y
                                                                     :func:`invalidate_organization_scoped`.
``services/_data_cache``       Agregados de solo lectura de la       La **señal de ingesta**: el scraper
(``SignalAwareCache``)         capa de servicios (señales de          escribe la marca al terminar y la
                               scoring)                              siguiente lectura recarga. Es la única
                                                                     capa que se entera de la ingesta sola.
``shared/cache_signal``        La marca de tiempo de esa señal       Se **escribe** en la ingesta (event log
                               (event log de Postgres + fichero      de Postgres); las lecturas se memoizan
                               centinela como fallback)              5 s.
ETag (``api/middleware``)      Nada en servidor: emite ``ETag`` y    El **cuerpo de la respuesta**. Si el
                               responde 304 (respeta la que ya       dato cambia, el hash cambia y el 304
                               trae una respuesta de                 deja de emitirse. No hay que invalidar.
                               ``cache_response``)
``functools.lru_cache``        Config derivada y cara de recalcular  Nadie en caliente: **muere con el
de proceso                     (claves de firma, catálogos i18n,     proceso**. Lo que sí se invalida a mano
                               versión del servicio)                 es ``shared/signing`` tras rotar clave
                                                                     (``reload_keys``).
``api/model_cache``            El clasificador ML cargado en         La **activación de versión**
                               memoria                               (``POST /models/{n}/activate/{v}``),
                                                                     explícitamente. No la ingesta.
Nonce store                    Nonces OAuth de un solo uso           TTL de ``cachetools.TTLCache`` (o la
(``shared/auth_core``)                                               tabla equivalente). Ajeno a la ingesta.
Rate limiting — Redis          Ventana deslizante por clave          TTL de la propia ventana.
(``services/rate_limiting``)
Rate limiting — Postgres       Lo mismo, en la tabla ``rate_limits`` La poda de la ventana. Es el fallback
(``services/rate_limiting``)                                         cuando no hay Redis; los dos backends
                                                                     nunca se coordinan entre sí.
============================== ==================================== =========================================

Lo que **desapareció** de esta tabla el 2026-09-03: el store en memoria de los
jobs de export asíncrono (``api/routes/exports.py``), que era un ``dict`` de
proceso con TTL de 15 minutos. Se retiró con los endpoints que lo usaban (ver
``docs/rfc/2026-09-03-rfc-retirada-exports-asincronos.md``).
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import inspect
import json
import math
import os
import threading
import time
import typing
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, TypeVar

import anyio.to_thread
from pydantic import BaseModel, SecretStr, TypeAdapter, ValidationError
from starlette.responses import Response

from observability.logging import get_logger
from shared.etag import etag_debil

log = get_logger(__name__)

_MEMORY_MAX_SIZE = 256  # entradas máximas por namespace en modo memory

#: Tiempo máximo de una operación contra Redis (segundos). Sin él, un Redis
#: colgado —TCP abierto que no responde— dejaba el hilo esperando para siempre;
#: y cuando la llamada corría en el event loop, era el proceso entero el que se
#: paraba. Medio segundo es dos órdenes de magnitud sobre lo que tarda un GET
#: sano en la misma región.
_REDIS_SOCKET_TIMEOUT_S = 0.5
#: Tiempo máximo para abrir una conexión nueva con Redis (segundos).
_REDIS_CONNECT_TIMEOUT_S = 1.0
#: Tras un fallo, cuánto tiempo se salta Redis y se sirve del respaldo en
#: memoria (segundos). Corto a propósito: su trabajo es que un Redis caído no
#: cueste un timeout **por petición**; pasado el plazo, la siguiente operación
#: vuelve a probar.
_REDIS_BREAKER_S = 15.0

#: Namespace de las respuestas de la API REST. Era el ``_NAMESPACE`` privado de
#: ``api/cache.py``; se conserva con el mismo valor para no invalidar de golpe
#: las entradas vivas en Redis al retirar aquella fachada.
API_NAMESPACE = "api"


def cache_key(*parts: Any) -> str:
    """Clave determinista a partir de varios componentes.

    Formato conservado tal cual venía de ``api/cache.py``
    (``licsap:`` + los 16 primeros hex de un MD5): cambiarlo habría dejado
    huérfanas las entradas ya escritas en Redis, que es exactamente el efecto
    que se quería evitar al unificar las dos capas.

    MD5 sin ``usedforsecurity``: es un identificador de caché, no un resumen
    criptográfico; nadie autentica nada con esto.
    """
    raw = ":".join(str(p) for p in parts)
    return "licsap:" + hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()[:16]


#: Namespace de las respuestas del LLM (C5.5).
LLM_NAMESPACE = "llm_respuestas"

#: TTL de una respuesta cacheada. 24 h, como pide el ítem.
#:
#: El límite no es el modelo sino el **corpus**: el contexto se reconstruye en
#: cada request y su huella entra en la clave, así que un pliego nuevo invalida
#: la entrada por sí solo. Lo que el TTL cubre es lo que la huella no ve — un
#: cambio de temperatura del proveedor, un modelo re-desplegado con el mismo
#: nombre — y para eso un día es suficiente.
LLM_CACHE_TTL_SECONDS = 86_400


def llm_cache_key(
    *,
    modo: str,
    modelo: str,
    prompt_version: str,
    contexto: Any,
) -> str:
    """Clave de una respuesta del LLM: modo + modelo + versión de prompt + contexto.

    Los cuatro componentes son necesarios y ninguno es redundante:

    - **modo** y **modelo** cambian la respuesta con el mismo contexto.
    - **prompt_version** es el hash del *system prompt* vigente, no un número a
      mano. Sin él, cambiar el prompt —como hizo C5.3 al pedir citas— seguiría
      sirviendo durante 24 h respuestas generadas bajo el prompt anterior, sin
      las citas que la UI ya espera. Un número manual sirve igual hasta el día
      que alguien olvide subirlo, que es el día que importa.
    - **contexto**: la huella de los documentos y fragmentos enviados. Es lo que
      hace que un pliego recién indexado invalide la entrada.
    """
    return cache_key("llm", modo, modelo, prompt_version, contexto)


# ---------------------------------------------------------------------------
# Respuesta cacheada por ``cache_response``
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _RespuestaCacheada:
    """Una respuesta de endpoint lista para servir: el JSON exacto y su ``ETag``.

    Se guarda **serializada** y no como ``dict``: en un acierto el cuerpo sale
    tal cual, sin volver a validarlo contra el ``response_model`` ni a
    serializarlo, que era trabajo de CPU dentro del event loop en cada acierto.
    La ``ETag`` se calcula una sola vez, al guardar, con la misma fórmula que
    el ``ETagMiddleware`` (:func:`shared.etag.etag_debil`): así el middleware no
    hashea el cuerpo en cada acierto, y un fallo y un acierto del mismo cuerpo
    llevan la misma etiqueta.
    """

    cuerpo: bytes
    etag: str


#: Prefijo de una respuesta cacheada en Redis. Las entradas anteriores a este
#: formato (un ``dict`` en JSON) no lo llevan y se tratan como fallo: se
#: recalculan y se sobrescriben, sin mezclar formatos. Mientras convivan dos
#: versiones en un despliegue, cada una ignora lo que escribe la otra.
_MARCA_RESPUESTA = "tf-respuesta-v1\n"


def _codificar_respuesta(entrada: _RespuestaCacheada) -> str:
    """``marca + etag + "\\n" + cuerpo``: se parte sin parsear JSON."""
    return f"{_MARCA_RESPUESTA}{entrada.etag}\n{entrada.cuerpo.decode('utf-8')}"


def _decodificar_respuesta(crudo: object) -> _RespuestaCacheada | None:
    """Inversa de :func:`_codificar_respuesta`; ``None`` si no tiene ese formato."""
    if isinstance(crudo, bytes):
        crudo = crudo.decode("utf-8", errors="replace")
    if not isinstance(crudo, str) or not crudo.startswith(_MARCA_RESPUESTA):
        return None
    etag, separador, cuerpo = crudo[len(_MARCA_RESPUESTA) :].partition("\n")
    if not separador or not etag:
        return None
    return _RespuestaCacheada(cuerpo=cuerpo.encode("utf-8"), etag=etag)


def _como_respuesta(valor: object) -> _RespuestaCacheada | None:
    return valor if isinstance(valor, _RespuestaCacheada) else None


def _segundos_redis(ttl: float) -> int:
    """TTL entero para ``SETEX``: nunca 0, que Redis rechaza como plazo inválido."""
    return max(1, math.ceil(ttl))


# ---------------------------------------------------------------------------
# Backend abstracto (duck-typed Protocol)
# ---------------------------------------------------------------------------


class _MemoryBackend:
    """Cache en memoria con LRU eviction y TTL. Thread-safe."""

    def __init__(self, max_size: int = _MEMORY_MAX_SIZE) -> None:
        self._store: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._lock = threading.Lock()
        self._max_size = max_size

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if expires_at != -1 and time.monotonic() > expires_at:
                self._store.pop(key, None)
                return None
            # LRU: mover al final (most recently used)
            self._store.move_to_end(key)
            return value

    def set(self, key: str, value: Any, ttl: float = 60.0) -> None:
        with self._lock:
            expires_at = -1 if ttl <= 0 else time.monotonic() + ttl
            if key in self._store:
                self._store[key] = (value, expires_at)
                self._store.move_to_end(key)
                return
            # Evicción: primero los expirados
            if len(self._store) >= self._max_size:
                now = time.monotonic()
                expired = [k for k, (_, exp) in self._store.items() if exp != -1 and exp < now]
                for k in expired:
                    self._store.pop(k, None)
            # Luego LRU si aún hace falta
            while len(self._store) >= self._max_size:
                self._store.popitem(last=False)
            self._store[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def keys(self, pattern: str = "*") -> list[str]:
        with self._lock:
            now = time.monotonic()
            all_keys = [k for k, (_, exp) in self._store.items() if exp == -1 or exp > now]
        if pattern == "*":
            return all_keys
        # Simple glob: solo soportamos "prefix*"
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            return [k for k in all_keys if k.startswith(prefix)]
        return [k for k in all_keys if k == pattern]

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

    # -- respuestas de ``cache_response`` -----------------------------------

    def get_respuesta(self, key: str) -> _RespuestaCacheada | None:
        return _como_respuesta(self.get(key))

    def set_respuesta(self, key: str, entrada: _RespuestaCacheada, ttl: float = 60.0) -> None:
        self.set(key, entrada, ttl)

    # -- variantes para ``async def`` ---------------------------------------
    #
    # Mismo contrato que en ``_RedisBackend``, para que el llamador async no
    # tenga que distinguir backends. Aquí no hay E/S —un ``dict`` con un lock
    # que nadie retiene más que unos microsegundos—, así que se responde en el
    # propio event loop: un salto a un hilo costaría más que la operación.

    async def aget(self, key: str) -> Any | None:
        return self.get(key)

    async def aset(self, key: str, value: Any, ttl: float = 60.0) -> None:
        self.set(key, value, ttl)

    async def aget_respuesta(self, key: str) -> _RespuestaCacheada | None:
        return self.get_respuesta(key)

    async def aset_respuesta(
        self, key: str, entrada: _RespuestaCacheada, ttl: float = 60.0
    ) -> None:
        self.set_respuesta(key, entrada, ttl)


class _RedisBackend:
    """Cache Redis con serialización JSON. Falla en silencio a Memory.

    **Cortacircuitos.** Toda llamada al cliente lleva ``socket_timeout``
    (:data:`_REDIS_SOCKET_TIMEOUT_S`), y el primer fallo —timeout, conexión
    rechazada, lo que sea— abre el circuito durante :data:`_REDIS_BREAKER_S`:
    en ese plazo ni se intenta Redis y las operaciones van a un
    :class:`_MemoryBackend` de respaldo, el mismo fallback a memoria que ya se
    aplicaba al arrancar. Sin esto, con Redis colgado cada operación pagaba su
    timeout, y con el cliente sin timeout la esperaba entera. Pasado el plazo,
    la siguiente operación vuelve a probar Redis; si responde, el respaldo se
    vacía, porque sus entradas son de la caída y ninguna invalidación las
    alcanzaría después.

    Un error al **decodificar** un valor no abre el circuito: es un dato raro,
    no un Redis caído, y se trata como fallo de caché.

    Los atributos del cortacircuitos tienen valor de clase para que un backend
    construido sin ``__init__`` (``tests/test_shared_cache.py`` lo hace así para
    inyectar un cliente simulado) funcione igual. Las carreras entre hilos sobre
    ellos solo pueden costar una prueba de más contra Redis o una entrada de
    respaldo perdida: es una caché.
    """

    #: Instante (``time.monotonic``) hasta el que se salta Redis.
    _saltar_hasta: float = 0.0
    #: ``True`` si el respaldo recibió escrituras durante la caída.
    _respaldo_usado: bool = False
    _respaldo: _MemoryBackend | None = None

    def __init__(self, url: str, namespace: str = "", *, password: str | None = None) -> None:
        import redis as redis_lib
        from redis.backoff import NoBackoff
        from redis.retry import Retry

        self._ns = f"{namespace}:" if namespace else ""
        self._respaldo = _MemoryBackend()
        # `retry` explícito con un solo reintento y sin espera: el valor por
        # defecto cambia entre versiones de redis-py (la 6 pasó a tres
        # reintentos con backoff exponencial de hasta varios segundos), y con
        # él el tiempo máximo de una operación dejaba de ser el de arriba. Un
        # reintento cubre la conexión del pool que el servidor cerró por
        # inactividad sin disparar el cortacircuitos.
        #
        # `password`: `REDIS_PASSWORD` (obligatoria en prod) puede venir aparte
        # de la URL, como la leen `llm/budget.py` y el rate limiter. Sin ella,
        # contra un Redis con `requirepass` el PING fallaba y el namespace se
        # quedaba en memoria para siempre. Si la URL ya trae contraseña,
        # redis-py da prioridad a la de la URL.
        self._r: Any = redis_lib.Redis.from_url(
            url,
            password=password,
            decode_responses=True,
            socket_connect_timeout=_REDIS_CONNECT_TIMEOUT_S,
            socket_timeout=_REDIS_SOCKET_TIMEOUT_S,
            retry=Retry(NoBackoff(), 1),
        )
        self._r.ping()

    def _k(self, key: str) -> str:
        return f"{self._ns}{key}"

    # -- cortacircuitos -----------------------------------------------------

    def _memoria(self) -> _MemoryBackend:
        respaldo = self._respaldo
        if respaldo is None:
            respaldo = self._respaldo = _MemoryBackend()
        return respaldo

    def _redis_activo(self) -> bool:
        return time.monotonic() >= self._saltar_hasta

    def _registrar_fallo(self, operacion: str, exc: BaseException) -> None:
        self._saltar_hasta = time.monotonic() + _REDIS_BREAKER_S
        log.warning(
            "shared_cache_redis_breaker_abierto",
            namespace=self._ns.rstrip(":"),
            operacion=operacion,
            error=str(exc),
            segundos=_REDIS_BREAKER_S,
        )

    def _registrar_exito(self) -> None:
        if self._respaldo_usado:
            self._respaldo_usado = False
            self._memoria().clear()
            log.info("shared_cache_redis_recuperado", namespace=self._ns.rstrip(":"))

    def _guardar_en_respaldo(self, key: str, valor: Any, ttl: float) -> None:
        self._respaldo_usado = True
        self._memoria().set(key, valor, ttl)

    # -- operaciones --------------------------------------------------------

    def get(self, key: str) -> Any | None:
        if not self._redis_activo():
            return self._memoria().get(key)
        try:
            raw = self._r.get(self._k(key))
        except Exception as exc:
            self._registrar_fallo("get", exc)
            return self._memoria().get(key)
        self._registrar_exito()
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError) as exc:
            log.debug("shared_cache_redis_get_error", key=key, error=str(exc))
            return None

    def set(self, key: str, value: Any, ttl: float = 60.0) -> None:
        if not self._redis_activo():
            self._guardar_en_respaldo(key, value, ttl)
            return
        try:
            serialized = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError) as exc:
            log.debug("shared_cache_redis_set_error", key=key, error=str(exc))
            return
        try:
            if ttl > 0:
                self._r.setex(self._k(key), _segundos_redis(ttl), serialized)
            else:
                self._r.set(self._k(key), serialized)
        except Exception as exc:
            self._registrar_fallo("set", exc)
            self._guardar_en_respaldo(key, value, ttl)
            return
        self._registrar_exito()

    def get_respuesta(self, key: str) -> _RespuestaCacheada | None:
        """La respuesta de ``cache_response`` guardada en ``key``, o ``None``."""
        if not self._redis_activo():
            return _como_respuesta(self._memoria().get(key))
        try:
            raw = self._r.get(self._k(key))
        except Exception as exc:
            self._registrar_fallo("get_respuesta", exc)
            return _como_respuesta(self._memoria().get(key))
        self._registrar_exito()
        return _decodificar_respuesta(raw)

    def set_respuesta(self, key: str, entrada: _RespuestaCacheada, ttl: float = 60.0) -> None:
        if not self._redis_activo():
            self._guardar_en_respaldo(key, entrada, ttl)
            return
        raw = _codificar_respuesta(entrada)
        try:
            if ttl > 0:
                self._r.setex(self._k(key), _segundos_redis(ttl), raw)
            else:
                self._r.set(self._k(key), raw)
        except Exception as exc:
            self._registrar_fallo("set_respuesta", exc)
            self._guardar_en_respaldo(key, entrada, ttl)
            return
        self._registrar_exito()

    def delete(self, key: str) -> None:
        # El respaldo se limpia siempre: puede guardar la entrada de una caída.
        self._memoria().delete(key)
        if not self._redis_activo():
            return
        try:
            self._r.delete(self._k(key))
        except Exception as exc:
            self._registrar_fallo("delete", exc)
            return
        self._registrar_exito()

    def clear(self) -> None:
        """Elimina solo las keys con el namespace actual (no flushdb)."""
        self._memoria().clear()
        if not self._redis_activo():
            return
        try:
            pattern = f"{self._ns}*" if self._ns else "*"
            cursor = 0
            while True:
                cursor, keys = self._r.scan(cursor=cursor, match=pattern, count=100)
                if keys:
                    self._r.delete(*keys)
                if cursor == 0:
                    break
        except Exception as exc:
            self._registrar_fallo("clear", exc)
            return
        self._registrar_exito()

    def keys(self, pattern: str = "*") -> list[str]:
        if not self._redis_activo():
            return self._memoria().keys(pattern)
        try:
            full_pattern = f"{self._ns}{pattern}"
            result: list[str] = []
            cursor = 0
            ns_len = len(self._ns)
            while True:
                cursor, keys = self._r.scan(cursor=cursor, match=full_pattern, count=100)
                result.extend(k[ns_len:] for k in keys)
                if cursor == 0:
                    break
        except Exception as exc:
            self._registrar_fallo("keys", exc)
            return self._memoria().keys(pattern)
        self._registrar_exito()
        return result

    # -- variantes para ``async def``: la E/S va a un hilo -------------------

    async def aget(self, key: str) -> Any | None:
        return await anyio.to_thread.run_sync(self.get, key)

    async def aset(self, key: str, value: Any, ttl: float = 60.0) -> None:
        await anyio.to_thread.run_sync(self.set, key, value, ttl)

    async def aget_respuesta(self, key: str) -> _RespuestaCacheada | None:
        return await anyio.to_thread.run_sync(self.get_respuesta, key)

    async def aset_respuesta(
        self, key: str, entrada: _RespuestaCacheada, ttl: float = 60.0
    ) -> None:
        await anyio.to_thread.run_sync(self.set_respuesta, key, entrada, ttl)


# ---------------------------------------------------------------------------
# Singleton factory por namespace
# ---------------------------------------------------------------------------

_instances: dict[str, _MemoryBackend | _RedisBackend] = {}
_instances_lock = threading.Lock()
_redis_available: bool | None = None


def get_cache(namespace: str = "default") -> _MemoryBackend | _RedisBackend:
    """Devuelve el backend de cache para ``namespace``.

    Singleton por namespace: primera llamada crea la instancia (Redis si
    ``REDIS_URL`` está configurado, Memory como fallback).

    Args:
        namespace: Identificador lógico del cache (ej. "api", "analytics").
                   Prefija todas las keys en Redis para evitar colisiones.
    """
    if namespace in _instances:
        return _instances[namespace]

    with _instances_lock:
        # Double-checked locking
        if namespace in _instances:
            return _instances[namespace]

        backend: _MemoryBackend | _RedisBackend = _try_redis(namespace)
        _instances[namespace] = backend
        return backend


async def aget_cache(namespace: str = "default") -> _MemoryBackend | _RedisBackend:
    """:func:`get_cache` para ``async def``.

    Una vez creado el backend es una lectura de ``dict``. La **primera** vez lo
    construye, y con Redis eso incluye un ``PING`` con timeout de conexión: ese
    único caso va a un hilo para no parar el loop mientras se conecta.
    """
    existente = _instances.get(namespace)
    if existente is not None:
        return existente
    return await anyio.to_thread.run_sync(get_cache, namespace)


def es_compartida(backend: _MemoryBackend | _RedisBackend) -> bool:
    """True si lo que se escriba en ``backend`` lo verá otro proceso.

    Lo necesita quien escribe en la caché **para otro**: un job que calienta
    entradas que servirá la API. Con el backend de memoria esas escrituras
    mueren con el proceso del job, y hacerlas es gasto sin efecto.
    """
    return isinstance(backend, _RedisBackend)


def _try_redis(namespace: str) -> _MemoryBackend | _RedisBackend:
    """Intenta conectar con Redis; si falla devuelve MemoryBackend.

    Siempre falla suavemente a MemoryBackend — es preferible tener datos
    potencialmente stale a devolver 500.  El error se loggea a nivel
    ``error`` para que monitoreo lo capte.  Si el paquete ``redis`` no
    está instalado, se hace fallback silencioso con un warning.
    """
    try:
        from config import settings

        if not settings.REDIS_URL:
            return _MemoryBackend()

        backend = _RedisBackend(
            settings.REDIS_URL, namespace=namespace, password=_contrasena_redis(settings)
        )
        log.info("shared_cache_redis_connected", namespace=namespace)
        return backend
    except ImportError as exc:
        log.warning(
            "shared_cache_redis_module_missing",
            error=str(exc),
            fallback="memory",
        )
        return _MemoryBackend()
    except Exception as exc:
        log.error(
            "shared_cache_redis_unavailable",
            error=str(exc),
            env=os.getenv("ENV", ""),
            fallback="memory",
        )
        return _MemoryBackend()


def _contrasena_redis(settings_obj: object) -> str | None:
    """``REDIS_PASSWORD`` en claro, o ``None`` si no hay (``SecretStr`` o ``str``)."""
    valor = getattr(settings_obj, "REDIS_PASSWORD", None)
    if isinstance(valor, SecretStr):
        valor = valor.get_secret_value()
    return valor if isinstance(valor, str) and valor else None


def reset_cache(namespace: str | None = None) -> None:
    """Elimina instancias del singleton (útil en tests o tras cambio de config).

    Args:
        namespace: Si se da, elimina solo ese namespace. Si None, elimina todos.
    """
    global _redis_available
    with _instances_lock:
        if namespace is None:
            _instances.clear()
            _redis_available = None
        else:
            _instances.pop(namespace, None)


# ---------------------------------------------------------------------------
# Decorador de cache para endpoints (con protección anti-estampida)
# ---------------------------------------------------------------------------

T = TypeVar("T")
_CACHE_LOCKS_MAX_SIZE = 1024  # LRU global — ver docstring de _get_cache_lock
_cache_locks: OrderedDict[str, asyncio.Lock] = OrderedDict()
_cache_locks_mutex = threading.Lock()


def _get_cache_lock(key: str) -> asyncio.Lock:
    """Obtiene (o crea) un ``asyncio.Lock`` por *key* de forma thread-safe.

    LRU-acotado a ``_CACHE_LOCKS_MAX_SIZE``: sin esto, cada combinación
    distinta de filtros que llega a un endpoint cacheado deja un ``Lock``
    vivo para siempre en este dict aunque su entrada ya haya expirado y sido
    evictada de ``_MemoryBackend`` — un memory leak que crece con el uptime
    del proceso, no con el volumen de datos. Evictar el lock menos usado no
    rompe la protección anti-estampida de una request ya en vuelo (esa
    coroutine ya tiene su propia referencia al ``Lock``); en el peor caso,
    una nueva request para la misma key llegada justo después de la eviction
    obtiene un ``Lock`` distinto y no queda deduplicada — mismo trade-off que
    la eviction LRU del caché de datos.
    """
    with _cache_locks_mutex:
        lock = _cache_locks.get(key)
        if lock is not None:
            _cache_locks.move_to_end(key)
            return lock
        if len(_cache_locks) >= _CACHE_LOCKS_MAX_SIZE:
            _cache_locks.popitem(last=False)
        lock = asyncio.Lock()
        _cache_locks[key] = lock
        return lock


@asynccontextmanager
async def single_flight(key: str) -> AsyncIterator[None]:
    """Serializa el recálculo de ``key`` entre corrutinas concurrentes.

    Es la misma protección anti-estampida que aplica :func:`cache_response`,
    expuesta para los handlers que gestionan su propio par
    ``cache_get``/``cache_set`` porque devuelven cabeceras (``X-Cache``) que el
    decorador no modela.

    El patrón de uso es *comprobar, entrar, volver a comprobar*: la segunda
    lectura dentro del bloque es obligatoria, porque quien esperaba en el lock
    lo hacía precisamente mientras otra corrutina rellenaba la entrada.

    Sin esto, N peticiones simultáneas fallan el caché a la vez y las N
    ejecutan la consulta cara. En producción se midió el caso: dos
    ``/meta/filters`` y cuatro ``/analytics/overview`` en el mismo segundo,
    cada uno arrastrando su propio escaneo y reteniendo una conexión del pool
    (12 slots) durante decenas de segundos.
    """
    async with _get_cache_lock(key):
        yield


#: Parámetro que :func:`cache_response` añade a la firma **pública** del
#: endpoint (``__signature__``) para que FastAPI le inyecte la respuesta
#: temporal de la petición. Que llegue es lo que distingue una llamada HTTP de
#: una llamada directa desde Python, y sus cabeceras (las que fije una
#: dependencia) se copian a la respuesta final, como hace FastAPI. No aparece en
#: el OpenAPI: FastAPI no documenta los parámetros de tipo ``Response``.
_PARAM_RESPUESTA = "_cache_response_temporal"


def _json_canonico(valor: object) -> str:
    """JSON compacto y con claves ordenadas: la misma entrada, la misma cadena."""
    return json.dumps(valor, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _marca_de_identidad(campo: str, valor: object) -> str:
    """Fragmento exacto con el que ``campo`` aparece en una clave de caché.

    Es lo que buscan :func:`invalidate_user_scoped` y
    :func:`invalidate_organization_scoped`. Lleva las comillas de cierre del
    valor, así que ``u1`` no casa con ``u10``, y ningún parámetro puede
    imitarlo: dentro del JSON de un parámetro las comillas van escapadas.
    """
    return f"{_json_canonico(campo)}:{_json_canonico(str(valor))}"


def _clave_de_peticion(
    nombre: str, kwargs: dict[str, Any], *, user_scoped: bool, huella: str
) -> str:
    """Clave de caché de una llamada: ``<función>|<huella>|<JSON canónico de la llamada>``.

    ``huella`` identifica la forma de la respuesta (ver
    :meth:`_Serializador.ahuella`): un despliegue que cambia el DTO no sirve
    las entradas que guardó el anterior.

    **Sin ambigüedad.** Hasta 2026-09 la clave era ``k:v`` unido por ``|``, y
    un valor con esos separadores fabricaba la clave de **otra** consulta:
    ``?ccaa=Madrid|cpv:72`` ocupaba la entrada de ``?ccaa=Madrid&cpv=72``. En
    un endpoint ``user_scoped=False`` eso servía una respuesta equivocada a
    todos los usuarios durante el TTL. En JSON cada valor es una cadena con sus
    comillas y sus escapes: dos llamadas distintas no pueden dar el mismo texto.

    El prefijo ``<función>|`` se conserva porque es por donde las
    invalidaciones buscan (``keys("<función>|*")``); el nombre es un
    identificador de Python y no puede contener ``|``.

    Función aparte y síncrona porque trabaja sobre los **parámetros** de la
    petición (unos pocos escalares y, como mucho, un modelo de filtros), no
    sobre la respuesta: es microsegundos de CPU y puede correr en el loop.
    """
    identidad: dict[str, str] = {}
    parametros: list[list[str]] = []
    for k, v in sorted(kwargs.items()):
        if k.startswith("_"):
            # Las dependencias de autenticación pueden alterar la
            # respuesta; cuando lo hacen, la identidad entra en la clave
            # y dos usuarios nunca comparten entrada. Los endpoints que
            # declaran `user_scoped=False` afirman lo contrario —su
            # respuesta solo depende de los query params— y ahí meter el
            # `user_key` solo multiplicaba por N el mismo cálculo.
            if user_scoped and isinstance(v, dict) and v.get("user_key"):
                identidad["principal"] = str(v["user_key"])
                if v.get("organization_id") is not None:
                    identidad["organization"] = str(v["organization_id"])
            continue
        if isinstance(v, BaseModel):
            parametros.append([k, v.model_dump_json(exclude_none=True)])
        elif v is not None:
            parametros.append([k, str(v)])
    return f"{nombre}|{huella}|{_json_canonico({**identidad, 'parametros': parametros})}"


def _adaptador_de_retorno(func: Callable[..., Any]) -> TypeAdapter[Any] | None:
    """``TypeAdapter`` del tipo de retorno anotado, o ``None`` si no lo hay.

    Es el mismo tipo con el que FastAPI valida y serializa la respuesta: en
    las rutas cacheadas el ``response_model`` coincide con la anotación de
    retorno (``tests/test_cache_response_http.py`` lo verifica ruta a ruta).
    ``None`` para funciones sin anotación o con una que no se puede resolver
    —tipos locales de un test—: entonces se serializa como lo haría FastAPI
    sin ``response_model``.
    """
    try:
        retorno = typing.get_type_hints(func).get("return")
    except Exception:  # anotaciones irresolubles: se cae al camino sin modelo
        log.debug("cache_response_sin_tipo_de_retorno", func=func.__name__, exc_info=True)
        return None
    if retorno is None or retorno is Any or retorno is type(None):
        return None
    try:
        return TypeAdapter(retorno)
    except Exception:  # un tipo que pydantic no sabe adaptar: mismo camino
        log.debug("cache_response_tipo_no_adaptable", func=func.__name__, exc_info=True)
        return None


class _Serializador:
    """Convierte el resultado del handler en el JSON que habría servido FastAPI.

    Con tipo de retorno hace lo mismo que FastAPI con el ``response_model``:
    ``validate_python`` (un no-op para una instancia del propio modelo; un
    ``dict`` sí se valida, y una subclase se recorta a los campos declarados)
    y ``dump_json(by_alias=True)``. Sin tipo, ``jsonable_encoder`` +
    ``json.dumps`` compacto, que es lo que renderiza ``JSONResponse``.

    Un fallo de validación se relanza como ``ResponseValidationError``, igual
    que FastAPI: el ``ValidationError`` de pydantic es un ``ValueError`` y el
    manejador de ``api/errors.py`` lo convertiría en un 400, cuando un
    handler que devuelve algo que no cumple su contrato es un 500.

    Corre siempre en un hilo, junto al handler o justo después: es CPU
    proporcional al tamaño de la respuesta.
    """

    def __init__(self, func: Callable[..., Any]) -> None:
        self._func = func
        self._adaptador: TypeAdapter[Any] | None = None
        self._resuelto = False
        self._huella: str | None = None
        self._lock = threading.Lock()

    def _obtener_adaptador(self) -> TypeAdapter[Any] | None:
        if not self._resuelto:
            with self._lock:
                if not self._resuelto:
                    self._adaptador = _adaptador_de_retorno(self._func)
                    self._resuelto = True
        return self._adaptador

    def _calcular_huella(self) -> str:
        """Huella corta del esquema JSON de salida del tipo de retorno."""
        if self._huella is None:
            adaptador = self._obtener_adaptador()
            if adaptador is None:
                huella = "sin-tipo"
            else:
                try:
                    esquema = adaptador.json_schema(mode="serialization", by_alias=True)
                    huella = hashlib.blake2b(
                        _json_canonico(esquema).encode("utf-8"), digest_size=6
                    ).hexdigest()
                except Exception:  # un tipo sin esquema JSON: la caché funciona igual
                    log.debug("cache_response_sin_esquema", func=self._func.__name__, exc_info=True)
                    huella = "sin-esquema"
            self._huella = huella
        return self._huella

    async def ahuella(self) -> str:
        """Huella de la forma de la respuesta, para la clave de caché.

        Antes, un acierto devolvía el ``dict`` cacheado y FastAPI lo volvía a
        validar contra el ``response_model``: tras un despliegue que cambiaba
        el DTO, la entrada vieja se rellenaba con defaults o daba un 500 hasta
        que caducaba. Ahora el cuerpo sale tal cual, así que la forma entra en
        la clave: un DTO distinto es una clave distinta, y lo que guardó el
        despliegue anterior simplemente no se encuentra.

        Se calcula una vez por endpoint, en un hilo (generar el esquema de un
        modelo grande son milisegundos de CPU); después es una lectura.
        """
        if self._huella is not None:
            return self._huella
        return await anyio.to_thread.run_sync(self._calcular_huella)

    def __call__(self, resultado: Any) -> _RespuestaCacheada:
        adaptador = self._obtener_adaptador()
        if adaptador is not None:
            try:
                valor = adaptador.validate_python(resultado, from_attributes=True)
            except ValidationError as exc:
                from fastapi.exceptions import ResponseValidationError

                errores = [
                    {**error, "loc": ("response", *error.get("loc", ()))}
                    for error in exc.errors(include_url=False)
                ]
                raise ResponseValidationError(errores, body=resultado) from exc
            cuerpo = adaptador.dump_json(valor, by_alias=True)
        else:
            from fastapi.encoders import jsonable_encoder

            cuerpo = json.dumps(
                jsonable_encoder(resultado),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        return _RespuestaCacheada(cuerpo=cuerpo, etag=etag_debil(cuerpo))


def _calcular_y_serializar(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    serializador: _Serializador,
) -> tuple[Any, _RespuestaCacheada]:
    """Handler síncrono + serialización en el mismo salto al hilo."""
    resultado = func(*args, **kwargs)
    return resultado, serializador(resultado)


def _respuesta_http(entrada: _RespuestaCacheada, temporal: Response) -> Response:
    """La respuesta HTTP de una entrada: el cuerpo tal cual y su ``ETag``.

    ``Cache-Control`` y ``Vary`` no se fijan aquí: los pone el
    ``ETagMiddleware``, que es quien sabe si la petición venía autenticada, y
    también es quien responde el 304 cuando ``If-None-Match`` nombra la
    etiqueta. Lo que sí se conserva es lo que FastAPI habría conservado: el
    ``status_code`` y las cabeceras que las dependencias fijaron en la
    respuesta temporal.
    """
    respuesta = Response(
        content=entrada.cuerpo,
        status_code=temporal.status_code or 200,
        media_type="application/json",
        headers={"ETag": entrada.etag},
    )
    respuesta.headers.raw.extend(temporal.headers.raw)
    return respuesta


#: Nombres de las clases de respuesta de Starlette/FastAPI, para reconocer una
#: anotación que no se pudo resolver (``from __future__ import annotations``).
_NOMBRES_DE_RESPUESTA_HTTP = frozenset(
    {
        "Response",
        "JSONResponse",
        "ORJSONResponse",
        "UJSONResponse",
        "HTMLResponse",
        "PlainTextResponse",
        "StreamingResponse",
        "FileResponse",
        "RedirectResponse",
    }
)


def _anotacion_de_respuesta_http(anotacion: object) -> bool:
    if isinstance(anotacion, type):
        return issubclass(anotacion, Response)
    if isinstance(anotacion, str):
        return anotacion.rsplit(".", 1)[-1] in _NOMBRES_DE_RESPUESTA_HTTP
    return False


def _firma_con_respuesta(func: Callable[..., Any]) -> inspect.Signature:
    """Firma de ``func`` más el parámetro por el que FastAPI inyecta la respuesta.

    Rechaza en el arranque —no en la primera petición— los handlers que ya
    reciben una ``Response``: FastAPI inyecta la respuesta temporal en un solo
    parámetro por endpoint, y con dos uno de ellos llegaría vacío.
    """
    firma = inspect.signature(func)
    try:
        resueltas = typing.get_type_hints(func)
    except Exception:  # anotaciones irresolubles: se mira el texto de la anotación
        resueltas = {}
    parametros = list(firma.parameters.values())
    for parametro in parametros:
        anotacion = resueltas.get(parametro.name, parametro.annotation)
        if parametro.name == _PARAM_RESPUESTA or _anotacion_de_respuesta_http(anotacion):
            raise TypeError(
                f"cache_response no admite handlers que reciben una Response "
                f"({func.__qualname__}.{parametro.name}): la respuesta la construye el "
                "decorador. Fija las cabeceras desde una dependencia."
            )
    nuevo = inspect.Parameter(_PARAM_RESPUESTA, inspect.Parameter.KEYWORD_ONLY, annotation=Response)
    posicion = next(
        (i for i, p in enumerate(parametros) if p.kind is inspect.Parameter.VAR_KEYWORD),
        len(parametros),
    )
    parametros.insert(posicion, nuevo)
    return firma.replace(parameters=parametros)


async def _entregar(entrada: _RespuestaCacheada, temporal: Response | None) -> Any:
    """Lo que devuelve el wrapper en un acierto.

    Por HTTP, la ``Response`` con el cuerpo ya serializado: FastAPI la entrega
    sin validarla ni serializarla otra vez. En una llamada directa desde
    Python (tests, scripts) se conserva el contrato de siempre —el valor
    cacheado como ``dict``—, decodificado en un hilo.
    """
    if temporal is not None:
        return _respuesta_http(entrada, temporal)
    return await anyio.to_thread.run_sync(json.loads, entrada.cuerpo)


def cache_response(
    ttl: int = 300,
    namespace: str = "analytics",
    *,
    cpu_bound: bool = False,
    user_scoped: bool = True,
) -> Callable[..., Any]:
    """Decorador que cachea respuestas de endpoints FastAPI.

    Características:
      - **Anti-estampida**: usa ``asyncio.Lock`` por clave para que si
        N peticiones idénticas llegan simultáneamente, solo 1 ejecute la
        función pesada y las demás esperen el resultado cacheado.
      - **Async-native**: el wrapper es ``async def``, lo que evita que
        FastAPI despache la llamada al threadpool *antes* de revisar caché.
        Si la función subyacente es síncrona, se ejecuta con
        ``anyio.to_thread.run_sync`` **dentro** del lock.
      - **Nada pesado en el event loop**: la E/S de Redis va a un hilo
        (``aget_respuesta``/``aset_respuesta``) y la serialización también,
        en el mismo salto que el handler cuando este es síncrono.
      - **Se guarda la respuesta serializada, con su ETag** (ver
        :class:`_RespuestaCacheada`). Por HTTP, el wrapper devuelve una
        ``Response`` con ese cuerpo tanto en el fallo como en el acierto: el
        mismo JSON y la misma etiqueta en los dos caminos, y FastAPI no
        revalida el ``dict`` entero contra el ``response_model`` en cada
        acierto. El ``response_model`` de la ruta sigue declarado, así que el
        OpenAPI no cambia.
      - **Llamada directa desde Python** (sin la respuesta temporal que
        inyecta FastAPI): contrato de siempre, el resultado del handler en un
        fallo y el valor cacheado como ``dict`` en un acierto. Para el modelo
        sin caché está ``__wrapped__``.

    Args:
        ttl: Tiempo de vida en segundos (default 5 min).
        namespace: Namespace del backend de cache.
        cpu_bound: si el handler hace trabajo pesado de CPU (agregación pandas),
            se ejecuta en el bulkhead ``API_CPU_BOUND_TOKENS`` en vez de competir
            por el threadpool general. Es lo que permite dimensionar ese pool
            para carga IO-bound sin repetir el incidente de CPU starvation que
            en su día lo dejó clavado en 4 hilos: quien tiene que estar acotada
            es la analítica, no las lecturas baratas.
        user_scoped: si la respuesta depende de **quién** pregunta. Por defecto
            sí, que es la opción segura: la clave incorpora el ``user_key`` de
            la dependencia de autenticación y dos identidades nunca comparten
            entrada. Ponerlo a ``False`` es afirmar que el handler es función
            pura de sus parámetros de consulta —que ya viajan en la clave— y
            hace que N usuarios compartan un único cálculo en vez de pagarlo N
            veces. Solo para datos globales: la analítica agregada lo es, el
            scoring personalizado y las novedades desde el último login no.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        is_sync = not inspect.iscoroutinefunction(func)
        serializador = _Serializador(func)
        firma_publica = _firma_con_respuesta(func)

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            temporal: Response | None = kwargs.pop(_PARAM_RESPUESTA, None)
            cache = await aget_cache(namespace)
            cache_key = _clave_de_peticion(
                func.__name__,
                kwargs,
                user_scoped=user_scoped,
                huella=await serializador.ahuella(),
            )

            # --- Fast path (no lock) ---
            entrada = await cache.aget_respuesta(cache_key)
            if entrada is not None:
                log.debug("cache_hit", key=cache_key, func=func.__name__)
                return await _entregar(entrada, temporal)

            # --- Stampede-protected slow path ---
            lock = _get_cache_lock(cache_key)
            async with lock:
                # Double-check inside lock
                entrada = await cache.aget_respuesta(cache_key)
                if entrada is not None:
                    log.debug("cache_hit_after_lock", key=cache_key, func=func.__name__)
                    return await _entregar(entrada, temporal)

                log.debug("cache_miss", key=cache_key, func=func.__name__)
                nueva: _RespuestaCacheada
                if is_sync:
                    limiter = None
                    if cpu_bound:
                        from shared.concurrency import cpu_limiter

                        limiter = cpu_limiter()
                    # Handler y serialización en el mismo salto: con
                    # `cpu_bound` la serialización también cuenta contra el
                    # bulkhead, que es donde debe estar el trabajo de CPU.
                    result, nueva = await anyio.to_thread.run_sync(
                        functools.partial(_calcular_y_serializar, func, args, kwargs, serializador),
                        limiter=limiter,
                    )
                else:
                    result = await func(*args, **kwargs)
                    nueva = await anyio.to_thread.run_sync(serializador, result)

                await cache.aset_respuesta(cache_key, nueva, ttl)

            if temporal is None:
                return result
            return _respuesta_http(nueva, temporal)

        # FastAPI lee la firma para decidir qué inyectar: con este parámetro
        # extra le pasa la respuesta temporal. `__wrapped__` (la función
        # desnuda, sin caché) conserva la firma original.
        wrapper.__dict__["__signature__"] = firma_publica
        return wrapper

    return decorator


def invalidate_user_scoped(namespace: str, func_name: str, user_key: str) -> int:
    """Borra las entradas cacheadas de ``func_name`` que pertenecen a un usuario.

    Para endpoints ``user_scoped`` cuya respuesta cambia por una acción del
    propio usuario y no por una nueva ingesta: sin esto, quien descarta una
    señal del Radar seguiría viéndola hasta que expirase el TTL, porque el
    ranking se sirve cacheado.

    Se filtra por contenido y no por prefijo: la clave la construye
    ``cache_response`` como JSON canónico, y el usuario va en su campo
    ``"principal"`` (ver :func:`_marca_de_identidad`: la marca no casa con otro
    usuario que empiece igual ni la puede imitar un parámetro). Devuelve
    cuántas entradas se borraron.

    Alcance: la instancia local con backend en memoria, todas con Redis. Con
    varias instancias y memoria, el resto sigue el TTL — por eso el cliente
    mantiene además su filtro optimista.
    """
    cache = get_cache(namespace)
    marca = _marca_de_identidad("principal", user_key)
    borradas = 0
    for key in cache.keys(f"{func_name}|*"):
        if marca in key:
            cache.delete(key)
            borradas += 1
    if borradas:
        log.debug("cache_invalidated_user_scoped", func=func_name, borradas=borradas)
    return borradas


def invalidate_organization_scoped(namespace: str, func_name: str, organization_id: int) -> int:
    """Borra las entradas de ``func_name`` calculadas para una organización.

    Un perfil de scoring con visibilidad de organización cambia el ranking de
    todos sus miembros, no solo el de quien lo guarda. La marca es el campo
    ``"organization"`` de la misma clave JSON que lleva ``"principal"`` y
    funciona tanto con el backend en memoria como con Redis.
    """
    cache = get_cache(namespace)
    marca = _marca_de_identidad("organization", organization_id)
    borradas = 0
    for key in cache.keys(f"{func_name}|*"):
        if marca in key:
            cache.delete(key)
            borradas += 1
    if borradas:
        log.debug(
            "cache_invalidated_organization_scoped",
            func=func_name,
            organization_id=organization_id,
            borradas=borradas,
        )
    return borradas


async def ainvalidate_user_scoped(namespace: str, func_name: str, user_key: str) -> int:
    """:func:`invalidate_user_scoped` para ``async def``: el ``SCAN`` va a un hilo.

    Con Redis la invalidación recorre las claves del namespace con ``SCAN`` y
    borra las del usuario: varios viajes de red, que desde un handler async
    tienen que salir del event loop.
    """
    return await anyio.to_thread.run_sync(invalidate_user_scoped, namespace, func_name, user_key)


async def ainvalidate_organization_scoped(
    namespace: str, func_name: str, organization_id: int
) -> int:
    """:func:`invalidate_organization_scoped` para ``async def`` (ver arriba)."""
    return await anyio.to_thread.run_sync(
        invalidate_organization_scoped, namespace, func_name, organization_id
    )
