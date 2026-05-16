"""Rutas /api/v1/health — sin autenticación.

Endpoints:
    GET /api/v1/health        — alias de /ready (mantiene compat)
    GET /api/v1/health/live   — liveness probe: proceso vivo
    GET /api/v1/health/ready  — readiness probe: DB + dependencias listas
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from db.database import connect

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    status: str
    db: str
    timestamp: str


def _check_db() -> str:
    try:
        with connect() as c:
            c.execute("SELECT 1").fetchone()
        return "ok"
    except Exception:
        return "error"


@router.get("", response_model=HealthResponse, summary="Health check (alias de /ready)")
async def health() -> HealthResponse:
    """Estado del servicio y conectividad con la base de datos.

    No requiere autenticación — usado por load balancers y monitorización.
    Mantiene compatibilidad con clientes que usaban ``/health`` directamente.
    """
    db_status = _check_db()
    return HealthResponse(
        status="ok" if db_status == "ok" else "degraded",
        db=db_status,
        timestamp=datetime.now(UTC).isoformat(),
    )


@router.get("/live", summary="Liveness probe — proceso vivo")
async def liveness() -> dict:
    """Kubernetes liveness probe. Siempre devuelve 200 si el proceso responde."""
    return {"status": "alive", "timestamp": datetime.now(UTC).isoformat()}


@router.get("/ready", response_model=HealthResponse, summary="Readiness probe — dependencias listas")
async def readiness() -> JSONResponse:
    """Kubernetes readiness probe. Verifica DB y devuelve 503 si degradado."""
    db_status = _check_db()
    status_str = "ok" if db_status == "ok" else "degraded"
    http_status = 200 if db_status == "ok" else 503
    body = HealthResponse(
        status=status_str,
        db=db_status,
        timestamp=datetime.now(UTC).isoformat(),
    )
    return JSONResponse(content=body.model_dump(), status_code=http_status)
