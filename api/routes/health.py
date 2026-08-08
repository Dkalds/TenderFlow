"""Rutas /api/v1/health — sin autenticación.

Endpoints:
    GET /api/v1/health        — alias de /ready (mantiene compat)
    GET /api/v1/health/live   — liveness probe: proceso vivo
    GET /api/v1/health/ready  — readiness probe: DB + Redis + disco listos
"""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime
from typing import Any

import anyio
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.concurrency import run_db
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


class HealthResponse(BaseModel):
    status: str
    db: str
    redis: str
    disk: str
    timestamp: str


def _check_db() -> str:
    return check_db()


async def _gather_checks() -> tuple[str, str, str]:
    """Ejecuta los tres sondeos en el threadpool, con techo de tiempo.

    Los tres son síncronos y bloqueantes (BD, socket a Redis, ``statvfs``), así
    que van a ``run_db``; el ``fail_after`` acota lo que puede tardar el
    endpoint aunque la dependencia no responda nunca. El hilo que quedó
    esperando termina por su cuenta cuando su propio timeout salta: lo que
    importa es que la respuesta HTTP salga a tiempo con ``degraded`` en vez de
    colgarse con el probe.
    """
    timeout = _check_timeout_seconds()

    async def _guarded(name: str, fn: Any, on_timeout: str) -> str:
        try:
            with anyio.fail_after(timeout):
                result: str = await run_db(fn)
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

    return results["db"], results["redis"], results["disk"]


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


def _overall_status(db: str, redis: str, disk: str) -> str:
    """ok si DB está bien y Redis/disco ok; degraded si Redis/disco fallan pero DB ok."""
    if db != "ok":
        return "degraded"
    if redis == "degraded" or disk.startswith("low"):
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
    db_status, redis_status, disk_status = await _gather_checks()
    return HealthResponse(
        status=_overall_status(db_status, redis_status, disk_status),
        db=db_status,
        redis=redis_status,
        disk=disk_status,
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
    - ``200`` con ``status:"degraded"`` si Redis o disco están degradados pero la BD funciona
      (el proceso puede servir tráfico, con funcionalidad reducida).
    """
    db_status, redis_status, disk_status = await _gather_checks()
    overall = _overall_status(db_status, redis_status, disk_status)
    http_status = _http_status_for_readiness(db_status)
    body = HealthResponse(
        status=overall,
        db=db_status,
        redis=redis_status,
        disk=disk_status,
        timestamp=datetime.now(UTC).isoformat(),
    )
    return JSONResponse(content=body.model_dump(), status_code=http_status)
