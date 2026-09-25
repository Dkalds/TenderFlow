"""Rutas /api/v1/health — sin autenticación.

Endpoints:
    GET /api/v1/health        — alias de /ready (mantiene compat)
    GET /api/v1/health/live   — liveness probe: proceso vivo
    GET /api/v1/health/ready  — readiness probe: DB + Redis + disco + schema
"""

from __future__ import annotations

import os
import shutil
import time
from datetime import UTC, datetime
from typing import Any

import anyio
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.concurrency import run_probe
from db.schema_revision import database_url as _database_url
from db.schema_revision import diagnosticar
from db.schema_revision import revisiones_aplicadas as _applied_revisions
from db.schema_revision import revisiones_repo as _repo_revisions
from observability.logging import get_logger
from services.health import check_db
from shared.outbound_http import pinned_https_request

log = get_logger(__name__)

router = APIRouter(prefix="/health", tags=["health"])

# Espacio libre mínimo en disco para considerar el servicio ready (bytes).
# 500 MB cubre el buffer de descargas de ZIPs del scraper.
# Configurable vía HEALTH_MIN_FREE_DISK_BYTES para entornos con discos pequeños.
_DEFAULT_MIN_FREE = 500 * 1024 * 1024  # 500 MB

# Techo por sondeo. Sin él, un `check_db` contra una BD colgada tarda lo que
# tarde `connect_timeout` (10 s) o el `statement_timeout` (30 s) del pool: más
# de lo que cualquier probe espera, así que la plataforma da el proceso por
# muerto y lo reinicia en vez de leer el "degraded" que este endpoint existe
# para publicar.
_DEFAULT_CHECK_TIMEOUT = 5.0

# ── Alineación código ↔ schema (S6.2) ────────────────────────────────────────
# Nada relacionaba el código desplegado con el schema aplicado: `migrate.yml` es
# `workflow_dispatch` a propósito y el arranque de la API solo hace ping a la
# BD. Resultado: `deploy.yml` puede desplegar código que exige la revisión N+1
# sobre una BD en N y todos los gates salen verdes — que es exactamente el
# incidente que motivó `migrate.yml` (`column "lote_id" of relation
# "adjudicaciones" does not exist`).
#
# Este sondeo compara `alembic_version` (BD) con las cabezas del repo. NO es un
# gate de arranque: publica `degraded` con un detalle legible y deja que el
# operador (o `smoke_prod.py` / `deploy.yml`) decida. Un fallo suyo nunca puede
# tumbar el proceso ni degradar el estado — devuelve `unknown` y sigue.
#
# La comparación vive en `db/schema_revision.py` desde 2026-09: la comparte con
# el preflight de los workflows de datos (`python -m db.schema_revision`), de
# modo que el endpoint y los jobs no pueden discrepar sobre qué es un desfase.
# Aquí queda lo que es solo del endpoint: la caché, el techo de tiempo y el
# efecto sobre `status`. Los alias con los nombres de siempre (`_database_url`,
# `_repo_revisions`, `_applied_revisions`) se conservan como las fuentes que
# `_check_schema` le pasa a `diagnosticar`.

# El resultado se cachea: `alembic_version` solo cambia cuando corre una
# migración, y las cabezas del repo no cambian en la vida del proceso. Sin TTL
# este sondeo abriría una conexión por cada probe de la plataforma (cada 30 s
# con el HEALTHCHECK del Dockerfile) fuera de los dos pools de psycopg, cuyo
# presupuesto está contado al detalle en render.yaml. Con 300 s el coste es de
# como mucho una conexión cada cinco minutos, y una migración recién aplicada se
# refleja en ese mismo plazo sin reiniciar nada.
_DEFAULT_SCHEMA_TTL = 300.0
_schema_cache: tuple[float, str] | None = None


def _min_free_disk_bytes() -> int:
    """Devuelve el umbral de espacio libre configurado o el default."""
    raw = os.environ.get("HEALTH_MIN_FREE_DISK_BYTES")
    if raw is not None:
        try:
            val = int(raw)
            if val > 0:
                return val
        except ValueError:
            pass
    return _DEFAULT_MIN_FREE


def _check_timeout_seconds() -> float:
    """Techo por sondeo, configurable con ``HEALTH_CHECK_TIMEOUT_SECONDS``."""
    raw = os.environ.get("HEALTH_CHECK_TIMEOUT_SECONDS")
    if raw is not None:
        try:
            val = float(raw)
            if val > 0:
                return val
        except ValueError:
            pass
    return _DEFAULT_CHECK_TIMEOUT


def _schema_ttl_seconds() -> float:
    """TTL del sondeo de schema, configurable con ``HEALTH_SCHEMA_TTL_SECONDS``.

    ``0`` desactiva la caché (útil en tests y en un incidente, donde se quiere
    ver el efecto de una migración al instante).
    """
    raw = os.environ.get("HEALTH_SCHEMA_TTL_SECONDS")
    if raw is not None:
        try:
            val = float(raw)
            if val >= 0:
                return val
        except ValueError:
            pass
    return _DEFAULT_SCHEMA_TTL


class HealthResponse(BaseModel):
    status: str
    db: str
    redis: str
    disk: str
    # Alineación entre la revisión alembic aplicada en la BD y las cabezas del
    # repo: ``ok (v98)`` · ``behind (v97 < v98)`` · ``ahead (v99 > v98)`` ·
    # ``unknown`` (no se pudo determinar) · ``unconfigured`` (sin DATABASE_URL).
    schema_revision: str = "unknown"
    timestamp: str


def _check_db() -> str:
    return check_db()


def _check_schema() -> str:
    """Compara la revisión aplicada con las cabezas del repo. Nunca propaga.

    Devuelve ``unconfigured`` sin ``DATABASE_URL`` (desarrollo y tests, donde no
    hay nada que comparar) y ``unknown`` ante cualquier fallo: un sondeo que no
    puede leer el estado no es lo mismo que un schema desalineado, y sólo el
    segundo tiene que teñir el endpoint de ``degraded``.
    """
    global _schema_cache

    ttl = _schema_ttl_seconds()
    ahora = time.monotonic()
    cache = _schema_cache
    if cache is not None and ttl > 0 and (ahora - cache[0]) < ttl:
        return cache[1]

    # Se pasan los alias de este módulo, resueltos en cada llamada, y no las
    # fuentes por defecto de `db.schema_revision`: así sustituirlos aquí (lo
    # hace `tests/test_s6_health_schema.py`) tiene efecto.
    diagnostico = diagnosticar(
        url=_database_url, repo=_repo_revisions, aplicadas=_applied_revisions
    )
    if diagnostico.error is not None:
        log.warning("health_schema_check_failed", error=diagnostico.error)
    resultado = diagnostico.estado

    _schema_cache = (ahora, resultado)
    return resultado


async def _gather_checks() -> tuple[str, str, str, str]:
    """Ejecuta los cuatro sondeos en el threadpool, con techo de tiempo.

    Los cuatro son síncronos y bloqueantes (BD, socket a Redis, ``statvfs``), así
    que van a ``run_probe`` — y no a ``run_db``: solo ``run_probe`` abandona el
    hilo al cancelarse, que es lo único que hace efectivo el ``fail_after``. Con
    ``run_db`` el timeout salta pero la espera continúa hasta que el sondeo
    termina, así que el endpoint seguiría colgado (ver su docstring).
    El hilo huérfano muere por su cuenta cuando salta su propio timeout de
    conexión; lo que importa es que la respuesta HTTP salga a tiempo con
    ``degraded`` en vez de colgarse con el probe.
    """
    timeout = _check_timeout_seconds()

    async def _guarded(name: str, fn: Any, on_timeout: str) -> str:
        try:
            with anyio.fail_after(timeout):
                result: str = await run_probe(fn)
                return result
        except TimeoutError:
            log.warning("health_check_timeout", check=name, timeout_seconds=timeout)
            return on_timeout
        except Exception as exc:
            log.warning("health_check_failed", check=name, error=str(exc))
            return on_timeout

    results: dict[str, str] = {}

    async def _run(name: str, fn: Any, on_timeout: str) -> None:
        results[name] = await _guarded(name, fn, on_timeout)

    async with anyio.create_task_group() as tg:
        tg.start_soon(_run, "db", _check_db, "error")
        tg.start_soon(_run, "redis", _check_redis, "degraded")
        tg.start_soon(_run, "disk", _check_disk, "unknown")
        # El sondeo de schema entra en el mismo grupo, con el mismo techo y el
        # mismo `run_probe` abandonable: si la BD está colgada, este también
        # tiene que soltar el hilo en vez de retener la respuesta HTTP. Su
        # `on_timeout` es "unknown" y no un estado de desalineación — un sondeo
        # que no llegó a leer nada no puede afirmar que el schema esté mal.
        tg.start_soon(_run, "schema", _check_schema, "unknown")

    return results["db"], results["redis"], results["disk"], results["schema"]


def _check_redis() -> str:
    """Verifica conectividad con Redis si está configurado.

    Devuelve ``"ok"``, ``"degraded"`` (no responde) o ``"unconfigured"`` si
    no hay ``REDIS_URL`` en settings.

    Para bases de datos Upstash (host contiene ``.upstash.io``) usa la REST
    API sobre HTTPS (puerto 443) en vez del protocolo TCP nativo (puerto 6380),
    que suele estar bloqueado en redes corporativas y domésticas.
    """
    try:
        from config import settings

        redis_url: str = getattr(settings, "REDIS_URL", "") or ""
        if not redis_url:
            return "unconfigured"

        import urllib.parse

        parsed = urllib.parse.urlparse(redis_url)
        host = parsed.hostname or ""

        if host.endswith(".upstash.io"):
            # Upstash REST API — funciona por HTTPS (puerto 443, siempre abierto).
            # Prioridad: variable REDIS_REST_TOKEN; si no, la contraseña de la URL.
            token = getattr(settings, "REDIS_REST_TOKEN", "") or parsed.password or ""
            rest_url = f"https://{host}/PING"
            with pinned_https_request(
                "GET",
                rest_url,
                headers={"Authorization": f"Bearer {token}"},
                timeout_seconds=5,
                allowed_hosts=frozenset({host}),
            ) as response:
                response.raise_for_status()
                body = b"".join(response.iter_content()).decode()
                # La REST API devuelve {"result":"PONG"}
                if "PONG" in body:
                    return "ok"
            return "degraded"

        # Redis estándar — protocolo TCP nativo
        import redis as _redis

        from_url: Any = _redis.from_url
        client = from_url(redis_url, socket_connect_timeout=2)
        client.ping()
        return "ok"
    except Exception:
        return "degraded"


def _check_disk() -> str:
    """Verifica espacio libre en disco.

    Devuelve ``"ok"`` si hay al menos el umbral configurado libre, ``"low"`` en caso contrario.
    """
    try:
        from config import settings

        check_path = getattr(settings, "DATA_DIR", None) or "."
        usage = shutil.disk_usage(str(check_path))
        min_free = _min_free_disk_bytes()
        if usage.free >= min_free:
            return "ok"
        return f"low ({usage.free // (1024 * 1024)} MB free, min {min_free // (1024 * 1024)} MB)"
    except Exception:
        return "unknown"


def _overall_status(db: str, redis: str, disk: str, schema: str = "unknown") -> str:
    """ok si DB está bien y Redis/disco/schema ok; degraded en caso contrario.

    ``schema`` degrada solo cuando afirma un desalineamiento (``behind``/
    ``ahead``). ``unknown`` y ``unconfigured`` no degradan: el sondeo puede no
    haber podido leer la revisión (BD lenta, alembic ausente) y eso no es una
    afirmación sobre el schema. El default del parámetro mantiene compatible a
    quien llame con tres argumentos.
    """
    if db != "ok":
        return "degraded"
    if redis == "degraded" or disk.startswith("low"):
        return "degraded"
    if schema.startswith(("behind", "ahead")):
        return "degraded"
    return "ok"


def _http_status_for_readiness(db: str) -> int:
    """503 solo si la BD no está disponible. Redis/disco degradado → 200 con payload degraded."""
    return 503 if db != "ok" else 200


@router.get("", response_model=HealthResponse, summary="Health check (alias de /ready)")
async def health() -> HealthResponse:
    """Estado del servicio y conectividad con la base de datos.

    No requiere autenticación — usado por load balancers y monitorización.
    Mantiene compatibilidad con clientes que usaban ``/health`` directamente.
    """
    db_status, redis_status, disk_status, schema_status = await _gather_checks()
    return HealthResponse(
        status=_overall_status(db_status, redis_status, disk_status, schema_status),
        db=db_status,
        redis=redis_status,
        disk=disk_status,
        schema_revision=schema_status,
        timestamp=datetime.now(UTC).isoformat(),
    )


class Liveness(BaseModel):
    status: str
    timestamp: str


@router.get("/live", summary="Liveness probe — proceso vivo")
async def liveness() -> Liveness:
    """Kubernetes liveness probe. Siempre devuelve 200 si el proceso responde."""
    return Liveness(status="alive", timestamp=datetime.now(UTC).isoformat())


@router.get(
    "/ready", response_model=HealthResponse, summary="Readiness probe — dependencias listas"
)
async def readiness() -> JSONResponse:
    """Kubernetes readiness probe.

    - ``503`` solo si la base de datos no responde (el proceso no puede servir tráfico).
    - ``200`` con ``status:"degraded"`` si Redis, disco o el schema están
      desalineados pero la BD funciona (el proceso puede servir tráfico, con
      funcionalidad reducida).

    Un schema desalineado NO devuelve 503 a propósito: el proceso sirve, y un
    503 haría que Render retirase la instancia y dejase la superficie pública
    caída por un problema que se arregla corriendo una migración. Quien tiene
    que fallar ante ``degraded`` es el pipeline (``deploy.yml``, ``smoke.yml``
    vía ``scripts/smoke_prod.py``), no el balanceador.
    """
    db_status, redis_status, disk_status, schema_status = await _gather_checks()
    overall = _overall_status(db_status, redis_status, disk_status, schema_status)
    http_status = _http_status_for_readiness(db_status)
    body = HealthResponse(
        status=overall,
        db=db_status,
        redis=redis_status,
        disk=disk_status,
        schema_revision=schema_status,
        timestamp=datetime.now(UTC).isoformat(),
    )
    return JSONResponse(content=body.model_dump(), status_code=http_status)
