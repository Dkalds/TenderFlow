"""Settings de la API HTTP: CORS, límites, bulkheads, IP del cliente y caché Redis.

Módulo hermano de ``config/settings.py`` (P3 «Los dos módulos-dios»): ``Settings``
hereda de esta clase, así que los nombres de las variables de entorno y el
acceso (``settings.CORS_ALLOWED_ORIGINS``) son los de siempre.

Sin ``model_config`` propio, por lo mismo que ``config/settings_resumen.py``.
"""

from __future__ import annotations

import ipaddress
import warnings
from typing import Self

from pydantic import SecretStr, field_validator, model_validator

from config.settings_auth import LONGITUD_MINIMA_CLAVE
from config.settings_bd import _LOCAL_DB_HOSTS
from config.settings_entorno import EntornoSettings


def _redis_publico_sin_tls(url: str) -> bool:
    """``redis://`` (sin TLS) hacia un nombre con puntos o una IP que no es privada."""
    from urllib.parse import urlsplit

    try:
        partes = urlsplit(url)
        host = partes.hostname or ""
    except ValueError:
        return False
    if partes.scheme != "redis" or not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # shortcut: un nombre sin puntos (`red-abc123`) se toma por red privada de la
        # plataforma; subirlo si prod usa un host interno con puntos y el aviso sobra.
        return "." in host and host != "localhost"
    return not (ip.is_private or ip.is_loopback)


def _origen_cors_seguro(origen: str) -> bool:
    """``https://host`` o, solo para el loopback, ``http://host``; nunca ``*``."""
    from urllib.parse import urlsplit

    try:
        partes = urlsplit(origen)
        partes.port  # noqa: B018 — un puerto inválido lanza ValueError
    except ValueError:
        return False
    if not partes.hostname:
        return False
    if partes.scheme == "https":
        return True
    return partes.scheme == "http" and partes.hostname in _LOCAL_DB_HOSTS


class ApiSettings(EntornoSettings):
    """Lo que solo pinta en el proceso que sirve HTTP (perfil ``api``)."""

    # Orígenes CORS permitidos (lista separada por comas, vacío = bloquear todo en
    # prod; en dev `api/app.py` abre solo localhost:3000). En prod/staging el
    # validador rechaza "*" y todo origen que no sea https (la API manda cookies).
    # Ej: "https://app.example.com,https://api.example.com"
    CORS_ALLOWED_ORIGINS: str = ""

    # Límite global del RateLimitMiddleware. `api/app.py` los leía con
    # `getattr(settings, ...)` y `Settings` no los declaraba: con
    # `extra="ignore"`, exportar la variable no hacía nada y el límite era
    # siempre 120/60s, pese a que docs/runbooks/rate-limit-reset.md los
    # documenta como palanca de operación. Declararlos los vuelve reales.
    API_RATE_LIMIT_MAX_CALLS: int = 120
    API_RATE_LIMIT_WINDOW_SECONDS: float = 60.0

    # ── API REST ─────────────────────────────────────────────────────────
    # Hilos del threadpool de anyio, donde corre TODO el trabajo síncrono de la
    # API (los ~104 `run_db` y los handlers `def`). Estuvo fijado a 4 desde un
    # incidente de CPU en Render Free: el límite era correcto para la analítica
    # pandas pero castigaba por igual a las lecturas IO-bound, que solo esperan
    # red — con 4 hilos y un pool de 5 conexiones, el techo de la API era de 4
    # peticiones concurrentes. Ahora el trabajo CPU-bound tiene su propio carril
    # (API_CPU_BOUND_TOKENS) y este límite puede respirar.
    API_THREADPOOL_TOKENS: int = 24
    # Bulkheads dedicados (subconjuntos del threadpool anterior).
    API_CPU_BOUND_TOKENS: int = 2
    API_ML_TOKENS: int = 2
    # `statement_timeout` (ms) de las lecturas de la analítica, más corto que el
    # general (`DB_STATEMENT_TIMEOUT_MS`, 30 s). Una agregación que pasa de
    # unos segundos ya no la espera nadie en la pantalla, y cada segundo que
    # sigue corriendo retiene una conexión del pool de lectura y un hilo del
    # bulkhead de CPU. Lo fijan las rutas de `/analytics` y `/competitive` para
    # toda la petición (`api/techo_analitica.py` → `db.connection.
    # techo_de_sentencia`), nunca los jobs de precálculo, que necesitan las
    # consultas largas. Solo baja el techo: un valor igual o mayor que el
    # general no cambia nada, y 0 lo desactiva (manda el general).
    #
    # **Apagado por defecto a propósito.** No hay medición de producción de
    # cuánto tardan hoy las agregaciones filtradas, y la búsqueda `q` sigue
    # sin índice utilizable hasta aplicar la propuesta de
    # `docs/plans/2026-09-indices-busqueda-propuestos.md`: con un techo corto,
    # consultas que hoy terminan en 15-25 s pasarían a fallar. Se enciende por
    # entorno (p. ej. 15000) cuando `pg_stat_statements` diga dónde cortar. La
    # cancelación ya no se reintenta desde el navegador (503 `query-timeout`,
    # ver `api/errors.py`), así que encenderlo no multiplica la carga.
    API_ANALYTICS_STATEMENT_TIMEOUT_MS: int = 0
    # TTL de la caché de proceso del clasificador ML. Cubre el caso
    # multi-worker: `/models/{name}/activate` invalida el proceso que atiende
    # la petición, y los demás recargan al vencer este plazo. 0 = sin recarga
    # por tiempo (solo invalidación explícita).
    API_MODEL_CACHE_TTL_SECONDS: float = 300.0
    # IPs (o rangos) que pueden acceder a /metrics sin API key (separadas por coma).
    # Por defecto solo loopback. En producción añadir la IP del servidor Prometheus.
    # Ej: "127.0.0.1,10.0.0.5,10.0.0.6"
    METRICS_ALLOWED_IPS: str = "127.0.0.1"
    # IPs (o rangos CIDR) del reverse proxy cuyo ``X-Forwarded-For`` se considera
    # confiable, separadas por coma. La consume uvicorn (`--forwarded-allow-ips`,
    # que reescribe la IP del peer con la cabecera) y api.middleware
    # ._trusted_client_ip, del que dependen el rate limiting, el lockout de login
    # y la IP que queda registrada en el audit log.
    #
    # El comodín "*" hace que se acepte la cabecera venga de donde venga: el
    # cliente pasa a elegir su propia IP y las tres defensas anteriores dejan de
    # discriminar entre atacantes. Por eso el default es loopback y
    # _validate_prod_forwarded_allow_ips impide arrancar con "*" en prod/staging.
    #
    # Hasta 2026-08-02 este campo no estaba declarado y model_config usa
    # extra="ignore": la variable de entorno se descartaba en silencio y el
    # getattr de api/middleware.py caía siempre al default. Si alguien la vuelve
    # a quitar, la defensa deja de ser configurable sin que nada falle.
    FORWARDED_ALLOW_IPS: str = "127.0.0.1"
    # Secreto compartido con el frontend de Vercel (RFC 2026-10-24, opción B).
    # Detrás de Render la API ve como peer un nodo interno 10.19x de su proxy, y
    # recorrer X-Forwarded-For solo llega al egreso de Vercel, compartido por
    # todos: ninguna de las dos es la IP de una persona. Vercel añade este
    # secreto en la cabecera ``x-tf-origin-secret`` de cada petición que reenvía
    # a /api/* (``web/vercel.json``) y el prefetch SSR de Next lo manda también
    # (``web/src/lib/server-prefetch.ts``). Si la cabecera casa con alguno de los
    # dos valores, api.middleware._trusted_client_ip toma la IP del visitante de
    # ``x-real-ip``; si falta o no casa, el comportamiento es el de siempre.
    #
    # Dos valores para rotar sin corte: el nuevo en API_ORIGIN_SECRET y el
    # anterior en API_ORIGIN_SECRET_PREVIOUS mientras Vercel se redespliega
    # (docs/runbooks/ip-del-cliente.md). Vacío = la verificación no existe.
    # Genera uno con: python -c "import secrets; print(secrets.token_hex(32))"
    API_ORIGIN_SECRET: SecretStr = SecretStr("")
    API_ORIGIN_SECRET_PREVIOUS: SecretStr = SecretStr("")

    # ── Cache (Redis opcional) ────────────────────────────────────────────
    # Si se deja vacío se usa cache en memoria por proceso (default).
    # Formato: redis://[:password@]host[:port][/db]
    REDIS_URL: str = ""
    # Contraseña de Redis. En producción debe coincidir con --requirepass del servidor.
    # Genera una con: python -c "import secrets; print(secrets.token_hex(32))"
    REDIS_PASSWORD: SecretStr = SecretStr("")
    # Token para la REST API de Upstash (GET https://host/PING, puerto 443).
    # Necesario cuando el puerto TCP 6380 está bloqueado (redes domésticas/corporativas).
    # Cópialo desde Upstash Console → tu base de datos → "Connect" → REST API Token.
    REDIS_REST_TOKEN: str = ""

    @field_validator("API_THREADPOOL_TOKENS", mode="before")
    @classmethod
    def _validate_threadpool_tokens(cls, v: object) -> int:
        val = int(str(v))
        if val < 1:
            raise ValueError("API_THREADPOOL_TOKENS debe ser >= 1")
        return val

    @field_validator("API_ANALYTICS_STATEMENT_TIMEOUT_MS", mode="before")
    @classmethod
    def _validate_analytics_statement_timeout(cls, v: object) -> int:
        # 0 es válido (desactivado); lo que no puede ser es un negativo, que
        # Postgres rechazaría en el `SET LOCAL` de cada lectura analítica.
        val = int(str(v))
        if val < 0:
            raise ValueError("API_ANALYTICS_STATEMENT_TIMEOUT_MS debe ser >= 0 (0 = desactivado)")
        return val

    @model_validator(mode="after")
    def _validate_prod_forwarded_allow_ips(self) -> Self:
        """Impide confiar en el ``X-Forwarded-For`` de cualquier peer en producción.

        Con "*", uvicorn sobrescribe la IP del cliente con el primer elemento de
        la cabecera, que lo escribe el propio cliente (el proxy añade la IP real
        *detrás*). El atacante elige entonces qué IP ve la aplicación: el rate
        limiting y el lockout de login se esquivan rotando el valor, y la IP del
        audit log deja de ser evidencia de nada. Un valor vacío es igual de malo
        por la vía contraria: deja el campo sin configurar en un despliegue que
        sí está detrás de un proxy.
        """
        if not (self._is_prod_data and self._serves_http):
            return self
        entries = {ip.strip() for ip in self.FORWARDED_ALLOW_IPS.split(",") if ip.strip()}

        def _confia_en_todos(entrada: str) -> bool:
            """True si la entrada equivale a "confío en cualquier peer".

            No basta con comparar contra "*": tanto uvicorn (``_TrustedHosts``,
            uvicorn 0.46) como ``api.middleware._trusted_client_ip`` resuelven
            rangos CIDR, así que ``0.0.0.0/0`` (o ``::/0``) reproduce el agujero
            exacto que este validator existe para cerrar. Un prefijo de longitud
            0 cubre todo el espacio de direcciones de su familia.
            """
            if entrada == "*":
                return True
            try:
                return ipaddress.ip_network(entrada, strict=False).prefixlen == 0
            except ValueError:
                return False

        if not entries or any(_confia_en_todos(entry) for entry in entries):
            raise ValueError(
                "FORWARDED_ALLOW_IPS no puede estar vacío ni contener el comodín '*' "
                "(ni un rango que lo abarque todo, como '0.0.0.0/0' o '::/0') "
                "en ENV=prod/staging con APP_PROFILE=api: con '*' cualquier cliente "
                "puede falsificar su IP vía X-Forwarded-For y con ello se caen el "
                "rate limiting, el lockout de login y la trazabilidad del audit log. "
                "Configura la IP o el rango CIDR del reverse proxy que tenés delante "
                '(ej: FORWARDED_ALLOW_IPS="10.0.0.0/8").'
            )
        return self

    @model_validator(mode="after")
    def _validate_api_origin_secret(self) -> Self:
        """Un secreto de origen corto es un error, en cualquier entorno.

        Quien lo conozca elige la IP con la que cuentan las cuotas por IP
        (login, recuperación de contraseña, tope global), así que tiene que ser
        imposible de adivinar. Hay además un motivo concreto para el mínimo: si
        la variable falta en un entorno de Vercel, su transform manda el texto
        literal ``$API_ORIGIN_SECRET``, y ese texto no puede ser nunca un valor
        aceptado. Vacío sí vale: es «sin verificación», el comportamiento de
        antes de la opción B.
        """
        for nombre, campo in (
            ("API_ORIGIN_SECRET", self.API_ORIGIN_SECRET),
            ("API_ORIGIN_SECRET_PREVIOUS", self.API_ORIGIN_SECRET_PREVIOUS),
        ):
            valor = campo.get_secret_value()
            if valor and len(valor) < LONGITUD_MINIMA_CLAVE:
                raise ValueError(
                    f"{nombre} tiene que tener al menos {LONGITUD_MINIMA_CLAVE} "
                    "caracteres (o estar vacío). "
                    'Genera uno con: python -c "import secrets; print(secrets.token_hex(32))"'
                )
        return self

    @model_validator(mode="after")
    def _validate_prod_cors_origins(self) -> Self:
        """En producción, alertar si CORS_ALLOWED_ORIGINS está vacío y rechazar orígenes inseguros.

        La API responde con ``allow_credentials=True``: un ``*`` (Starlette
        refleja entonces el ``Origin`` de quien lleva cookie) o un origen que no
        sea ``https://`` entregaría la sesión a cualquier página. Solo el
        loopback puede ir por ``http://`` (depurar contra la API real).
        """
        if not (self._is_prod_data and self._serves_http):
            return self
        if not self.CORS_ALLOWED_ORIGINS:
            warnings.warn(
                "CORS_ALLOWED_ORIGINS está vacío en ENV=prod. Todas las solicitudes "
                "cross-origin serán bloqueadas. Configura los orígenes permitidos: "
                'CORS_ALLOWED_ORIGINS="https://app.example.com"',
                stacklevel=2,
            )
            return self
        inseguros = [
            origen
            for origen in (o.strip() for o in self.CORS_ALLOWED_ORIGINS.split(","))
            if origen and not _origen_cors_seguro(origen)
        ]
        if inseguros:
            raise ValueError(
                f"CORS_ALLOWED_ORIGINS tiene orígenes no admitidos en ENV={self.ENV}: "
                f"{', '.join(inseguros)}. Solo https://… (el comodín '*' y http:// no valen "
                "con cookies de sesión; el loopback sí puede ir por http)."
            )
        return self

    @model_validator(mode="after")
    def _validate_prod_redis(self) -> Self:
        """En producción, exigir REDIS_URL para cache compartido.

        Solo aplica al perfil ``api``: la caché de respuestas y los rate limits
        viven en el proceso HTTP. El scraper y los workers no la usan.
        """
        if self._is_prod_data and self._serves_http and not self.REDIS_URL:
            raise ValueError(
                "REDIS_URL es obligatorio en ENV=prod/staging con APP_PROFILE=api para cache "
                "compartido entre procesos. Formato: redis://[:password@]host[:port][/db]"
            )
        if (
            self._is_prod_data
            and self._serves_http
            and self.REDIS_URL
            and not self.REDIS_PASSWORD.get_secret_value()
        ):
            raise ValueError(
                "REDIS_PASSWORD es obligatorio en ENV=prod con APP_PROFILE=api. "
                'Genera uno con: python -c "import secrets; print(secrets.token_hex(32))"'
            )
        if self._is_prod_data and self._serves_http and _redis_publico_sin_tls(self.REDIS_URL):
            # Aviso y no error: el Redis interno de la plataforma va por `redis://`
            # dentro de su red privada y desde el repo no se ve cuál es el de prod.
            warnings.warn(
                "REDIS_URL usa redis:// contra un host público: contraseña y datos de "
                "caché y rate limit viajan sin cifrar. Usa rediss:// (TLS).",
                stacklevel=2,
            )
        return self
