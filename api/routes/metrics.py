"""Endpoint Prometheus ``GET /metrics``.

Vivía dentro de ``api/app.py``, donde además de estar fuera de sitio hacía algo
peor: **revalidaba la API key por su cuenta**. Hash, lookup, expiración, scopes
y propietario activo, todo reescrito a mano junto al handler. Un comentario del
propio fichero admitía cómo salió mal la última vez —«la comprobación de
propietario hay que repetirla aquí: sin ella, la key de un usuario dado de baja
seguía leyendo las métricas»—, que es exactamente lo que pasa cuando la misma
regla se escribe en dos sitios.

Aquí no se valida nada a mano: la credencial la valida
:func:`api.auth.validate_api_key_credential` (el mismo núcleo que
``require_api_key``: comparación en tiempo constante, expiración, propietario
activo, 503 ante error de BD) y el scope lo comprueba
:func:`api.auth.require_scope`, invocado con el contexto ya validado.

Lo único propio de este endpoint es **de dónde sale la credencial**:

* ``X-API-Key``, como el resto de la API.
* ``Authorization: Bearer`` — Prometheus (``prom/prometheus:v2.53``) no puede
  enviar cabeceras custom, solo el header estándar de su bloque
  ``authorization``. Sin esta rama el scrape de Render recibía 401 en cada
  pasada y los SLOs de ADR-019 se quedaban sin medición.
* En ``ENV=dev``, la IP allowlist (``METRICS_ALLOWED_IPS``) basta y no hace
  falta credencial. En prod/staging **no**: la allowlist es condición
  adicional, nunca suficiente — detrás de un gateway Docker la IP del cliente
  es la de la red interna, no ``127.0.0.1``.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Security, status
from fastapi.responses import Response
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from api.auth import AuthContext, require_scope, validate_api_key_credential
from api.middleware import _trusted_client_ip
from config import settings
from observability.logging import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["observability"])

#: Scope que autoriza la lectura de métricas.
SCOPE_METRICAS = "metrics:read"

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
_BEARER = HTTPBearer(auto_error=False, scheme_name="PrometheusBearer")

#: ``require_scope`` devuelve una dependencia de FastAPI, pero por dentro es una
#: función normal que acepta el ``AuthContext``: se invoca con el contexto ya
#: validado en vez de recomprobar el scope a mano.
_exigir_scope_metricas = require_scope(SCOPE_METRICAS)

_NO_AUTORIZADO = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Unauthorized",
    headers={"WWW-Authenticate": "ApiKey"},
)


def _ip_permitida(request: Request) -> bool:
    """¿La IP de origen está en ``METRICS_ALLOWED_IPS``?"""
    permitidas = {ip.strip() for ip in settings.METRICS_ALLOWED_IPS.split(",") if ip.strip()}
    return _trusted_client_ip(request) in permitidas


async def require_metrics_reader(
    request: Request,
    api_key_raw: str | None = Security(_API_KEY_HEADER),
    bearer: HTTPAuthorizationCredentials | None = Security(_BEARER),
    background_tasks: BackgroundTasks = BackgroundTasks(),
) -> AuthContext | None:
    """Autoriza el scrape. Devuelve el contexto, o ``None`` si entró por IP.

    Devuelve ``None`` —y no un contexto fabricado— cuando el acceso se concede
    por la allowlist de dev: no hay credencial, así que no hay identidad que
    representar y no conviene inventarse una.
    """
    credencial = api_key_raw or (bearer.credentials if bearer is not None else None)
    if credencial:
        ctx = await validate_api_key_credential(credencial, background_tasks=background_tasks)
        return await _exigir_scope_metricas(ctx=ctx)

    if settings.ENV not in ("prod", "staging") and _ip_permitida(request):
        return None
    raise _NO_AUTORIZADO


@router.get(
    "/metrics",
    # Fuera del contrato público: no lo consume el cliente TS, lo consume
    # Prometheus, y su formato es texto de exposición, no JSON.
    include_in_schema=False,
    response_class=Response,
)
async def prometheus_metrics(
    _ctx: AuthContext | None = Depends(require_metrics_reader),
) -> Response:
    """Métricas en formato de exposición Prometheus."""
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    # Muestrear el estado de los pools de BD justo antes de serializar:
    # psycopg_pool ya lleva la contabilidad, así que el scrape la lee en vez de
    # instrumentar cada adquisición de conexión.
    from observability.runtime_metrics import refresh_db_pool_metrics

    refresh_db_pool_metrics()
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


__all__ = ["SCOPE_METRICAS", "require_metrics_reader", "router"]
