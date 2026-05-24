"""Rutas /api/v1/health — sin autenticación.

Endpoints:
    GET /api/v1/health        — alias de /ready (mantiene compat)
    GET /api/v1/health/live   — liveness probe: proceso vivo
    GET /api/v1/health/ready  — readiness probe: DB + Redis + disco listos
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from services.health import check_db

router = APIRouter(prefix="/health", tags=["health"])

# Espacio libre mínimo en disco para considerar el servicio ready (bytes).
# 500 MB cubre WAL de SQLite + buffer de descargas de ZIPs.
_MIN_FREE_DISK_BYTES = 500 * 1024 * 1024


class HealthResponse(BaseModel):
    status: str
    db: str
    redis: str
    disk: str
    timestamp: str


def _check_db() -> str:
    return check_db()


def _check_redis() -> str:
    """Verifica conectividad con Redis si está configurado.

    Devuelve ``"ok"``, ``"degraded"`` (no responde) o ``"unconfigured"`` si
    no hay ``REDIS_URL`` en settings.
    """
    try:
        from config import settings

        redis_url: str = getattr(settings, "REDIS_URL", "") or ""
        if not redis_url:
            return "unconfigured"

        import redis as _redis

        client = _redis.from_url(redis_url, socket_connect_timeout=2)
        client.ping()
        return "ok"
    except Exception:
        return "degraded"


def _check_disk() -> str:
    """Verifica espacio libre en disco.

    Devuelve ``"ok"`` si hay al menos 500 MB libres, ``"low"`` en caso contrario.
    """
    try:
        from config import settings

        check_path = getattr(settings, "DATA_DIR", None) or "."
        usage = shutil.disk_usage(str(check_path))
        if usage.free >= _MIN_FREE_DISK_BYTES:
            return "ok"
        return f"low ({usage.free // (1024 * 1024)} MB free)"
    except Exception:
        return "unknown"


def _overall_status(db: str, redis: str, disk: str) -> str:
    """ok si DB está bien; degraded si Redis falla o disco bajo pero DB ok."""
    if db != "ok":
        return "degraded"
    if redis == "degraded" or disk.startswith("low"):
        return "degraded"
    return "ok"


@router.get("", response_model=HealthResponse, summary="Health check (alias de /ready)")
async def health() -> HealthResponse:
    """Estado del servicio y conectividad con la base de datos.

    No requiere autenticación — usado por load balancers y monitorización.
    Mantiene compatibilidad con clientes que usaban ``/health`` directamente.
    """
    db_status = _check_db()
    redis_status = _check_redis()
    disk_status = _check_disk()
    return HealthResponse(
        status=_overall_status(db_status, redis_status, disk_status),
        db=db_status,
        redis=redis_status,
        disk=disk_status,
        timestamp=datetime.now(UTC).isoformat(),
    )


@router.get("/live", summary="Liveness probe — proceso vivo")
async def liveness() -> dict:
    """Kubernetes liveness probe. Siempre devuelve 200 si el proceso responde."""
    return {"status": "alive", "timestamp": datetime.now(UTC).isoformat()}


@router.get(
    "/ready", response_model=HealthResponse, summary="Readiness probe — dependencias listas"
)
async def readiness() -> JSONResponse:
    """Kubernetes readiness probe. Verifica DB, Redis y disco; devuelve 503 si degradado."""
    db_status = _check_db()
    redis_status = _check_redis()
    disk_status = _check_disk()
    overall = _overall_status(db_status, redis_status, disk_status)
    http_status = 200 if overall == "ok" else 503
    body = HealthResponse(
        status=overall,
        db=db_status,
        redis=redis_status,
        disk=disk_status,
        timestamp=datetime.now(UTC).isoformat(),
    )
    return JSONResponse(content=body.model_dump(), status_code=http_status)
