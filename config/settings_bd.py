"""Settings de la base de datos: conexión, TLS, pools, timeouts y ventanas de lectura.

Módulo hermano de ``config/settings.py`` (P3 «Los dos módulos-dios»): ``Settings``
hereda de esta clase, así que los nombres de las variables de entorno y el
acceso (``settings.DATABASE_URL``) son los de siempre. Incluye la credencial de
administración (``database_admin_url``), que a propósito no es un campo.

Sin ``model_config`` propio, por lo mismo que ``config/settings_resumen.py``.
"""

from __future__ import annotations

import os
import warnings
from typing import Self

from pydantic import SecretStr, field_validator, model_validator

from config.settings_entorno import EntornoSettings


def _extract_sslmode(url: str) -> str | None:
    """Devuelve el valor de ``sslmode`` de una DATABASE_URL, o None si no está.

    Robusto frente a passwords con caracteres especiales: solo parsea la query
    string (tras ``?``). Devuelve el valor en minúsculas.
    """
    from urllib.parse import parse_qs, urlsplit

    values = parse_qs(urlsplit(url).query).get("sslmode")
    if not values:
        return None
    return values[-1].strip().lower()


# Hosts sin red externa que interceptar — sslmode no aporta nada real ahí.
_LOCAL_DB_HOSTS = {"localhost", "127.0.0.1", "::1"}


# Techo por consulta para los perfiles que no sirven HTTP (ver
# ``Settings._relax_batch_statement_timeout``). Cinco minutos cubre con margen
# la consulta batch más lenta medida (76 s) sin dejar a un job colgado media
# hora contra la base de producción.
_BATCH_STATEMENT_TIMEOUT_MS = 300_000


def _extract_host(url: str) -> str | None:
    """Devuelve el hostname de una DATABASE_URL, o None si no se puede parsear."""
    from urllib.parse import urlsplit

    try:
        return urlsplit(url).hostname
    except ValueError:
        return None


class BaseDatosSettings(EntornoSettings):
    """Postgres/Supabase: DSN, TLS, pools, timeouts y flags de lectura de columnas nuevas."""

    # ── DB / Upsert ──────────────────────────────────────────────────────
    # Tamaño de chunk para upsert_licitaciones_with_history. Cada chunk
    # se ejecuta en su propia transacción, liberando el write lock entre chunks.
    UPSERT_CHUNK_SIZE: int = 500

    # ── Postgres / Supabase (ADR-016, F3) ────────────────────────────────
    # Único motor desde ADR-021 (SQLite retirado).
    # Formato: postgresql://user:pass@host:5432/db?sslmode=require  # pragma: allowlist secret
    # En Supabase: usar Supavisor session pooler (puerto 5432) para compatibilidad
    # con GH Actions (IPv4-only) y evitar conflictos con PREPARE.
    DATABASE_URL: SecretStr = SecretStr("")

    # Ruta al certificado CA raíz de Supabase (Dashboard → Database → SSL).
    # Necesario para usar ``sslmode=verify-full`` (verifica cadena + hostname del
    # servidor, previene MITM). No es un secreto (cert público). Si está vacío y
    # el DSN pide verify-full, psycopg buscará la CA del sistema.
    DATABASE_SSL_ROOT_CERT: str = ""

    # Timeouts server-side aplicados a cada conexión del pool Postgres. Protegen
    # contra queries descontroladas o transacciones idle que clavan una conexión
    # y saturan el pool (pequeño). En milisegundos; 0 = sin límite (no recomendado).
    #
    # El default vale para el perfil ``api``, que es donde el pool es un recurso
    # compartido y escaso. Los perfiles batch lo reciben más alto por
    # ``_relax_batch_statement_timeout``: ver ese validator antes de asumir que
    # 30 s es el valor efectivo en un job.
    DB_STATEMENT_TIMEOUT_MS: int = 30_000
    DB_IDLE_TX_TIMEOUT_MS: int = 60_000
    # Timeout (segundos) para establecer la conexión TCP/TLS al pooler.
    DB_CONNECT_TIMEOUT: int = 10

    # ── Base de datos ─────────────────────────────────────────────────────
    DB_POOL_SIZE: int = 5
    # Segundos de espera por una conexión libre antes de fallar. Sin este
    # límite del lado cliente, una petición espera indefinidamente cuando el
    # pool está agotado y la saturación se manifiesta como cuelgue, no como
    # error medible (ver `db_pool_acquire_timeout_total`).
    DB_POOL_TIMEOUT: float = 10.0
    # Tamaño del pool de LECTURA (`connect_read`). 0 = mismo que DB_POOL_SIZE.
    # Son pools separados porque el modo solo-lectura se fija en la sesión.
    DB_READ_POOL_SIZE: int = 0
    # Reciclado de conexiones (segundos). `max_idle` mantiene las ociosas por
    # debajo del idle-timeout del pooler de Supabase, que si no las corta y el
    # pool entrega una conexión muerta; `max_lifetime` recicla también la que
    # sostiene `min_size`. 0 desactiva cada uno.
    DB_POOL_MAX_IDLE_SECONDS: float = 120.0
    DB_POOL_MAX_LIFETIME_SECONDS: float = 1800.0
    # Conexiones que cada pool mantiene abiertas aunque no haya tráfico
    # (`min_size`). Con 1, tras un rato sin peticiones una ráfaga abría el resto
    # (TLS + SCRAM + los `set_config` de sesión) y psycopg_pool crece de una en
    # una: la última petición esperaba todas las aperturas. Estos valores son
    # los de la API en prod/staging; el resto de perfiles y entornos se quedan
    # en 1 (`_pool_minimo_por_perfil`) salvo valor explícito. Nunca pasan de
    # `DB_POOL_SIZE`/`DB_READ_POOL_SIZE`, que siguen siendo el techo. Que una
    # conexión ociosa de estas no se entregue muerta lo garantiza la
    # verificación por checkout de `db/connection.py::_make_pg_check`.
    DB_POOL_MIN_SIZE: int = 2
    DB_READ_POOL_MIN_SIZE: int = 4

    # ── Núcleo tipado (T2, v133) ────────────────────────────────────────────
    # Lectura de las columnas sombra (`fecha_publicacion_ts`, `fecha_limite_ts`,
    # `importe_num`, `duracion_valor_num`) en los fragmentos de lectura dual de
    # `db/sql_fragments.py`. Default False y se queda así hasta que el backfill
    # esté VERIFICADO en producción con cero divergencias
    # (`docs/runbooks/nucleo-tipado-ventana.md`): con el flag off, cada
    # fragmento devuelve la columna vieja byte a byte. La escritura dual no
    # depende de esto — `db/upsert.py` escribe las sombras en cuanto existen.
    NUCLEO_TIPADO_LECTURA: bool = False
    # ── Fechas a timestamptz, fase 1 (v159/v160) ───────────────────────────
    # Lectura de las sombras `<columna>_ts` de `db/fechas_ts.py` en los
    # fragmentos de `db.sql_fragments.instante_sql` (novedades, historial,
    # notificaciones) y en `MAX(fecha_extraccion_ts)`. Default False hasta que
    # `scripts/backfill_fechas_ts.py --verificar` dé cero divergencias en
    # producción Y `v160` esté aplicada con su índice válido
    # (`docs/runbooks/fechas-ts-ventana.md`). La escritura no depende de esto.
    FECHAS_TS_LECTURA: bool = False
    # ── Seguimiento unificado (T1, ADR-031 §B fase 2, v130) ────────────────
    # Con True, `GET /watchlist/items`, `GET /competitive/watchlist` y los
    # descartes del Radar deciden la pertenencia leyendo `follows`; la tabla de
    # origen sólo aporta las columnas que `follows` no tiene (nota, correo,
    # frecuencia, acción del descarte). Default False hasta que
    # `scripts/check_follows_paridad.py` dé cero diferencias en producción.
    # Las escrituras no dependen de esto: la doble escritura ya está activa.
    FOLLOWS_LECTURA: bool = False

    @field_validator("DB_POOL_SIZE", mode="before")
    @classmethod
    def _validate_pool_size(cls, v: object) -> int:
        val = int(str(v))
        if val < 1:
            raise ValueError("DB_POOL_SIZE debe ser >= 1")
        return val

    @field_validator("DB_POOL_MIN_SIZE", "DB_READ_POOL_MIN_SIZE", mode="before")
    @classmethod
    def _validate_pool_min_size(cls, v: object) -> int:
        val = int(str(v))
        if val < 1:
            raise ValueError("DB_POOL_MIN_SIZE y DB_READ_POOL_MIN_SIZE deben ser >= 1")
        return val

    @model_validator(mode="after")
    def _relax_batch_statement_timeout(self) -> Self:
        """Sube el techo de tiempo por consulta en los perfiles que no sirven HTTP.

        Los 30 s del default protegen un recurso que solo existe en la API: un
        pool de 12 conexiones compartido por todas las peticiones, donde una
        consulta clavada se lleva por delante a endpoints que no calculan nada.
        Un job de GitHub Actions no tiene esa restricción —proceso propio, una
        tarea, y su propio timeout de workflow— y sí tiene consultas que
        legítimamente pasan de 30 s: la auditoría diaria de
        ``domain-truth.yml`` mide 76 s, y el precálculo de KPIs agrega
        ``adjudicaciones`` entera en unos 42 s.

        Se deriva de ``APP_PROFILE`` en vez de declararlo en cada workflow
        porque es el eje que el proyecto ya usa para esto (los ocho workflows
        que tocan la BD declaran ``scraper``, y Render declara ``api``), y así
        no depende de que nadie recuerde añadir una variable al octavo.

        Un valor explícito en el entorno gana siempre: ``model_fields_set``
        solo contiene los campos que llegaron de fuera, no los defaults.
        """
        if (
            "DB_STATEMENT_TIMEOUT_MS" not in self.model_fields_set
            and not self._serves_http
            and not self._es_mcp  # atiende peticiones de usuario, no es un batch
        ):
            self.DB_STATEMENT_TIMEOUT_MS = _BATCH_STATEMENT_TIMEOUT_MS
        return self

    @model_validator(mode="after")
    def _pool_minimo_por_perfil(self) -> Self:
        """Solo la API de prod/staging mantiene conexiones calientes de sobra.

        Los defaults de ``DB_POOL_MIN_SIZE``/``DB_READ_POOL_MIN_SIZE`` son los
        de la API en producción, que es donde una ráfaga tras un rato sin
        tráfico se nota en la latencia. Un job, el worker o un entorno de
        desarrollo no tienen esa ráfaga, y cada conexión ociosa que mantuvieran
        ocuparía una ranura del pooler de Supabase compartido (ver la nota de
        presupuesto de conexiones en ``render.yaml``); la suite de tests,
        además, recrea los pools en cada test. Ahí vuelven a 1, como antes.

        Mismo criterio que ``_relax_batch_statement_timeout``: se deriva del
        perfil y un valor explícito en el entorno gana siempre.
        """
        if self._serves_http and self._is_prod_data:
            return self
        for nombre in ("DB_POOL_MIN_SIZE", "DB_READ_POOL_MIN_SIZE"):
            if nombre not in self.model_fields_set:
                setattr(self, nombre, 1)
        return self

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _validate_database_url_scheme(cls, v: object) -> object:
        """Rechaza esquemas peligrosos en DATABASE_URL.

        Solo se permiten ``postgresql://`` y ``postgres://``. Un valor vacío
        se acepta aquí; lo que exige una URL es quien abre la conexión. El chequeo de ``sslmode`` vive en ``_validate_prod_database_ssl``
        (model_validator) porque depende de ``self.ENV``, no disponible aún
        en un field_validator per-campo.
        """
        value = v.get_secret_value() if isinstance(v, SecretStr) else v
        if not isinstance(value, str) or not value:
            return v
        allowed = ("postgresql://", "postgres://")
        if not value.startswith(allowed):
            raise ValueError(
                f"DATABASE_URL tiene un esquema no permitido. "
                f"Se esperaba uno de {allowed}, se recibió un valor que no matchea."
            )
        return v

    @model_validator(mode="after")
    def _validate_prod_database_ssl(self) -> Self:
        """Exigir TLS verificado en DATABASE_URL (Postgres/Supabase) cuando aplica.

        ``sslmode=require`` cifra pero NO valida el certificado ni el hostname del
        servidor: un atacante capaz de interponerse (MITM) puede presentar su
        propio certificado y capturar credenciales + datos. ``verify-full`` valida
        cadena + hostname (necesita ``DATABASE_SSL_ROOT_CERT`` = CA de Supabase).

        La política se aplica (``enforce``) si ``ENV`` es prod/staging **o** si el
        host es remoto (no localhost/127.0.0.1/::1) — independientemente de ENV.
        F4 (2026-07-13): esto cierra el gap de ``scrape-daily.yml``, que corre con
        ``ENV=dev`` pero apunta a Supabase real — antes esa combinación solo
        avisaba, nunca bloqueaba una conexión sin TLS verificado. Un host local
        (docker-compose/desarrollo con Postgres en la propia máquina) no tiene red
        externa que interceptar, así que ahí sigue bastando con avisar.

        Política cuando ``enforce``:
          - ``sslmode`` ausente → error (psycopg podría negociar sin TLS).
          - ``disable``/``allow``/``prefer`` → error (no garantizan TLS; cierran el
            downgrade silencioso que el chequeo por substring anterior permitía).
          - ``require``/``verify-ca`` → permitido con warning (se recomienda verify-full).
          - ``verify-full`` → OK.
        Si no aplica (dev + host local), solo se avisa.
        """
        url = self.DATABASE_URL.get_secret_value()
        if not url:
            return self

        host = _extract_host(url)
        is_prod = self.ENV in ("prod", "staging")
        is_remote = host not in _LOCAL_DB_HOSTS
        enforce = is_prod or is_remote
        sslmode = _extract_sslmode(url)

        if sslmode is None:
            if enforce:
                reason = (
                    "en ENV=prod/staging"
                    if is_prod
                    else f"apuntando a un host remoto ({host}), sea cual sea ENV"
                )
                raise ValueError(
                    f"DATABASE_URL no especifica sslmode {reason}. Añade "
                    "'?sslmode=verify-full' (con DATABASE_SSL_ROOT_CERT) para exigir "
                    "TLS verificado en la conexión a Postgres/Supabase."
                )
            warnings.warn(
                "DATABASE_URL no especifica sslmode. Añade '?sslmode=verify-full' "
                "para exigir TLS verificado en la conexión a Postgres/Supabase.",
                stacklevel=2,
            )
            return self

        insecure = {"disable", "allow", "prefer"}
        if sslmode in insecure:
            if enforce:
                reason = (
                    "en ENV=prod/staging"
                    if is_prod
                    else f"apuntando a un host remoto ({host}), sea cual sea ENV"
                )
                raise ValueError(
                    f"DATABASE_URL usa sslmode={sslmode!r}, que no garantiza TLS, {reason}. "
                    "Usa 'verify-full' (recomendado) o al menos 'require'."
                )
            warnings.warn(
                f"DATABASE_URL usa sslmode={sslmode!r}, que puede conectar sin TLS. "
                "Usa 'verify-full' para exigir TLS verificado.",
                stacklevel=2,
            )
            return self

        if enforce and sslmode in ("require", "verify-ca"):
            warnings.warn(
                f"DATABASE_URL usa sslmode={sslmode!r}: cifra pero no valida "
                "completamente el certificado del servidor. Se recomienda "
                "'verify-full' con DATABASE_SSL_ROOT_CERT (CA de Supabase) para "
                "prevenir ataques MITM.",
                stacklevel=2,
            )
        return self


# ── Credencial de administración de la base (O0.4) ───────────────────────
# `DATABASE_ADMIN_URL` es el DSN del rol DUEÑO del schema: el único que puede
# hacer DDL y el único que bypassa la RLS de `v52_rls_lockdown`. Existe para que
# `alembic upgrade` deje de correr con la misma credencial que la app
# (`scripts/setup_pg_roles.sql`, docs/runbooks/persistence-tripwires.md).
#
# Por qué NO es un campo de `Settings`: si lo fuera, cualquier módulo de la API
# podría leerla con `settings.DATABASE_ADMIN_URL` y el «solo para migraciones»
# quedaría en una convención que nadie comprueba. Al vivir fuera de la clase,
# `extra="ignore"` descarta la variable al construir `Settings`, así que el
# objeto que la API tiene entre manos ni siquiera la contiene: no hay atributo
# que leer, ni por accidente ni a propósito. El acceso pasa obligatoriamente por
# la función de abajo, que se niega a servirla al perfil que atiende HTTP.
_ADMIN_DB_URL_ENV = "DATABASE_ADMIN_URL"

# Perfiles a los que la función SÍ entrega la credencial. Es una allowlist y no
# una lista de prohibidos, y la diferencia es la que separa fail-closed de
# fail-open: con una lista de prohibidos (`{"api"}`), cualquier valor que no
# estuviera en ella —un `worker` de mañana, un `APP_PROFILE=apiv2` mal escrito,
# un perfil nuevo que nadie recuerde añadir aquí— recibiría el DSN con DDL sin
# que nada fallara. Solo `scraper` la necesita: es el perfil con el que corre
# `.github/workflows/migrate.yml`, el único plano que aplica migraciones.
_PERFILES_CON_CREDENCIAL_ADMIN = frozenset({"scraper"})

# Perfil que se asume cuando el proceso no declara ninguno. Replica el de
# `Settings.APP_PROFILE` y `test_settings_admin_url` fija que sigan siendo el
# mismo; con la allowlist de arriba el efecto es el mismo mire por donde se
# mire, pero el mensaje de error nombra un perfil concreto en vez de una cadena
# vacía.
_PERFIL_POR_DEFECTO = "api"


def database_admin_url() -> str | None:
    """DSN del rol administrador, o ``None`` si el cutover sigue pendiente.

    Se lee de ``os.environ`` y no de ``Settings`` por lo explicado arriba: es la
    única vía de acceso, y refleja el entorno del proceso en el momento de la
    llamada (un test puede fijar ``APP_PROFILE`` sin reconstruir el singleton).

    :raises RuntimeError: para cualquier ``APP_PROFILE`` que no sea ``scraper``,
        incluido el caso de no declararlo. Que un proceso distinto del que migra
        pida esta credencial no es un error de configuración recuperable sino un
        fallo de diseño en quien llama, y tiene que doler en el acto.
    """
    perfil = os.environ.get("APP_PROFILE", "").strip().lower() or _PERFIL_POR_DEFECTO
    if perfil not in _PERFILES_CON_CREDENCIAL_ADMIN:
        permitidos = ", ".join(sorted(_PERFILES_CON_CREDENCIAL_ADMIN))
        raise RuntimeError(
            f"{_ADMIN_DB_URL_ENV} no está disponible con APP_PROFILE={perfil!r}: es la "
            "credencial con DDL y sin RLS, reservada a las migraciones "
            f"(.github/workflows/migrate.yml, APP_PROFILE={permitidos}). La API usa "
            "DATABASE_URL, que apunta al rol tenderflow_app."
        )
    return os.environ.get(_ADMIN_DB_URL_ENV, "").strip() or None
