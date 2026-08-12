"""Gestión del pool de conexiones Postgres (psycopg3).

Este módulo centraliza toda la lógica de conexión: creación, pooling,
context managers ``connect()`` / ``connect_read()``, y helpers de diagnóstico.
No contiene lógica de dominio ni DDL; esos residen en ``db.schema`` y ``db.upsert``.

**Postgres es el único motor soportado** (ADR-021), en producción, CI y
desarrollo local, via ``DATABASE_URL`` (postgresql://...). Turso/libSQL se
retiró en ADR-020 y SQLite en ADR-021; el schema lo gestiona exclusivamente
Alembic.

Paramstyle:
  El SQL del proyecto se escribe directamente en el paramstyle de psycopg3
  (``%s``). Hasta 2026-08 se escribía en dialecto ``?`` (qmark) y un shim
  (``_translate_qmarks``) lo reescribía en cada ``execute``; era herencia de
  cuando convivían dos motores, retirado con ADR-021. Consecuencia práctica al
  escribir SQL nuevo: un ``%`` **literal** dentro de una sentencia con
  parámetros debe doblarse (``%%``), porque psycopg lo interpreta como inicio
  de placeholder también dentro de los literales.
"""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from pydantic import SecretStr

from config import settings
from observability.logging import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Utilidades de tiempo
# ---------------------------------------------------------------------------


def now_utc() -> datetime:
    """Devuelve datetime actual en UTC (aware). Reemplaza datetime.utcnow()."""
    return datetime.now(UTC)


def now_utc_iso() -> str:
    """ISO 8601 del instante actual en UTC."""
    return now_utc().isoformat()


# ---------------------------------------------------------------------------
# Detección de backend (ADR-016)
# ---------------------------------------------------------------------------


# URL de Postgres inyectada por la suite de tests (ver tests/conftest.py).
# Tiene precedencia sobre _DB_PATH_OVERRIDE: cuando está puesta, los tests
# corren contra el mismo motor que producción en vez de contra SQLite local.
_PG_TEST_URL: str | None = None


def set_pg_test_url(url: str | None) -> None:
    """Fija (o limpia con None) la URL de Postgres para la suite de tests.

    Cada test recibe un schema aislado dentro del mismo Postgres (ver
    ``tests/conftest.py::_pg_schema``), por lo que la URL lleva un
    ``options=-csearch_path`` propio.
    """
    global _PG_TEST_URL, _db_initialized
    _PG_TEST_URL = url
    _db_initialized = False


def _database_url() -> str:
    """Devuelve DATABASE_URL del entorno o cadena vacía.

    ``settings.DATABASE_URL`` es un ``SecretStr`` en el caso normal, pero los
    tests hacen ``monkeypatch.setattr(settings, "DATABASE_URL", "")`` con un
    ``str`` plano — se soportan ambas formas.
    """
    if _PG_TEST_URL:
        return _PG_TEST_URL
    env_val = os.environ.get("DATABASE_URL", "")
    if env_val:
        return env_val
    attr_val = getattr(settings, "DATABASE_URL", "")
    if isinstance(attr_val, SecretStr):
        return attr_val.get_secret_value()
    return attr_val or ""


# ---------------------------------------------------------------------------
# Adaptador de interfaz sobre la conexión psycopg3
# ---------------------------------------------------------------------------


class _PgConnAdapter:
    """Expone una conexión psycopg3 con la interfaz que usan los call-sites.

    Une conexión y cursor en un solo objeto, de forma que ``execute`` devuelva
    algo encadenable con ``fetchone``/``fetchall``:
      - execute(sql, params) → self, con fetchone/fetchall/description/rowcount
      - executemany(sql, seq)
      - commit() / rollback()
      - close()

    No traduce el SQL: el paramstyle del proyecto es el nativo de psycopg3
    (``%s``). Hasta 2026-08 esta clase aplicaba un shim qmark→``%s``, retirado
    con ADR-021 junto al segundo motor que lo justificaba.
    """

    def __init__(self, pg_conn: Any, pool: Any = None) -> None:
        self._conn = pg_conn
        self._cur: Any = None
        # Pool del que salió la conexión: hay uno de escritura y otro de
        # lectura, y devolverla al equivocado corrompería ambos.
        self._pool = pool

    def execute(self, sql: str, params: Any = None) -> _PgConnAdapter:
        self._cur = self._conn.cursor()
        if params is None:
            self._cur.execute(sql)
        else:
            self._cur.execute(sql, params)
        return self

    def executemany(self, sql: str, seq: Any) -> None:
        with self._conn.cursor() as cur:
            cur.executemany(sql, seq)

    def fetchone(self) -> Any:
        if self._cur is None:
            return None
        return self._cur.fetchone()

    def fetchall(self) -> list[Any]:
        if self._cur is None:
            return []
        return list(self._cur.fetchall())

    @property
    def description(self) -> Any:
        return self._cur.description if self._cur else None

    @property
    def rowcount(self) -> int:
        """Filas afectadas por la última sentencia.

        24 call-sites de producción lo usan para saber si un UPDATE/DELETE tuvo
        efecto (``db/webhooks.py``, ``db/repositories/api_keys.py``,
        ``services/watchlist_rules.py``, ``db/job_locks.py``…). Faltaba en
        este adaptador, así que **todos** lanzaban ``AttributeError`` con backend
        Postgres. La suite no lo detectaba porque corría sobre SQLite (ADR-018).
        """
        if self._cur is None:
            return -1
        return int(self._cur.rowcount)

    # ``lastrowid`` NO se expone a propósito. psycopg3 no lo tiene, y emularlo
    # con ``SELECT lastval()`` era incorrecto: lastval() devuelve el último
    # valor generado por CUALQUIER secuencia de la sesión, en una sentencia
    # aparte. Con triggers en el schema (v61) basta que uno inserte en otra
    # tabla con identity para que el caller reciba un id ajeno sin error.
    # El equivalente correcto en Postgres es ``INSERT … RETURNING id``, que es
    # lo que usan hoy los call-sites (db/webhooks.py, db/events.py,
    # db/watchlist_empresas.py, services/watchlist_rules.py).

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        if self._cur:
            try:
                self._cur.close()
            except Exception:
                pass
        self._conn.close()

    def __enter__(self) -> _PgConnAdapter:
        return self

    def __exit__(self, *_: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# Pool Postgres (psycopg_pool.ConnectionPool)
# ---------------------------------------------------------------------------

_pg_pool: Any = None  # psycopg_pool.ConnectionPool | None — camino de escritura
_pg_read_pool: Any = None  # psycopg_pool.ConnectionPool | None — camino de lectura
_pg_pool_lock = threading.Lock()


def _url_options(url: str) -> str:
    """Devuelve el parámetro ``options`` embebido en la query string de ``url``.

    ``psycopg_pool`` pasa ``kwargs`` **por encima** de lo que traiga la URL, así
    que un ``options=...`` en la cadena de conexión se perdía en silencio al
    aplicarse los timeouts. Se extrae aquí para poder fusionarlo en vez de
    pisarlo (lo usa, por ejemplo, el ``search_path`` por test de la suite).
    """
    from urllib.parse import parse_qs, urlsplit

    if not url:
        return ""
    values = parse_qs(urlsplit(url).query).get("options")
    return values[-1] if values else ""


def _pg_connect_kwargs(url: str = "", *, read_only: bool = False) -> dict[str, Any]:
    """Parámetros libpq extra aplicados a cada conexión del pool Postgres.

    - ``options``: ``statement_timeout`` + ``idle_in_transaction_session_timeout``
      server-side. Evitan que una query descontrolada u hostil, o una transacción
      idle, claven una conexión del (pequeño) pool y lo saturen (DoS barato).
      Se **fusionan** con los que traiga la URL, que de otro modo se perderían.
    - ``connect_timeout``: no colgar indefinidamente si el pooler no responde.
    - ``sslrootcert``: CA raíz para ``sslmode=verify-full`` (si está configurada).
    - ``read_only``: añade ``default_transaction_read_only=on`` a nivel de sesión
      y abre la conexión en autocommit. Es lo que sustituye al
      ``SET TRANSACTION READ ONLY`` por bloque del camino de lectura: misma
      garantía (una escritura por esa vía lanza ``ReadOnlySqlTransaction``) sin
      gastar un round-trip por lectura.
    """
    kwargs: dict[str, Any] = {}
    stmt_ms = int(getattr(settings, "DB_STATEMENT_TIMEOUT_MS", 30_000))
    idle_ms = int(getattr(settings, "DB_IDLE_TX_TIMEOUT_MS", 60_000))
    opts: list[str] = []
    from_url = _url_options(url)
    if from_url:
        opts.append(from_url)
    if stmt_ms > 0:
        opts.append(f"-c statement_timeout={stmt_ms}")
    if idle_ms > 0:
        opts.append(f"-c idle_in_transaction_session_timeout={idle_ms}")
    if read_only:
        opts.append("-c default_transaction_read_only=on")
    if opts:
        kwargs["options"] = " ".join(opts)
    connect_timeout = int(getattr(settings, "DB_CONNECT_TIMEOUT", 10))
    if connect_timeout > 0:
        kwargs["connect_timeout"] = connect_timeout
    ca = getattr(settings, "DATABASE_SSL_ROOT_CERT", "") or ""
    if isinstance(ca, str) and ca.strip():
        kwargs["sslrootcert"] = ca.strip()
    if read_only:
        # En autocommit un SELECT no abre transacción, así que ``putconn`` no
        # tiene que emitir el ROLLBACK de cierre: el camino de lectura pasa de
        # 3 round-trips (SET + query + ROLLBACK) a 1.
        kwargs["autocommit"] = True
    return kwargs


def _pool_lifecycle_kwargs() -> dict[str, Any]:
    """``timeout``/``max_idle``/``max_lifetime`` del pool (lado cliente).

    Sin ``timeout`` una petición espera indefinidamente cuando el pool está
    agotado; sin reciclado, una conexión que el pooler de Supabase cortó por
    inactividad se entrega rota al siguiente que la pida. ``max_idle`` mantiene
    las conexiones ociosas por debajo de cualquier idle-timeout razonable del
    pooler, y ``max_lifetime`` recicla también la que sostiene ``min_size``.
    """
    kwargs: dict[str, Any] = {}
    acquire_timeout = float(getattr(settings, "DB_POOL_TIMEOUT", 10.0))
    if acquire_timeout > 0:
        kwargs["timeout"] = acquire_timeout
    max_idle = float(getattr(settings, "DB_POOL_MAX_IDLE_SECONDS", 120.0))
    if max_idle > 0:
        kwargs["max_idle"] = max_idle
    max_lifetime = float(getattr(settings, "DB_POOL_MAX_LIFETIME_SECONDS", 1800.0))
    if max_lifetime > 0:
        kwargs["max_lifetime"] = max_lifetime
    return kwargs


def _make_pg_configure(*, read_only: bool) -> Callable[[Any], None]:
    """Callback ``configure`` del pool: fija los ajustes de sesión con ``SET``.

    Duplica a propósito lo que ``_pg_connect_kwargs`` ya pide por ``options``,
    porque **ese camino no está llegando a las conexiones de la API**. Con
    ``DB_STATEMENT_TIMEOUT_MS`` a 30 s, ``pg_stat_statements`` registra
    consultas que solo ejecuta la API con picos de 110 s y 116 s
    (``get_filter_options``, ``overview_para_hoy``): con el timeout aplicado no
    habrían pasado de 30. Se pierden los tres ajustes, incluido el
    ``default_transaction_read_only`` del pool de lectura, que es una garantía
    de seguridad y no solo una optimización.

    La causa probable es que ``options`` es un parámetro de *arranque* de libpq
    y el pooler de Supabase no lo propaga. No está cerrado del todo: el
    comentario de ``db/upsert.py`` documenta un ``QueryCanceled`` a los 30 s en
    el healthcheck del scraper, así que por ese camino sí llegó alguna vez. Sea
    cual sea el motivo, un ``SET`` explícito quita la duda — y que atraviesa el
    pooler está verificado (se probó subiendo el timeout para una migración).

    ``set_config(..., false)`` en vez de ``SET`` a secas: viaja como una
    sentencia normal, acepta el valor como parámetro en lugar de interpolarlo,
    y ``false`` lo hace de sesión y no de transacción, que es lo que necesita
    una conexión reutilizada por el pool.

    Se conserva además el ``options`` de ``_pg_connect_kwargs``: cuando sí
    aplica lo hace desde el primer byte de la sesión, antes incluso de este
    callback.

    Los ajustes se leen en cada conexión y no al construir el pool, para que un
    cambio de configuración surta efecto en las conexiones nuevas sin recrear
    el pool entero.
    """

    def _configure(conn: Any) -> None:
        stmt_ms = int(getattr(settings, "DB_STATEMENT_TIMEOUT_MS", 30_000))
        idle_ms = int(getattr(settings, "DB_IDLE_TX_TIMEOUT_MS", 60_000))
        ajustes: list[tuple[str, str]] = []
        if stmt_ms > 0:
            ajustes.append(("statement_timeout", str(stmt_ms)))
        if idle_ms > 0:
            ajustes.append(("idle_in_transaction_session_timeout", str(idle_ms)))
        if read_only:
            ajustes.append(("default_transaction_read_only", "on"))
        if not ajustes:
            return
        with conn.cursor() as cur:
            for nombre, valor in ajustes:
                cur.execute("SELECT set_config(%s, %s, false)", (nombre, valor))
        # En el pool de escritura la conexión no está en autocommit, así que el
        # `set_config` abrió transacción: sin commit, el reset del pool haría
        # rollback y se perderían los ajustes (son transaccionales).
        if not getattr(conn, "autocommit", False):
            conn.commit()

    return _configure


def _build_pool(*, read_only: bool) -> Any:
    """Crea un ``ConnectionPool`` de escritura o de lectura."""
    try:
        from psycopg_pool import ConnectionPool
    except ImportError as exc:
        raise RuntimeError(
            "psycopg-pool no instalado. Ejecuta: pip install psycopg-pool>=3.2,<4"
        ) from exc

    default_size = getattr(settings, "DB_POOL_SIZE", 5)
    if read_only:
        pool_size = getattr(settings, "DB_READ_POOL_SIZE", 0) or default_size
    else:
        pool_size = default_size
    url = _database_url()
    conn_kwargs = _pg_connect_kwargs(url, read_only=read_only)
    lifecycle = _pool_lifecycle_kwargs()
    name = "read" if read_only else "write"
    try:
        pool = ConnectionPool(
            conninfo=url,
            min_size=1,
            max_size=max(pool_size, 2),
            kwargs=conn_kwargs,
            configure=_make_pg_configure(read_only=read_only),
            open=True,
            name=f"tenderflow-{name}",
            **lifecycle,
        )
    except Exception as exc:
        # No filtrar el DSN (con password) en el mensaje de error propagado.
        from observability.logging import redact_dsn

        raise RuntimeError(f"No se pudo crear el pool Postgres: {redact_dsn(str(exc))}") from None
    log.info(
        "pg_pool_created",
        pool=name,
        min=1,
        max=max(pool_size, 2),
        timeouts=conn_kwargs.get("options", "none"),
        ssl_ca=bool(conn_kwargs.get("sslrootcert")),
        acquire_timeout=lifecycle.get("timeout"),
        max_lifetime=lifecycle.get("max_lifetime"),
    )
    return pool


def _get_pg_pool() -> Any:
    """Devuelve (creando si es necesario) el pool de escritura."""
    global _pg_pool
    if _pg_pool is not None:
        return _pg_pool
    with _pg_pool_lock:
        if _pg_pool is None:
            _pg_pool = _build_pool(read_only=False)
    return _pg_pool


def _get_pg_read_pool() -> Any:
    """Devuelve (creando si es necesario) el pool de lectura.

    Es un pool aparte porque el modo solo-lectura se fija **en la sesión**
    (``default_transaction_read_only``), no por transacción: mezclarlo con las
    conexiones de escritura en un pool común haría que un writer heredase el
    modo de la conexión que le tocara.
    """
    global _pg_read_pool
    if _pg_read_pool is not None:
        return _pg_read_pool
    with _pg_pool_lock:
        if _pg_read_pool is None:
            _pg_read_pool = _build_pool(read_only=True)
    return _pg_read_pool


def pool_stats() -> dict[str, dict[str, int]]:
    """Estadísticas de ambos pools para métricas y diagnóstico.

    Devuelve ``{}`` para el pool que aún no se haya creado (lazy), sin forzar
    su creación: exponer la métrica no debe abrir conexiones por sí mismo.
    """
    stats: dict[str, dict[str, int]] = {}
    for name, pool in (("write", _pg_pool), ("read", _pg_read_pool)):
        if pool is None:
            continue
        try:
            stats[name] = dict(pool.get_stats())
        except Exception:
            log.debug("pg_pool_stats_unavailable", pool=name)
    return stats


def _close_pg_pool() -> None:
    """Cierra ambos pools Postgres si están abiertos."""
    global _pg_pool, _pg_read_pool
    with _pg_pool_lock:
        pools = [_pg_pool, _pg_read_pool]
        _pg_pool = None
        _pg_read_pool = None
    for pool in pools:
        if pool is not None:
            try:
                pool.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Estado global
# ---------------------------------------------------------------------------

# Bandera de inicialización: evita ejecutar init_db() más de una vez por proceso.
# db.schema.init_db() la pone a True; set_pg_test_url() la resetea.
_db_initialized = False


# Whitelist de identificadores SQL válidos: solo alfanuméricos y guiones bajos.
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_identifier(name: str) -> str:
    """Valida que ``name`` sea un identificador SQL seguro (previene inyección)."""
    if not _SAFE_IDENTIFIER_RE.match(name):
        raise ValueError(f"Identificador SQL no válido: {name!r}")
    return name


def get_table_columns(conn: Any, table: str) -> set[str]:
    """Devuelve el conjunto de nombres de columna de ``table``.

    Consulta ``information_schema``, con fallback a ``SELECT * … LIMIT 0`` +
    ``cursor.description``. Devuelve conjunto vacío si la tabla no existe o no
    se puede inspeccionar.

    Raises:
        ValueError: si ``table`` contiene caracteres no válidos.
    """
    _validate_identifier(table)

    try:
        cur = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
            (table,),
        )
        rows = cur.fetchall()
        if rows:
            return {r[0] for r in rows}
    except Exception:
        pass
    # Fallback: SELECT * LIMIT 0
    try:
        cur = conn.execute(f"SELECT * FROM {table} LIMIT 0")
        if cur.description:
            return {d[0] for d in cur.description}
    except Exception:
        pass
    return set()


# ---------------------------------------------------------------------------
# Creación y ciclo de vida de conexiones
# ---------------------------------------------------------------------------


def _create_pg_connection(*, read_only: bool = False) -> _PgConnAdapter:
    """Toma una conexión del pool correspondiente (lectura o escritura).

    Un agotamiento del pool se contabiliza en ``db_pool_acquire_timeout_total``
    antes de propagarse: es el modo de fallo más probable bajo carga y sin esta
    métrica era invisible.
    """
    pool = _get_pg_read_pool() if read_only else _get_pg_pool()
    try:
        raw_conn = pool.getconn()
    except Exception as exc:
        if type(exc).__name__ == "PoolTimeout":
            from observability.runtime_metrics import db_pool_acquire_timeout_total

            db_pool_acquire_timeout_total.inc()
            log.warning("pg_pool_acquire_timeout", pool="read" if read_only else "write")
        raise
    return _PgConnAdapter(raw_conn, pool=pool)


def _return_pg_connection(adapter: _PgConnAdapter) -> None:
    """Devuelve la conexión subyacente a su pool de origen."""
    pool = adapter._pool if adapter._pool is not None else _pg_pool
    if pool is not None:
        try:
            pool.putconn(adapter._conn)
        except Exception:
            try:
                adapter._conn.close()
            except Exception:
                pass


def _get_conn(*, read_only: bool = False) -> Any:
    """Devuelve una conexión del pool Postgres gestionado (psycopg_pool)."""
    if not _database_url():
        raise RuntimeError(
            "DATABASE_URL no está configurada. Postgres es el único motor "
            "soportado desde ADR-021: levantá el servicio con "
            "`docker compose up -d postgres` o apuntá DATABASE_URL a tu "
            "instancia."
        )
    return _create_pg_connection(read_only=read_only)


def _return_conn(conn: Any) -> None:
    """Devuelve la conexión al pool Postgres."""
    if isinstance(conn, _PgConnAdapter):
        _return_pg_connection(conn)


def close_pool() -> None:
    """Cierra el pool Postgres compartido."""
    _close_pg_pool()


# ---------------------------------------------------------------------------
# Context managers públicos
# ---------------------------------------------------------------------------


@contextmanager
def connect() -> Iterator[Any]:
    """Context manager de escritura. Hace commit al salir, rollback en error.

    Instrumenta latencia de commit; los eventos se persisten en ops_events via
    buffer en memoria + flush best-effort (ver observability/ops_events.py).

    Toma la conexión del pool de escritura; para lecturas usá ``connect_read``,
    que además impide escribir por esa vía.
    """
    import time as _time

    from observability.ops_events import (
        _piggyback_flush,
        dec_writers,
        inc_writers,
        record_event,
        record_writers_high_if_needed,
    )
    from observability.runtime_metrics import (
        db_concurrent_writers,
        db_write_duration_seconds,
    )

    conn = _get_conn()
    db_concurrent_writers.inc()
    n_writers = inc_writers()
    record_writers_high_if_needed(n_writers)
    try:
        yield conn
        t0 = _time.monotonic()
        conn.commit()
        dur = _time.monotonic() - t0
        db_write_duration_seconds.observe(dur)
        if dur > 0.5:
            record_event("write_slow", value=round(dur, 3))
        # Flush best-effort del buffer de ops_events piggyback al commit exitoso
        _piggyback_flush()
    except Exception:
        conn.rollback()
        raise
    finally:
        db_concurrent_writers.inc(-1)
        dec_writers()
        _return_conn(conn)


@contextmanager
def connect_read() -> Iterator[Any]:
    """Context manager de SOLO LECTURA.

    La garantía es la misma de siempre —cualquier INSERT/UPDATE/DELETE/DDL mal
    dirigido por esta vía lanza ``ReadOnlySqlTransaction`` en vez de ejecutarse
    y ser revertido en silencio— pero ahora la impone la **sesión**: el pool de
    lectura abre sus conexiones con ``default_transaction_read_only=on`` y en
    autocommit (ver ``_pg_connect_kwargs``).

    El motivo es de latencia. Hasta 2026-08 cada bloque emitía
    ``SET TRANSACTION READ ONLY`` y un ``ROLLBACK`` de cierre alrededor de la
    query: tres round-trips por lectura, que a los ~80 ms de RTT contra Supabase
    ponían el suelo de cualquier lectura en ~240 ms, con 209 bloques de lectura
    en producción. Es la misma clase de defecto que ya se corrigió en el camino
    de escritura (2201 → 6 viajes por lote), que nunca se auditó en lectura.
    En autocommit un SELECT no abre transacción, así que ``putconn`` tampoco
    tiene nada que revertir al devolver la conexión.
    """
    import time as _time

    from observability.runtime_metrics import db_read_duration_seconds

    conn = _get_conn(read_only=True)
    t0 = _time.monotonic()
    try:
        yield conn
    finally:
        db_read_duration_seconds.observe(_time.monotonic() - t0)
        _return_conn(conn)


def ping() -> bool:
    """``SELECT 1`` contra el camino de lectura. True si la BD responde.

    Es el chequeo de conectividad que consume ``services/health.py``; vive aquí
    para que el SQL no salga de ``db/`` (ADR-022).
    """
    try:
        with connect_read() as conn:
            conn.execute("SELECT 1").fetchone()
        return True
    except Exception:
        log.warning("db_ping_failed", exc_info=True)
        return False
