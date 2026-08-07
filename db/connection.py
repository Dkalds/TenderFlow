"""Gestión del pool de conexiones Postgres (psycopg3).

Este módulo centraliza toda la lógica de conexión: creación, pooling,
context managers ``connect()`` / ``connect_read()``, y helpers de diagnóstico.
No contiene lógica de dominio ni DDL; esos residen en ``db.schema`` y ``db.upsert``.

**Postgres es el único motor soportado** (ADR-021), en producción, CI y
desarrollo local, via ``DATABASE_URL`` (postgresql://...). Turso/libSQL se
retiró en ADR-020 y SQLite en ADR-021; el schema lo gestiona exclusivamente
Alembic.

Shim de paramstyle:
  El SQL del proyecto se escribe en dialecto ``?`` (qmark) y ``_translate_qmarks``
  lo reescribe a ``%s`` para psycopg3, respetando literales y comentarios.
  Desde ADR-021 esto ya **no** es un hack de compatibilidad entre motores sino
  una convención de estilo: queda como deuda acotada y su retirada (1123
  ocurrencias en 57 archivos) es un ítem de backlog separado.
"""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Iterator
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
# Shim qmark → %s (activo solo con Postgres, F3a → F5)
# ---------------------------------------------------------------------------

# Patrón para tokenizar SQL y detectar ? fuera de literales/comentarios.
# Captura: strings simples, strings dobles, comentarios de línea, bloque, y ?
#
# IMPORTANTE: los literales SQL estándar (Postgres con standard_conforming_strings=on,
# el default) NO usan backslash como escape -- una comilla literal dentro de un string
# se escribe doblada (''), no con \'. Un patrón tipo (?:[^'\\]|\\.)* trata \' como
# "comilla escapada" y NO cierra el string ahi, tragándose el resto de la query
# (incluyendo placeholders ? reales) como si siguiera dentro del literal. Esto rompe
# de forma silenciosa cualquier SQL con ESCAPE '\' seguido de más '?' (patrón usado en
# los fallbacks LIKE de db/repositories/licitaciones.py). Por eso aquí NO se trata
# el backslash como escape: solo '' (comilla doblada) cierra/reabre un string.
_SQL_TOKEN_RE = re.compile(
    r"('(?:[^']|'')*')"  # string comillas simples (SQL estándar: '' escapa, no \')
    r'|("(?:[^"]|"")*")'  # identificador comillas dobles (mismo criterio)
    r"|(--[^\n]*)"  # comentario de línea
    r"|(/\*.*?\*/)"  # comentario de bloque (non-greedy)
    r"|(\?)",  # placeholder qmark
    re.DOTALL,
)


def _translate_qmarks(sql: str, *, has_params: bool = True) -> str:
    """Reescribe ``?`` → ``%s`` en SQL respetando literales y comentarios.

    Se invoca siempre desde ``_PgConnAdapter``, que es el único camino a la BD
    desde ADR-021 (Postgres es el único motor).

    Cuando la sentencia lleva parámetros, psycopg interpreta ``%`` como inicio
    de placeholder **también dentro de los literales**, así que un patrón como
    ``LIKE 'daily|%'`` revienta con ``only '%s', '%b', '%t' are allowed as
    placeholders``. Hay que doblarlo a ``%%``.

    Sin este escape, cualquier query que combine un ``LIKE`` con comodín y
    parámetros fallaba en Postgres. El caso real:
    ``ExtractionRunRepository.load_recent_daily_statuses`` —
    ``WHERE notas LIKE 'daily|%' ... LIMIT ?`` — que además captura la
    excepción y devuelve ``[]``, de modo que la alerta de fallos consecutivos
    del feed diario nunca se disparaba en producción. La suite no lo veía
    porque corría sobre SQLite (ADR-018).

    Args:
        sql: Sentencia en dialecto qmark.
        has_params: Si la sentencia se ejecuta con parámetros. Si es False,
            psycopg no interpreta ``%`` y doblarlo corrompería el literal.
    """

    def _replace(m: re.Match[str]) -> str:
        # Grupo 5: el placeholder qmark.
        if m.group(5) is not None:
            return "%s"
        # Grupos 1-2: literales de string/identificador. El `%` que contengan
        # es dato, no placeholder: se dobla para que psycopg no lo tome como tal.
        token = m.group(0)
        if has_params and (m.group(1) is not None or m.group(2) is not None):
            return token.replace("%", "%%")
        # Grupos 3-4: comentarios — preservar tal cual.
        return token

    return _SQL_TOKEN_RE.sub(_replace, sql)


# ---------------------------------------------------------------------------
# Adaptador psycopg3 que aplica el shim automáticamente
# ---------------------------------------------------------------------------


class _PgConnAdapter:
    """Envuelve una conexión psycopg3 y traduce qmark→%s en execute/executemany.

    Expone la misma interfaz mínima que las conexiones libsql para que los
    call-sites existentes funcionen sin cambios:
      - execute(sql, params) → cursor con fetchone/fetchall/description
      - executemany(sql, seq)
      - commit() / rollback()
      - close()

    El shim se aplica en execute/executemany. description es un alias de
    cursor.description de la última query.
    """

    def __init__(self, pg_conn: Any) -> None:
        self._conn = pg_conn
        self._cur: Any = None

    def execute(self, sql: str, params: Any = None) -> _PgConnAdapter:
        translated = _translate_qmarks(sql, has_params=params is not None)
        self._cur = self._conn.cursor()
        if params is None:
            self._cur.execute(translated)
        else:
            self._cur.execute(translated, params)
        return self

    def executemany(self, sql: str, seq: Any) -> None:
        translated = _translate_qmarks(sql, has_params=True)
        with self._conn.cursor() as cur:
            cur.executemany(translated, seq)

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
        ``services/watchlist_rules.py``, ``services/job_locks.py``…). Faltaba en
        este adaptador, así que **todos** lanzaban ``AttributeError`` con backend
        Postgres. La suite no lo detectaba porque corría sobre SQLite (ADR-018).
        """
        if self._cur is None:
            return -1
        return int(self._cur.rowcount)

    @property
    def lastrowid(self) -> Any:
        """Id autogenerado por el último INSERT.

        psycopg3 no expone ``lastrowid``. Antes esta propiedad devolvía
        ``self._cur.rownumber``, que es la **posición del cursor en el
        resultado**, no un id: ``db/users.py::create_user`` y
        ``db/webhooks.py`` devolvían un identificador inventado (típicamente 0)
        en producción.

        ``lastval()`` devuelve el último valor generado por una secuencia en la
        sesión actual, que es el equivalente correcto tras un INSERT sobre una
        PK serial/identity. Si el INSERT no tocó ninguna secuencia, Postgres
        lanza ``ObjectNotInPrerequisiteState``; se devuelve None, que los
        call-sites ya tratan (``int(cur.lastrowid or 0)``).
        """
        if self._cur is None:
            return None
        try:
            with self._conn.cursor() as cur:
                cur.execute("SELECT lastval()")
                row = cur.fetchone()
                return row[0] if row else None
        except Exception:
            log.debug("pg_lastrowid_unavailable")
            return None

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

_pg_pool: Any = None  # psycopg_pool.ConnectionPool | None
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


def _pg_connect_kwargs(url: str = "") -> dict[str, Any]:
    """Parámetros libpq extra aplicados a cada conexión del pool Postgres.

    - ``options``: ``statement_timeout`` + ``idle_in_transaction_session_timeout``
      server-side. Evitan que una query descontrolada u hostil, o una transacción
      idle, claven una conexión del (pequeño) pool y lo saturen (DoS barato).
      Se **fusionan** con los que traiga la URL, que de otro modo se perderían.
    - ``connect_timeout``: no colgar indefinidamente si el pooler no responde.
    - ``sslrootcert``: CA raíz para ``sslmode=verify-full`` (si está configurada).
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
    if opts:
        kwargs["options"] = " ".join(opts)
    connect_timeout = int(getattr(settings, "DB_CONNECT_TIMEOUT", 10))
    if connect_timeout > 0:
        kwargs["connect_timeout"] = connect_timeout
    ca = getattr(settings, "DATABASE_SSL_ROOT_CERT", "") or ""
    if isinstance(ca, str) and ca.strip():
        kwargs["sslrootcert"] = ca.strip()
    return kwargs


def _get_pg_pool() -> Any:
    """Devuelve (creando si es necesario) el pool de conexiones Postgres."""
    global _pg_pool
    if _pg_pool is not None:
        return _pg_pool
    with _pg_pool_lock:
        if _pg_pool is not None:
            return _pg_pool
        try:
            from psycopg_pool import ConnectionPool
        except ImportError as exc:
            raise RuntimeError(
                "psycopg-pool no instalado. Ejecuta: pip install psycopg-pool>=3.2,<4"
            ) from exc

        pool_size = getattr(settings, "DB_POOL_SIZE", 5)
        url = _database_url()
        conn_kwargs = _pg_connect_kwargs(url)
        try:
            _pg_pool = ConnectionPool(
                conninfo=url,
                min_size=1,
                max_size=max(pool_size, 2),
                kwargs=conn_kwargs,
                open=True,
            )
        except Exception as exc:
            # No filtrar el DSN (con password) en el mensaje de error propagado.
            from observability.logging import redact_dsn

            raise RuntimeError(
                f"No se pudo crear el pool Postgres: {redact_dsn(str(exc))}"
            ) from None
        log.info(
            "pg_pool_created",
            min=1,
            max=max(pool_size, 2),
            timeouts=conn_kwargs.get("options", "none"),
            ssl_ca=bool(conn_kwargs.get("sslrootcert")),
        )
    return _pg_pool


def _close_pg_pool() -> None:
    """Cierra el pool Postgres si está abierto."""
    global _pg_pool
    with _pg_pool_lock:
        pool = _pg_pool
        _pg_pool = None
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


def _create_pg_connection() -> _PgConnAdapter:
    """Crea una nueva conexión Postgres via psycopg_pool."""
    pool = _get_pg_pool()
    raw_conn = pool.getconn()
    return _PgConnAdapter(raw_conn)


def _return_pg_connection(adapter: _PgConnAdapter) -> None:
    """Devuelve la conexión subyacente al pool Postgres."""
    pool = _pg_pool
    if pool is not None:
        try:
            pool.putconn(adapter._conn)
        except Exception:
            try:
                adapter._conn.close()
            except Exception:
                pass


def _get_conn() -> Any:
    """Devuelve una conexión del pool Postgres gestionado (psycopg_pool)."""
    if not _database_url():
        raise RuntimeError(
            "DATABASE_URL no está configurada. Postgres es el único motor "
            "soportado desde ADR-021: levantá el servicio con "
            "`docker compose up -d postgres` o apuntá DATABASE_URL a tu "
            "instancia."
        )
    return _create_pg_connection()


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

    Con backend Postgres (ADR-016): usa psycopg_pool; el shim qmark→%s se
    aplica automáticamente en cada execute().
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

    Marca la transacción en curso como ``READ ONLY``: cualquier
    INSERT/UPDATE/DELETE/DDL mal dirigido por esta vía lanza
    ``ReadOnlySqlTransaction`` en vez de ejecutarse y ser revertido en silencio
    por el ``putconn`` del pool. El guard anterior
    (``SET LOCAL default_transaction_read_only = on``) era inerte: solo afecta a
    transacciones que empiecen *después*, pero el primer ``execute`` ya había
    abierto la actual, así que una escritura pasaba sin error y se perdía sin
    rastro. ``SET TRANSACTION READ ONLY`` tiene que ser la primera sentencia de
    la transacción, y lo es: ``_get_conn`` entrega una conexión limpia del pool.
    """
    conn = _get_conn()
    try:
        conn.execute("SET TRANSACTION READ ONLY")
        yield conn
    finally:
        # Las lecturas no necesitan commit; cerramos la transacción con un
        # rollback explícito antes de devolver la conexión al pool. Si el
        # rollback falla, la conexión está en mal estado: lo registramos (no es
        # indistinguible de "sin datos") y dejamos que el pool la descarte.
        try:
            conn.rollback()
        except Exception:
            log.warning("connect_read_rollback_failed", exc_info=True)
        _return_conn(conn)
