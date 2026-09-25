"""Middlewares ASGI personalizados para la API REST.

* :class:`SecurityHeadersMiddleware` — Añade cabeceras de seguridad OWASP.
* :class:`ObservabilityMiddleware`   — ``X-Correlation-Id``, access log estructurado
  y coste estimado por request (Prometheus), en una sola capa.
* :class:`RateLimitMiddleware`       — Rate limiting por IP o API key; el almacén lo
  elige ``services.rate_limiting.get_rate_limiter`` (Redis o tabla ``rate_limits``)
  y la comprobación corre en un hilo, nunca en el event loop.
* :class:`ETagMiddleware`            — ETag/304 para respuestas GET JSON.
* :class:`_MaxBodyMiddleware`        — Rechaza bodies > 1 MB.
* :class:`_RejectNulMiddleware`      — Rechaza el byte NUL en path/query.

Todos diseñados para ser idempotentes y "fail-open" ante errores de infra, salvo
el rate limit, que ante un error de la BD deniega (``services.rate_limiting``).

Por qué todos son ASGI puro
---------------------------
Hasta 2026-09 cinco capas eran ``BaseHTTPMiddleware`` (rate limit, coste, access
log, ETag y correlation id). Cada una crea por petición un task group y un memory
stream y re-emite el cuerpo: todo lo que salía de la app atravesaba cinco relés,
los streams SSE incluidos. La API es **un solo proceso uvicorn** con un solo event
loop, así que ese coste lo paga cada petición de todas las demás.

Lo que ve el cliente no cambia, salvo en lo que era artefacto de esos relés:

* **Excepción antes de empezar a responder:** igual que antes. Sube intacta hasta
  el ``ServerErrorMiddleware`` de Starlette, que responde el 500 ``problem+json``
  por fuera de todo el stack (sin CORS ni correlation id, como siempre) y la
  relanza al servidor. El access log la registra como 500.
* **Excepción con la respuesta ya empezada** (un stream que revienta a medias):
  ``BaseHTTPMiddleware`` cerraba el cuerpo como si hubiera terminado bien y
  relanzaba después, así que el cliente recibía un cuerpo truncado con aspecto de
  completo. Ahora la excepción sube sin ese cierre y el servidor corta la
  conexión: el truncado se ve.
* **Troceado del cuerpo:** cada relé re-emitía la respuesta como stream
  (``more_body=True`` y un mensaje final vacío). La compresión, que va por fuera
  del ETag, trataba por eso *toda* respuesta como stream: comprimía también las
  menores que su ``minimum_size`` y quitaba ``Content-Length``. Ahora una
  respuesta de un solo mensaje le llega entera: las pequeñas salen sin comprimir
  y con ``Content-Length``, que es lo que dice su configuración.
* **contextvars:** ``call_next`` corría la app en otra task, con copia del
  contexto; ahora todo corre en la task de la petición. El correlation id se ve
  igual que antes en handlers, hilos del threadpool y logs.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
import uuid

from anyio import CapacityLimiter, to_thread
from starlette import status
from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import HTTPConnection
from starlette.responses import RedirectResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from structlog.contextvars import bind_contextvars, clear_contextvars

from observability.logging import get_logger
from services.rate_limiting import get_rate_limiter
from shared.etag import coincide_if_none_match, etag_debil

log = get_logger(__name__)


# ───────────────────────────── Security headers ─────────────────────────────


class SecurityHeadersMiddleware:
    """Añade cabeceras de seguridad recomendadas por OWASP.

    Implementado como middleware ASGI puro para evitar el overhead de
    ``BaseHTTPMiddleware`` (que bufferiza el body completo). Este middleware
    solo necesita interceptar los headers de la respuesta, no el body.

    Cabeceras añadidas:
    - ``X-Content-Type-Options: nosniff``
    - ``X-Frame-Options: DENY``
    - ``Referrer-Policy: strict-origin-when-cross-origin``
    - ``Permissions-Policy``: deshabilita APIs sensibles del navegador
    - ``Strict-Transport-Security``: solo si la request llega por HTTPS
    - ``Content-Security-Policy``: configurable, default seguro para JSON API
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        csp: str = "default-src 'none'; frame-ancestors 'none'; report-uri /api/v1/security/csp-report",
        hsts_max_age: int = 31_536_000,  # 1 año
    ) -> None:
        self.app = app
        self._csp = csp
        self._hsts = f"max-age={hsts_max_age}; includeSubDomains"
        # Pre-compute header pairs as bytes for performance
        self._base_headers: list[tuple[bytes, bytes]] = [
            (b"x-content-type-options", b"nosniff"),
            (b"x-frame-options", b"DENY"),
            (b"referrer-policy", b"strict-origin-when-cross-origin"),
            (
                b"permissions-policy",
                b"geolocation=(), microphone=(), camera=(), payment=(), usb=()",
            ),
            (b"content-security-policy", csp.encode()),
        ]
        self._hsts_header: tuple[bytes, bytes] = (
            b"strict-transport-security",
            self._hsts.encode(),
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Detectar si es HTTPS (directo o detrás de proxy)
        is_https = scope.get("scheme") == "https"
        if not is_https:
            # Check X-Forwarded-Proto en los headers de la request
            for header_name, header_value in scope.get("headers", []):
                if header_name == b"x-forwarded-proto" and header_value == b"https":
                    is_https = True
                    break

        async def _send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing_names = {h[0].lower() for h in headers}
                for name, value in self._base_headers:
                    if name not in existing_names:
                        headers.append((name, value))
                if is_https and b"strict-transport-security" not in existing_names:
                    headers.append(self._hsts_header)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, _send_with_security_headers)


# ───────────────────────────── Rate limiting ────────────────────────────────


def _trusted_client_ip(request: HTTPConnection) -> str:
    """Extrae la IP real del cliente validando proxies de confianza.

    Solo honra ``X-Forwarded-For`` si la conexión TCP directa viene de una IP
    en ``FORWARDED_ALLOW_IPS`` (configurado en settings). Esto evita que un
    cliente externo inyecte una IP falsa en la cabecera y eluda el rate-limit
    basado en IP.

    Returns:
        IP del cliente (string). Nunca lanza — devuelve "unknown" ante errores.
    """
    try:
        import ipaddress

        from config import settings

        allowed_proxies: set[str] = {
            ip.strip()
            for ip in getattr(settings, "FORWARDED_ALLOW_IPS", "127.0.0.1").split(",")
            if ip.strip()
        }
        direct_ip = request.client.host if request.client else None

        def _is_trusted_proxy(ip: str) -> bool:
            if "*" in allowed_proxies:
                return False
            try:
                candidate = ipaddress.ip_address(ip)
                return any(
                    candidate in ipaddress.ip_network(value, strict=False)
                    for value in allowed_proxies
                )
            except ValueError:
                return ip in allowed_proxies

        if "*" in allowed_proxies:
            # Semántica "un salto de confianza" para PaaS (Render): el único
            # peer TCP posible es el proxy de la plataforma, que APPENDEA la IP
            # real del cliente al final de X-Forwarded-For. El último hop es
            # por tanto fiable; los de la izquierda los escribe el cliente.
            # Hasta 2026-08 este caso devolvía request.client.host — que
            # uvicorn, honrando el mismo FORWARDED_ALLOW_IPS="*", ya había
            # reescrito con el hop MÁS A LA IZQUIERDA (spoofeable): el
            # rate-limit por IP y el allowlist de /metrics se alimentaban de
            # una IP elegida por el cliente (RFC-051).
            forwarded = request.headers.get("X-Forwarded-For", "")
            if forwarded:
                last_hop = forwarded.split(",")[-1].strip()
                if last_hop:
                    return last_hop
            return direct_ip or "unknown"

        if direct_ip and _is_trusted_proxy(direct_ip):
            # Petición viene de un proxy de confianza — honrar XFF
            forwarded = request.headers.get("X-Forwarded-For", "")
            if forwarded:
                # Recorremos la cadena desde el proxy más cercano. Solo las
                # IPs de proxies configurados son fiables; la primera no
                # confiable es el cliente visto por nuestra infraestructura.
                for hop in reversed([part.strip() for part in forwarded.split(",")]):
                    if hop and not _is_trusted_proxy(hop):
                        return hop
        return direct_ip or "unknown"
    except Exception:
        return "unknown"


def _client_key(request: HTTPConnection) -> str:
    """Identifica al cliente **solo** por IP verificada, nunca por API-Key.

    Un bucket por API-Key permitiría eludir el límite rotando claves (crearlas
    es barato), así que la cuota se ancla a la IP: el recurso caro de falsificar.
    La IP se obtiene a través de ``_trusted_client_ip``, que solo honra
    ``X-Forwarded-For`` si la petición viene de un proxy de confianza.
    """
    ip = _trusted_client_ip(request)
    return f"ip:{ip}"


# Endpoints que consumen más CPU/IO reciben un rate limit más bajo.
# Paths no listados usan el default del middleware.
#
# Esta tabla solo cubre rutas *sin* path params: se compara por igualdad exacta,
# así que "/api/v1/exports" no arrastra a "/api/v1/exports/{job_id}".
_HEAVY_ENDPOINT_LIMITS: dict[str, int] = {
    "/api/v1/exports": 20,
    # Descarga síncrona: hasta 50.000 filas y, con format=pdf, render en el
    # propio worker. Es el camino recomendado de export, no el job asíncrono.
    "/api/v1/exports/download": 10,
    "/api/v1/feedback/queue": 30,
    "/api/v1/search/semantic": 30,
    "/api/v1/ask": 10,
    "/api/v1/ask/models": 30,
}

# Rutas pesadas **con** path params. El middleware corre antes del
# routing, así que aquí solo se ve el path crudo y nunca el template: indexar
# por literal exacto hacía que estas dos entradas no matchearan jamás y
# corrieran al límite por defecto. Los patrones van anclados a ambos extremos
# para no capturar rutas vecinas.
_HEAVY_ENDPOINT_PATTERNS: tuple[tuple[re.Pattern[str], int], ...] = (
    # /licitaciones/{id_externo:path}/explain — el id puede contener '/'
    # (p.ej. "PA-S 2026/000058"), por eso el comodín admite barras.
    (re.compile(r"^/api/v1/licitaciones/.+/explain$"), 30),
    # /licitaciones/{id}/ficha-pliego/extract — la única ruta mutante de
    # /licitaciones y la más cara de la API: descarga contra PLACSP los pliegos
    # pendientes, extrae el PDF en un proceso aislado y pide al LLM una ficha de
    # hasta 3.500 tokens. Mismo tope que /ask porque el coste es de la misma
    # naturaleza —una llamada a proveedor por petición—, y corría al default de
    # 120/min por no estar en esta tabla. El comodín admite barras: el id
    # externo puede llevarlas (ver la nota de /explain).
    (re.compile(r"^/api/v1/licitaciones/.+/ficha-pliego/extract$"), 10),
    # /licitaciones/{id}/resumen — abre un SSE, arma contexto RAG con lecturas
    # de BD y streamea tokens del LLM. Es /ask con otro nombre y otra pregunta,
    # así que comparte su tope en vez del default: dejarlo en 120/min convertía
    # el límite de /ask en decorativo (misma capacidad, ruta distinta).
    (re.compile(r"^/api/v1/licitaciones/.+/resumen$"), 10),
    # /models/{name}/activate/{version}
    (re.compile(r"^/api/v1/models/[^/]+/activate/[^/]+$"), 10),
)


# La superficie pública indexable vive bajo este prefijo y necesita su propio
# bucket. Con la clave global `api:{ip}` compartida, dos cosas iban mal a la vez:
# los rastreadores consumían la cuota del usuario autenticado que estuviera
# detrás del mismo NAT, y —lo grave— si Next renderiza en servidor desde una IP
# de egreso única, TODAS las páginas públicas se contaban contra un solo bucket
# de 120/min y la superficie SEO se estrangulaba sola con 429.
#
# El límite es más alto porque el tráfico es cualitativamente distinto:
# lecturas anónimas, cacheables y sin estado, servidas a rastreadores que
# hacen ráfagas por diseño. Sigue siendo una cuota por IP, así que un abusivo
# concreto se corta igual, pero ya no arrastra al resto de la API.
PUBLIC_PATH_PREFIX = "/api/v1/publico/"
PUBLIC_MAX_CALLS = 600

# El único endpoint público de **escritura** (la cola de solicitudes de acceso
# que alimenta el formulario de la landing) necesita bucket propio, no una
# entrada en `_HEAVY_ENDPOINT_LIMITS`.
#
# El motivo es que esa tabla ajusta el tope pero **no** la clave: el contador
# seguiría siendo `publico:{ip}`, compartido con todas las lecturas anónimas.
# Un tope de 5 sobre ese contador significaría que cinco peticiones de un
# rastreador dejan el formulario inservible, y que cada envío consume cuota de
# la superficie SEO. Con clave propia, las dos cosas se limitan por separado.
#
# Cinco por minuto y por IP: un humano rellena el formulario una vez, y lo que
# hay detrás es una cola que revisa una persona.
#
# Al agotarse la cuota este path **no** responde `problem+json` como el resto de
# la API: quien lo consume es un navegador siguiendo un `<form method="post">`,
# así que se le redirige a la página de gracias con el estado de límite. Ver el
# caso propio en `RateLimitMiddleware._respuesta_429`.
SOLICITUDES_PATH = "/api/v1/publico/solicitudes-acceso"
SOLICITUDES_MAX_CALLS = 5


#: Cuánto se cachea el tier de una API key, en segundos (C2.3).
#:
#: El middleware corre **antes del routing**, en cada request. Consultar
#: `api_keys` + `api_key_tiers` en cada una convertiría el rate limiter en el
#: componente más caro del camino. Sesenta segundos es la ventana del propio
#: límite: un cambio de tier tarda como mucho un minuto en aplicarse, y esa
#: latencia es aceptable para una operación que hace un administrador a mano.
_TIER_CACHE_TTL_S = 60.0

#: `{key_hash: (limite_o_None, expira_epoch)}`. Cabe en memoria: son tantas
#: entradas como claves activas haya llamando, no como requests.
_tier_cache: dict[str, tuple[int | None, float]] = {}
_tier_cache_lock = threading.Lock()


def _tier_limit(key_hash: str) -> int | None:
    """Límite por minuto del tier de la clave, cacheado. `None` = sin tope propio."""
    ahora = time.time()
    with _tier_cache_lock:
        entrada = _tier_cache.get(key_hash)
        if entrada and entrada[1] > ahora:
            return entrada[0]

    try:
        from db.repositories.api_keys import tier_limit_por_hash

        limite = tier_limit_por_hash(key_hash)
    except Exception:
        # Un fallo de BD aquí no puede tumbar el rate limiter: se cae al default
        # del middleware, que es más restrictivo que `enterprise` y más
        # permisivo que `free`. Errar hacia el default deja la API respondiendo.
        log.debug("rate_limit_tier_lookup_fallo", exc_info=True)
        return None

    with _tier_cache_lock:
        _tier_cache[key_hash] = (limite, ahora + _TIER_CACHE_TTL_S)
        # Poda perezosa: sin ella el dict crece con cada clave que alguna vez
        # llamó, incluidas las rotadas.
        if len(_tier_cache) > 2_000:
            for k in [k for k, (_, exp) in _tier_cache.items() if exp <= ahora]:
                del _tier_cache[k]
    return limite


def reset_tier_cache() -> None:
    """Vacía la caché de tiers. Para tests que cambian el tier de una clave."""
    with _tier_cache_lock:
        _tier_cache.clear()


def _tier_bucket(request: HTTPConnection, client: str) -> tuple[str, int | None] | None:
    """Bucket y tope de una request con API key, o `None` si no la lleva.

    El bucket va por **clave**, no por IP: dos claves detrás del mismo NAT no
    tienen por qué compartir cuota, y una clave que rota de IP no debería
    estrenar cuota por eso. Es además lo que hace que el tier signifique algo —
    un límite por IP no se puede atribuir a un cliente.
    """
    raw = request.headers.get("x-api-key") or ""
    if not raw:
        return None
    from api.auth import hash_api_key

    key_hash = hash_api_key(raw)
    # Los primeros 16 caracteres del hash como identificador del bucket: ni el
    # token ni el hash entero salen a una clave de Redis que alguien pueda leer.
    return f"apikey:{key_hash[:16]}", _tier_limit(key_hash)


def _rate_bucket(path: str, client: str) -> tuple[str, int | None]:
    """Clave de cuota y tope propio para ``path``.

    Devuelve ``(clave, tope)``. Un tope ``None`` significa "usa el default del
    middleware", que es como se comporta todo lo que no es superficie pública.
    """
    if path == SOLICITUDES_PATH:
        return f"solicitudes:{client}", SOLICITUDES_MAX_CALLS
    if path.startswith(PUBLIC_PATH_PREFIX):
        return f"publico:{client}", PUBLIC_MAX_CALLS
    return f"api:{client}", None


def _regla_pesada(path: str) -> tuple[str, int] | None:
    """Regla de endpoint pesado aplicable a ``path``: ``(etiqueta, límite)``.

    Si varias matchean gana la **más restrictiva** (el mínimo): pasarse de
    estricto cuesta un 429 recuperable, quedarse corto deja el endpoint caro sin
    la protección que se le quiso poner.

    La **etiqueta** identifica la regla, no la petición: es el path exacto de la
    tabla o el patrón que casó. Sirve para que cada regla tenga su propio cubo
    (ver `RateLimitMiddleware._consultar_cuota`) sin reintroducir el bypass por
    path params que el cubo por cliente evita — dos ids distintos de `/explain`
    casan el mismo patrón y por tanto comparten cubo.
    """
    reglas: list[tuple[str, int]] = [
        (pattern.pattern, limit)
        for pattern, limit in _HEAVY_ENDPOINT_PATTERNS
        if pattern.match(path)
    ]
    exact = _HEAVY_ENDPOINT_LIMITS.get(path)
    if exact is not None:
        reglas.append((path, exact))
    return min(reglas, key=lambda r: r[1]) if reglas else None


def _effective_max_calls(path: str, default: int) -> int:
    """Límite de requests por ventana aplicable a ``path``."""
    regla = _regla_pesada(path)
    return regla[1] if regla else default


#: Hilos que la comprobación de cuota puede ocupar a la vez (ver
#: :class:`RateLimitMiddleware`). Con Redis cada comprobación dura ~1 ms, así
#: que cuatro sobran para lo que despacha un proceso de 1 vCPU. Con la BD de
#: respaldo son ~50 ms y cada hilo retiene una conexión del pool de escritura
#: (12 en producción): cuatro dejan el resto para las escrituras de los
#: handlers, y aun así cuadruplican lo que daba la comprobación serializada en
#: el event loop.
_HILOS_CUOTA = 4
_hilos_cuota: CapacityLimiter | None = None


def _limitador_de_hilos_cuota() -> CapacityLimiter:
    """``CapacityLimiter`` propio de la comprobación de cuota (lazy singleton)."""
    global _hilos_cuota
    if _hilos_cuota is None:
        _hilos_cuota = CapacityLimiter(_HILOS_CUOTA)
    return _hilos_cuota


class RateLimitMiddleware:
    """Rate limiting global por IP (o por API key) sobre la API REST.

    Usa :func:`services.rate_limiting.get_rate_limiter` como backend (Redis o
    la tabla ``rate_limits``, según configuración).
    Devuelve ``429 Too Many Requests`` con cabeceras estándar cuando se excede.

    Excluye paths configurables (e.g. ``/api/v1/health``) para no bloquear LBs.

    Los endpoints pesados (inferencia ML, exports) tienen un límite inferior;
    ver :func:`_effective_max_calls`.

    **La comprobación corre en un hilo, nunca en el event loop.** ``check()`` es
    síncrono: con Redis es un viaje de red; con la BD, un checkout del pool de
    escritura y cinco viajes (BEGIN, DELETE, SELECT COUNT, INSERT, COMMIT).
    Hasta 2026-09 se llamaba directamente desde el ``dispatch`` async, así que
    en **cada** petición el único event loop del proceso se quedaba parado unos
    50 ms, y todas las peticiones se contaban en serie. Lo mismo el tier de la
    API key, que en un fallo de caché consulta la BD.

    Se despacha con ``anyio.to_thread.run_sync`` y no con un cliente Redis
    asíncrono porque: el backend de BD es síncrono (psycopg) y habría que
    llevarlo a un hilo igualmente, así que sería un segundo camino; el
    protocolo ``RateLimiter`` es síncrono y lo usan otros consumidores que ya lo
    despachan con ``run_db``; un cliente ``redis.asyncio`` queda atado al loop
    que lo creó y exigiría abrir y cerrar su pool en el lifespan; y el salto a un
    hilo cuesta décimas de milisegundo, frente al milisegundo de Redis o los
    ~50 ms de la BD. Lo que había que evitar era parar el loop, no el hilo.

    El hilo sale de un ``CapacityLimiter`` propio (:data:`_HILOS_CUOTA`), no del
    threadpool general: con este lleno de handlers lentos, una petición trivial
    no debe esperar un hilo solo para contarse, y con la BD de respaldo acota las
    conexiones de escritura que el limitador puede retener a la vez.

    Args:
        app: Aplicación ASGI a envolver.
        max_calls: Máximo de requests permitidas en la ventana (endpoints estándar).
        window_seconds: Tamaño de la ventana en segundos.
        exclude_paths: Iterable de paths exactos a excluir (e.g. health, docs).
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_calls: int = 120,
        window_seconds: float = 60.0,
        exclude_paths: tuple[str, ...] = (
            "/",
            "/api/v1/health",
            "/api/docs",
            "/api/redoc",
            "/api/openapi.json",
        ),
    ) -> None:
        self.app = app
        self._max = max_calls
        self._window = window_seconds
        self._exclude = frozenset(exclude_paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # `scope["path"]` y no `request.url.path`: es lo que enruta Starlette.
        # La URL reconstruida corta en un `?` que llegue codificado en el path
        # (`/licitaciones/X%3F/explain`), y con ella el patrón de `/explain` no
        # casaba y la petición corría con el tope por defecto.
        path: str = scope["path"]
        if path in self._exclude or path.startswith(("/api/docs", "/api/redoc")):
            await self.app(scope, receive, send)
            return

        conexion = HTTPConnection(scope)
        client = _client_key(conexion)
        allowed, effective_max = await to_thread.run_sync(
            self._consultar_cuota,
            conexion,
            path,
            client,
            limiter=_limitador_de_hilos_cuota(),
        )
        if allowed:
            await self.app(scope, receive, send)
            return

        log.warning("rate_limit_exceeded", client=client, path=path)
        respuesta = self._respuesta_429(path, effective_max)
        await respuesta(scope, receive, send)

    def _consultar_cuota(
        self, conexion: HTTPConnection, path: str, client: str
    ) -> tuple[bool, int]:
        """Decide si la petición cabe en su cuota. Corre en un hilo: hace E/S.

        Devuelve ``(permitida, tope_aplicado)``.
        """
        # El middleware se ejecuta antes del routing: un bucket por
        # cliente evita el bypass por path params variables. La superficie
        # pública lleva el suyo aparte (ver `_rate_bucket`).
        # C2.3 — una request con API key se limita por SU clave y por el
        # tier que declara `api_key_tiers`, no por la IP compartida.
        por_clave = _tier_bucket(conexion, client)
        rate_key, tope_propio = por_clave or _rate_bucket(path, client)
        # Endpoints pesados (ML inference, exports): límite inferior **y cubo
        # propio**.
        #
        # El cubo propio no es un detalle. Hasta 2026-09-08 el tope bajo se
        # aplicaba sobre el cubo compartido `api:{cliente}`, que cuenta **todo**
        # el tráfico de ese cliente: cargar el dashboard son decenas de
        # llamadas, así que al pulsar «Exportar CSV» el contador ya iba muy por
        # encima de 10 y la descarga respondía 429. Lo destapó el E2E de
        # exportación (el log de la API del job: tres intentos, tres 429), y en
        # producción rompía el export para cualquiera que hubiera mirado la
        # pantalla antes de pedirlo.
        #
        # La etiqueta viene de la regla y no del path, así que el bypass por
        # path params que motivó el cubo por cliente sigue cerrado.
        regla = _regla_pesada(path)
        if regla is None:
            effective_max = tope_propio or self._max
        else:
            etiqueta, limite = regla
            rate_key = f"pesado:{etiqueta}:{rate_key}"
            effective_max = min(limite, tope_propio or self._max)
        allowed = get_rate_limiter().check(
            rate_key,
            max_calls=effective_max,
            window_seconds=self._window,
        )
        return allowed, effective_max

    def _respuesta_429(self, path: str, effective_max: int) -> Response:
        """Respuesta de cuota agotada: ``problem+json``, o la redirección del formulario."""
        # El formulario de la landing lo rellena una persona en un
        # navegador, no un cliente de API: aquí un `problem+json` es JSON
        # crudo en pantalla, y `api/routes/publico_solicitudes.py` está
        # escrito entero para que eso no pase en ningún camino de error.
        # El corte por cuota ocurre antes del router, así que la excepción
        # tiene que vivir aquí. Import perezoso por el mismo motivo que el
        # de `problem_429`: no arrastrar el árbol de rutas al importar el
        # middleware.
        if path == SOLICITUDES_PATH:
            from api.routes.publico_solicitudes import ESTADO_LIMITE, destino_error

            return RedirectResponse(
                destino_error(ESTADO_LIMITE),
                status_code=status.HTTP_303_SEE_OTHER,
                headers={"Retry-After": str(int(self._window))},
            )

        # `application/problem+json` como el resto de la API (RFC 7807). El
        # 429 cortocircuita antes del router, así que se construye aquí en
        # vez de en un exception handler; `problem_429` ya existía sin uso.
        from api.errors import problem_429

        return problem_429(effective_max, int(self._window)).response(
            **{
                "Retry-After": str(int(self._window)),
                "X-RateLimit-Limit": str(effective_max),
                "X-RateLimit-Window": str(int(self._window)),
            }
        )


# ─────────────── Correlation-ID + access log + coste (E7) ────────────────


def _registrar_acceso(conexion: HTTPConnection, scope: Scope, status_code: int, dt: float) -> None:
    """Línea ``http_request`` del access log."""
    # Usar el path template de la ruta (e.g. "/licitaciones/{id}") en lugar
    # del path crudo ("/licitaciones/123") para evitar cardinalidad explosiva
    # en métricas Prometheus cuando los IDs forman parte de la URL.
    route = scope.get("route")
    path = getattr(route, "path", None) or scope["path"]
    # Usar hash prefix en lugar de los primeros caracteres del API key
    # para evitar reducir el espacio de brute-force en los logs.
    raw_key = conexion.headers.get("x-api-key") or ""
    key_prefix = hashlib.sha256(raw_key.encode()).hexdigest()[:12] if raw_key else "-"

    log.info(
        "http_request",
        method=scope["method"],
        path=path,
        status=status_code,
        duration_ms=round(dt * 1000, 1),
        key_prefix=key_prefix,
        client_ip=_trusted_client_ip(conexion),
    )


class ObservabilityMiddleware:
    """Correlation-ID, access log y coste estimado de cada request, en una capa.

    Eran tres ``BaseHTTPMiddleware`` contiguos (``correlation_id_middleware`` →
    ``AccessLogMiddleware`` → ``CostTrackingMiddleware``), cada uno con su task
    group y su relé del cuerpo. Hacían tres cosas en el mismo instante de la
    misma petición; juntas ocupan el mismo sitio del stack y el orden efectivo
    no cambia (ver ``api.app.register_middlewares``).

    **Correlation-ID.** Toma ``X-Correlation-Id`` de la petición o genera un
    uuid4, limpia los contextvars de structlog y lo vincula: lo llevan los logs
    de toda la petición —los de los handlers y los de los hilos del threadpool,
    que heredan el contexto— y vuelve en la cabecera de la respuesta.

    **Access log** (``http_request``): método, path (la plantilla de la ruta, no
    el path crudo), status, duración en ms, prefijo del hash de la API key y la
    IP que decide :func:`_trusted_client_ip`. Las métricas RED las gestiona
    ``prometheus-fastapi-instrumentator`` (inicializado en ``api.app``).

    **Coste** (``api_cost_estimate_total{operation}``): un coste base de 0.0001
    USD más un factor proporcional a la duración, publicado en micros (USD *
    1e6) para evitar problemas de precisión float en el TSDB. Permite a Finance
    ver de un vistazo qué endpoints son los más caros.

    **Cuándo se mide.** Al salir ``http.response.start``, no al terminar el
    cuerpo: es lo que medía ``BaseHTTPMiddleware``, cuyo ``call_next`` vuelve en
    cuanto llegan las cabeceras. En un SSE es el tiempo hasta la primera
    respuesta; medir hasta el final daría duraciones de horas y retrasaría la
    línea de log hasta que el cliente cerrara.

    **Excepciones.** Si la app lanza antes de empezar a responder se registra un
    500 y la excepción sigue hacia arriba intacta (la convierte en respuesta el
    ``ServerErrorMiddleware`` de Starlette, como antes).
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        base_usd: float = 0.0001,
        per_second_usd: float = 0.001,
    ) -> None:
        self.app = app
        self._base = base_usd
        self._per_s = per_second_usd

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        conexion = HTTPConnection(scope)
        correlation_id = conexion.headers.get("x-correlation-id") or str(uuid.uuid4())
        # Limpiar y bindear variables de contexto structlog para esta request
        clear_contextvars()
        bind_contextvars(correlation_id=correlation_id)

        t0 = time.monotonic()
        registrada = False

        def registrar(status_code: int) -> None:
            nonlocal registrada
            if registrada:
                return
            registrada = True
            dt = time.monotonic() - t0
            self._registrar_coste(scope, dt)
            _registrar_acceso(conexion, scope, status_code, dt)

        async def enviar(message: Message) -> None:
            if message["type"] == "http.response.start":
                registrar(int(message["status"]))
                # Sobre una copia: la lista puede ser la `raw_headers` de un
                # objeto `Response` que alguien reutilice entre peticiones.
                cabeceras = MutableHeaders(raw=list(message.get("headers", [])))
                cabeceras["X-Correlation-Id"] = correlation_id
                message = {**message, "headers": cabeceras.raw}
            await send(message)

        try:
            await self.app(scope, receive, enviar)
        finally:
            # Solo cuenta si la app salió sin empezar a responder: lanzó, o
            # volvió sin respuesta. Es el status que registraba el access log.
            registrar(500)

    def _registrar_coste(self, scope: Scope, dt: float) -> None:
        usd = self._base + (dt * self._per_s)
        try:
            from observability.runtime_metrics import api_cost_estimate_total

            # Usar route template para evitar cardinalidad explosiva
            route = scope.get("route")
            op = getattr(route, "path", None) or "unmatched"
            api_cost_estimate_total.labels(operation=op).inc(int(usd * 1e6))
        except Exception:
            pass


# ────────────────── Límite de body y saneo de la request line ──────────────
#
# Los de abajo vivían en ``api/app.py`` (con el correlation id, hoy dentro de
# ``ObservabilityMiddleware``), que llegó a 706 líneas siendo a la vez fábrica
# de la app, registro de routers, definición de middlewares y handler de
# /metrics. No hay nada distinto en ellos: son middlewares, y este es el módulo
# de los middlewares.


class _BodyTooLargeError(Exception):
    """Señal interna para abortar el pipeline cuando el body excede el límite."""


class _MaxBodyMiddleware:
    """Rechaza requests con body > 1 MB usando raw ASGI.

    Comprueba Content-Length (fast path) y acumula tamaño en streaming
    (slow path) sin buffering completo del body.
    """

    _MAX_BYTES = 1 * 1024 * 1024  # 1 MB
    # RFC 7807 como el resto de la API. El 413 se emite en ASGI crudo (el body
    # se corta antes de llegar al router, así que no hay exception handler que
    # lo formatee), pero el contrato que ve el cliente es el mismo: un
    # `application/problem+json` con type/title/status.
    _413_BODY = (
        b'{"type":"https://licitaciones-sap/errors/payload-too-large",'
        b'"title":"Payload Too Large","status":413,'
        b'"detail":"Request body demasiado grande (m\\u00e1x. 1 MB)."}'
    )

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Fast path: rechazar inmediatamente si Content-Length lo delata
        headers = dict(scope.get("headers") or [])
        cl_raw = headers.get(b"content-length")
        if cl_raw is not None:
            try:
                if int(cl_raw) > self._MAX_BYTES:
                    await self._send_413(send)
                    return
            except (ValueError, UnicodeDecodeError):
                pass

        # Slow path: para requests con body, envolver receive para contar bytes
        method = scope.get("method", "")
        if method in ("POST", "PUT", "PATCH"):
            body_size = 0
            max_bytes = self._MAX_BYTES
            cortado = False
            respuesta_empezada = False

            async def limiting_receive() -> Message:
                nonlocal body_size, cortado
                message = await receive()
                if message.get("type") == "http.request":
                    body_size += len(message.get("body", b""))
                    if body_size > max_bytes:
                        cortado = True
                        raise _BodyTooLargeError
                return dict(message)

            # El _BodyTooLargeError no siempre sale de la app: FastAPI envuelve lo
            # que salte al leer el cuerpo de una ruta con parámetro de cuerpo en
            # HTTPException(400, "There was an error parsing the body"), y su
            # manejador responde ese 400. Por eso, cortado el cuerpo, se descarta
            # lo que la app responda y el cliente recibe el 413. Si la app ya había
            # empezado a responder antes del corte, el status no se puede cambiar:
            # su respuesta pasa tal cual y, si el _BodyTooLargeError llega hasta
            # aquí, se relanza en vez de mandar un segundo `http.response.start`.
            async def send_hasta_el_corte(message: Message) -> None:
                nonlocal respuesta_empezada
                if cortado and not respuesta_empezada:
                    return
                if message["type"] == "http.response.start":
                    respuesta_empezada = True
                await send(message)

            try:
                await self.app(scope, limiting_receive, send_hasta_el_corte)
            except _BodyTooLargeError:
                if respuesta_empezada:
                    raise
            if cortado and not respuesta_empezada:
                await self._send_413(send)
        else:
            await self.app(scope, receive, send)

    async def _send_413(self, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/problem+json"),
                    (b"content-length", str(len(self._413_BODY)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": self._413_BODY})


class _RejectNulMiddleware:
    """Rechaza el byte NUL en la línea de petición (path y query string).

    Postgres no admite ``\\x00`` en columnas de texto y psycopg lanza
    ``DataError`` al adaptar el parámetro, así que cualquier filtro de texto que
    acabe en una query convertía un carácter del cliente en un 500:
    ``GET /api/v1/competitive/bajas?cpv=%00`` reventaba en
    ``services/competitive/bajas.py`` y salía por el handler genérico. Lo
    encontró el fuzzer de contrato en 2026-08; el fallo llevaba semanas vivo.

    El saneo va aquí y no en las ~100 declaraciones ``Query(...)`` de
    ``api/routes/`` por la misma razón por la que ``shared.dto.SafeStr`` vive en
    el contrato y no en cada endpoint: acordarse en cada parámetro nuevo no es
    una defensa, es una lotería. Se comprueban los bytes **crudos** —antes del
    percent-decode— para cazar tanto ``\\x00`` literal como ``%00``.

    Se rechaza en vez de sanear en silencio: un filtro que se modifica solo y
    no lo dice devolvería un 200 con el resultado de una consulta que el cliente
    no pidió.
    """

    _400_BODY = (
        b'{"type":"https://licitaciones-sap/errors/bad-request",'
        b'"title":"Bad Request","status":400,'
        b'"detail":"La petici\\u00f3n no puede contener el byte NUL (\\\\x00)."}'
    )

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    @staticmethod
    def _tiene_nul(scope: Scope) -> bool:
        crudos: list[bytes] = [
            bytes(scope.get("query_string") or b""),
            bytes(scope.get("raw_path") or b""),
        ]
        for valor in crudos:
            if b"\x00" in valor or b"%00" in valor.lower():
                return True
        # `path` ya viene decodificado por el servidor ASGI: un %00 en la URL
        # llega aquí como \x00 aunque `raw_path` no esté disponible.
        return "\x00" in str(scope.get("path") or "")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and self._tiene_nul(scope):
            await self._send_400(send)
            return
        await self.app(scope, receive, send)

    async def _send_400(self, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 400,
                "headers": [
                    (b"content-type", b"application/problem+json"),
                    (b"content-length", str(len(self._400_BODY)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": self._400_BODY})


# ───────────────────────────── ETag caching ──────────────────────────────────

# RFC 7232 §4.1: un 304 debe repetir las cabeceras que habrían acompañado al
# 200 y que el cliente necesita para interpretar la respuesta cacheada.
_NOT_MODIFIED_PRESERVED_HEADERS = frozenset(
    {"vary", "x-request-id", "x-correlation-id", "content-language"}
)

# `Vary` no es opcional desde el momento en que el middleware decide el
# `Cache-Control` leyendo cabeceras de la **petición**: sin declararlo, un CDN
# o un proxy intermedio no sabe que la respuesta depende de ellas y puede
# servirle a un visitante anónimo la copia cacheada de uno autenticado. Se
# emite siempre, también en el 304, porque la dependencia existe igualmente en
# ese camino.
_VARY = "Cookie, X-API-Key"


def _cabeceras_etiquetadas(
    crudas: list[tuple[bytes, bytes]], *, etag: str | None, cache_control: str | None
) -> dict[str, str]:
    """Cabeceras del 200 etiquetado, como las componía la versión anterior.

    Parte de ``dict(response.headers)`` —una entrada por nombre, en minúsculas—
    y le añade ``ETag`` (si hay que ponerla), ``Cache-Control`` y ``Vary`` con
    clave capitalizada. Como las del handler quedaron en minúscula, las nuevas
    son claves **aparte**: si el handler fijó su propio ``Cache-Control`` (la
    superficie ``/publico/*`` pone ``public, max-age=300, …``), la respuesta
    sale con los dos y, por RFC 9111 §4.2.1, manda el más restrictivo. La
    versión anterior hacía exactamente eso —su ``headers.get("Cache-Control",
    …)`` nunca encontraba la clave del handler— y aquí se conserva tal cual:
    cambiarlo decide la cacheabilidad de la superficie pública en el CDN, y eso
    no es una optimización de rendimiento.
    """
    cabeceras = dict(Headers(raw=crudas))
    if etag is not None:
        cabeceras["ETag"] = etag
    # Para el JSON que sí lleva ETag, `private` mantiene fuera a los cachés
    # compartidos y `no-cache` obliga a revalidar en cada uso — el 304 sigue
    # siendo válido, y es justo el punto de haber calculado el ETag.
    cabeceras["Cache-Control"] = cache_control or "no-cache"
    cabeceras["Vary"] = _VARY
    return cabeceras


def _a_crudas(cabeceras: dict[str, str]) -> list[tuple[bytes, bytes]]:
    """``dict`` de cabeceras a la lista ASGI, igual que ``Response.init_headers``."""
    return [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in cabeceras.items()]


def _no_modificado(
    crudas: list[tuple[bytes, bytes]], *, etag: str, cache_control: str | None
) -> Response:
    """El 304 que corresponde a una respuesta cuya ETag nombra el cliente."""
    # El 304 conserva las cabeceras de correlación/seguridad de la
    # respuesta original: son las mismas que el cliente habría recibido
    # con un 200, y perderlas rompía el rastro de la petición.
    not_modified = {
        k: v for k, v in Headers(raw=crudas).items() if k.lower() in _NOT_MODIFIED_PRESERVED_HEADERS
    }
    not_modified["ETag"] = etag
    not_modified["Cache-Control"] = cache_control or "no-cache"
    not_modified["Vary"] = _VARY
    return Response(status_code=304, headers=not_modified)


class ETagMiddleware:
    """Añade ``ETag`` a respuestas GET 200 y responde 304 si ``If-None-Match`` coincide.

    Sólo actúa sobre respuestas ``Content-Type: application/json``. La etiqueta
    es débil (``W/"…"``) y la calcula :func:`shared.etag.etag_debil`.

    **Respuestas que ya traen ``ETag``** (contrato con ``shared/cache.py``): la
    caché de respuestas adjunta la etiqueta calculada al guardar la entrada. Se
    respeta tal cual: el cuerpo no se retiene ni se hashea; si ``If-None-Match``
    la nombra se responde 304 (mismas cabeceras que el 304 de siempre) y, si no,
    la respuesta pasa con las cabeceras de caché de este middleware.

    **Respuestas sin ``ETag``**: se hashea el cuerpo, igual que antes. Solo si
    llega en **un único mensaje** —lo que emite un ``JSONResponse``— y no pasa de
    ``max_bytes``; un cuerpo mayor pasa intacto, sin ETag.

    **Streams:** nunca se retienen. Lo que no es JSON (SSE, exports CSV/XLSX/PDF,
    zip) pasa en cuanto llega, y un JSON troceado (``more_body=True`` en el
    primer mensaje) se trata como stream, sin ETag. La versión con
    ``BaseHTTPMiddleware`` acumulaba hasta 512 KB de cualquier GET JSON antes de
    soltar un byte; ahora lo único que se retiene es el ``http.response.start``
    hasta que llega el primer trozo del cuerpo, que en un ``JSONResponse`` es el
    mensaje siguiente.

    **Tráfico autenticado.** Hasta 2026-08 una petición con cookie o API key
    salía por un atajo que ponía ``private, no-store`` y devolvía la respuesta
    *sin* ETag. Como prácticamente todos los endpoints exigen autenticación, el
    middleware no emitía un solo ETag en producción: se pagaba el coste de
    bufferizar el cuerpo de cada GET JSON a cambio de nada. Ahora esas
    respuestas llevan ``private, no-cache``, que sigue impidiendo que un caché
    compartido las guarde y además permite la revalidación con 304 — que es
    justo donde está el ahorro de ancho de banda para un SPA que repregunta.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_bytes: int = 512 * 1024,  # 512 KB
    ) -> None:
        self.app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") != "GET":
            await self.app(scope, receive, send)
            return

        peticion = Headers(scope=scope)
        # Una respuesta solicitada con cookie o API key puede contener estado
        # personalizado; ningún cache compartido debe conservarla.
        autenticada = bool(peticion.get("cookie") or peticion.get("x-api-key"))
        cache_control = "private, no-cache" if autenticada else None
        if_none_match = peticion.get("if-none-match", "")

        # Estado de la respuesta que sale de la app:
        retenido: Message | None = None  # `http.response.start` a la espera del cuerpo
        paso = False  # decidido: lo que llegue se reenvía tal cual
        descartar = False  # sustituida por un 304: el cuerpo de la app no sale

        async def enviar(message: Message) -> None:
            nonlocal retenido, paso, descartar
            if paso:
                await send(message)
                return
            if descartar:
                return
            tipo = message["type"]

            if tipo == "http.response.start":
                crudas = list(message.get("headers", []))
                cabeceras = Headers(raw=crudas)
                es_json = "application/json" in cabeceras.get("content-type", "")
                if message["status"] != 200 or not es_json:
                    paso = True
                    await send(self._sin_etiqueta(message, crudas, autenticada))
                    return
                etag_previa = cabeceras.get("etag")
                if etag_previa is not None:
                    if coincide_if_none_match(etag_previa, if_none_match):
                        descartar = True
                        await _no_modificado(crudas, etag=etag_previa, cache_control=cache_control)(
                            scope, receive, send
                        )
                        return
                    paso = True
                    etiquetadas = _cabeceras_etiquetadas(
                        crudas, etag=None, cache_control=cache_control
                    )
                    await send({**message, "headers": _a_crudas(etiquetadas)})
                    return
                retenido = message
                return

            if tipo == "http.response.body" and retenido is not None:
                inicio, retenido = retenido, None
                await self._responder_con_cuerpo(
                    inicio, message, autenticada, cache_control, if_none_match, scope, receive, send
                )
                # Tras un cuerpo completo la app no debería mandar nada más; si
                # era un stream, el resto se reenvía sin tocar.
                paso = True
                return

            await send(message)

        await self.app(scope, receive, enviar)

    async def _responder_con_cuerpo(
        self,
        inicio: Message,
        primero: Message,
        autenticada: bool,
        cache_control: str | None,
        if_none_match: str,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """Decide qué sale para un GET 200 JSON sin ETag previa, ya con su primer trozo."""
        crudas = list(inicio.get("headers", []))
        cuerpo: bytes = primero.get("body", b"")

        if primero.get("more_body", False):
            # Un stream: se suelta ya y no se etiqueta.
            await send(self._sin_etiqueta(inicio, crudas, autenticada))
            await send(primero)
            return

        if len(cuerpo) > self._max_bytes:
            # Demasiado grande: pasa sin ETag y con sus cabeceras tal cual,
            # igual que antes (entonces sin `Vary` ni `Cache-Control` propios).
            await send(inicio)
            await send(primero)
            return

        etag = etag_debil(cuerpo)
        if coincide_if_none_match(etag, if_none_match):
            await _no_modificado(crudas, etag=etag, cache_control=cache_control)(
                scope, receive, send
            )
            return

        etiquetada = Response(
            content=cuerpo,
            status_code=200,
            headers=_cabeceras_etiquetadas(crudas, etag=etag, cache_control=cache_control),
        )
        await etiquetada(scope, receive, send)

    @staticmethod
    def _sin_etiqueta(
        inicio: Message, crudas: list[tuple[bytes, bytes]], autenticada: bool
    ) -> Message:
        """``http.response.start`` de lo que no lleva ETag (no-200, no-JSON, streams).

        Conserva el ``private, no-store`` de siempre: sin revalidación posible,
        lo correcto es no guardarlo en ningún sitio.
        """
        cabeceras = MutableHeaders(raw=crudas)
        if autenticada:
            cabeceras["Cache-Control"] = "private, no-store"
        cabeceras["Vary"] = _VARY
        return {**inicio, "headers": cabeceras.raw}
