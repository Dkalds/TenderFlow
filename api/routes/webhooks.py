"""Rutas /api/v1/webhooks — gestión de suscripciones a eventos.

Endpoints:
    POST   /api/v1/webhooks              — crear (devuelve secret una sola vez)
    GET    /api/v1/webhooks              — listar (sin secret)
    GET    /api/v1/webhooks/{id}         — detalle
    PATCH  /api/v1/webhooks/{id}         — actualizar campos opcionales
    DELETE /api/v1/webhooks/{id}         — eliminar
    POST   /api/v1/webhooks/{id}/ping    — enviar entrega de prueba
    GET    /api/v1/webhooks/{id}/deliveries — historial de entregas

Los webhooks son un recurso compartido a nivel de instancia (sin owner por
usuario — cualquier integración registrada los ve todos), así que todos los
endpoints requieren autenticación dual (sesión OAuth o API key,
``require_any_auth``) **y** ``is_admin`` (F13·C3.1, plan Pliegos+RAG — antes
requerían ``X-API-Key`` con scope ``webhooks:read``/``webhooks:write``; una
key con scope ``*`` sigue teniendo acceso, ya que ``require_any_auth`` la
marca ``is_admin`` en ese caso).
"""

from __future__ import annotations

import urllib.parse
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from db.audit import log_event
from db.repositories.webhooks import WebhookRepository
from observability.logging import get_logger
from shared.ssrf import is_ssrf_url as _is_ssrf_url
from shared.ssrf import resolve_and_validate as _resolve_and_validate

log = get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

_VALID_EVENTS = {"watchlist_match", "daily_summary", "watchlist_rule.matched", "*"}


def _require_admin(user: dict[str, Any] = Depends(require_any_auth)) -> dict[str, Any]:
    """Verifica que el usuario autenticado sea admin (recurso compartido)."""
    if not user.get("is_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required.")
    return user


def _actor_key(ctx: dict[str, Any]) -> str:
    """Identificador corto para audit log — misma convención que feedback.py/me.py."""
    return str(ctx.get("key_hash") or ctx.get("email") or "session")[:8]


# ── Modelos ──────────────────────────────────────────────────────────────────


class WebhookCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, examples=["mi-integracion-slack"])
    url: str = Field(..., examples=["https://hooks.example.com/licitaciones"])
    event_types: list[str] = Field(
        default_factory=lambda: ["*"],
        examples=[["watchlist_match"]],
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith("https://") and not v.startswith("http://"):
            raise ValueError("URL debe ser http(s)://...")
        if len(v) > 500:
            raise ValueError("URL demasiado larga (máx 500 chars)")
        if _is_ssrf_url(v):
            raise ValueError("URL no permitida: apunta a una red privada o no es accesible.")
        return v

    @field_validator("event_types")
    @classmethod
    def validate_events(cls, v: list[str]) -> list[str]:
        invalid = [e for e in v if e not in _VALID_EVENTS]
        if invalid:
            raise ValueError(f"Eventos inválidos: {invalid}. Permitidos: {sorted(_VALID_EVENTS)}")
        return v


class WebhookUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    url: str | None = None
    event_types: list[str] | None = None
    active: bool | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not v.startswith("https://") and not v.startswith("http://"):
            raise ValueError("URL debe ser http(s)://...")
        if len(v) > 500:
            raise ValueError("URL demasiado larga")
        if _is_ssrf_url(v):
            raise ValueError("URL no permitida: apunta a una red privada.")
        return v

    @field_validator("event_types")
    @classmethod
    def validate_events(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        invalid = [e for e in v if e not in _VALID_EVENTS]
        if invalid:
            raise ValueError(f"Eventos inválidos: {invalid}. Permitidos: {sorted(_VALID_EVENTS)}")
        return v


class WebhookCreateResponse(BaseModel):
    id: int
    name: str
    url: str
    event_types: list[str]
    secret: str = Field(
        ...,
        description="Secret para verificar firma HMAC (X-Webhook-Signature). "
        "Solo se devuelve en la creación; guárdalo de forma segura.",
    )


# ── Endpoints ────────────────────────────────────────────────────────────────

_repo = WebhookRepository()


@router.post(
    "",
    response_model=WebhookCreateResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "URL inválida o SSRF detectado"},
        401: {"description": "API key inválida"},
        403: {"description": "Scope insuficiente"},
    },
)
async def create(
    body: WebhookCreate,
    ctx: dict[str, Any] = Depends(_require_admin),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> WebhookCreateResponse:
    """Crea un webhook. Devuelve el ``secret`` solo en esta respuesta.

    Si se incluye ``Idempotency-Key``, una segunda request con la misma
    clave devuelve la respuesta original sin crear un duplicado.
    """
    # -- Idempotency check --
    if idempotency_key:
        cached = await run_db(_repo.idempotency_get, idempotency_key, "webhook.create")
        if cached is not None:
            log.info("webhook_create_idempotent_hit", key=idempotency_key[:16])
            return WebhookCreateResponse(**cached)

    webhook_id, secret = await run_db(
        _repo.create, name=body.name, url=body.url, event_types=body.event_types
    )
    log_event(
        event_type="webhook.created",
        user_key=_actor_key(ctx),
        resource=f"webhook:{webhook_id}",
        detail={"name": body.name, "events": body.event_types},
    )
    response_data = WebhookCreateResponse(
        id=webhook_id,
        name=body.name,
        url=body.url,
        event_types=body.event_types,
        secret=secret,
    )

    # -- Persist idempotency key --
    if idempotency_key:
        await run_db(
            _repo.idempotency_store,
            idempotency_key,
            "webhook.create",
            response_data.model_dump(),
        )

    return response_data


@router.get(
    "",
    summary="Listar webhooks (sin secret)",
    responses={401: {"description": "API key inválida"}},
)
async def list_all(
    _ctx: dict[str, Any] = Depends(_require_admin),
) -> list[dict[str, Any]]:
    return _repo.list_all()


@router.get(
    "/{webhook_id}",
    summary="Detalle de un webhook",
    responses={401: {"description": "API key inválida"}, 404: {"description": "No encontrado"}},
)
async def get_one(
    webhook_id: int,
    _ctx: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    wh = _repo.get_by_id(webhook_id)
    if wh is None:
        raise HTTPException(status_code=404, detail="Webhook no encontrado.")
    return wh


@router.patch(
    "/{webhook_id}",
    summary="Actualizar campos de un webhook",
    responses={
        401: {"description": "API key inválida"},
        403: {"description": "Scope insuficiente"},
        404: {"description": "No encontrado"},
    },
)
async def update(
    webhook_id: int,
    body: WebhookUpdate,
    ctx: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    """Actualiza nombre, URL, event_types o active de un webhook existente."""
    found = _repo.update(
        webhook_id,
        name=body.name,
        url=body.url,
        event_types=body.event_types,
        active=body.active,
    )
    if not found:
        raise HTTPException(status_code=404, detail="Webhook no encontrado.")
    log_event(
        event_type="webhook.updated",
        user_key=_actor_key(ctx),
        resource=f"webhook:{webhook_id}",
    )
    wh = _repo.get_by_id(webhook_id)
    return wh or {}


@router.delete(
    "/{webhook_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        401: {"description": "API key inválida"},
        403: {"description": "Scope insuficiente"},
        404: {"description": "No encontrado"},
    },
)
async def delete(
    webhook_id: int,
    ctx: dict[str, Any] = Depends(_require_admin),
) -> None:
    if not _repo.delete(webhook_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe")
    log_event(
        event_type="webhook.deleted",
        user_key=_actor_key(ctx),
        resource=f"webhook:{webhook_id}",
    )


@router.post(
    "/{webhook_id}/ping",
    summary="Enviar una entrega de prueba",
    status_code=200,
    responses={
        401: {"description": "API key inválida"},
        403: {"description": "Scope insuficiente"},
        404: {"description": "No encontrado"},
    },
)
async def ping(
    webhook_id: int,
    _ctx: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    """Envía un payload de prueba al URL del webhook para verificar conectividad."""
    import asyncio as _asyncio
    import hashlib
    import hmac as _hmac
    import json

    import requests

    wh = _repo.get_by_id(webhook_id)
    if wh is None:
        raise HTTPException(status_code=404, detail="Webhook no encontrado.")

    secret = _repo.get_secret(webhook_id)
    if not secret:
        raise HTTPException(status_code=500, detail="Secret no disponible.")

    from db.database import now_utc_iso

    payload = json.dumps(
        {"event": "ping", "data": {"message": "Test delivery"}, "timestamp": now_utc_iso()},
        ensure_ascii=False,
    ).encode()
    sig = _hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    # DNS pinning: resolve NOW, validate, pin IP to prevent rebinding
    url = str(wh["url"])
    original_host = urllib.parse.urlparse(url).hostname or ""
    try:
        pinned_url = _resolve_and_validate(url)
    except ValueError as exc:
        log.warning("webhook_ping_ssrf_blocked", webhook_id=webhook_id, error=str(exc))
        return {"success": False, "error": f"SSRF blocked: {exc}"}

    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Signature": f"sha256={sig}",
        "X-Webhook-Event": "ping",
        "User-Agent": "licitaciones-sap-webhook/1.0",
        "Host": original_host,  # preserve original Host for TLS SNI / vhosts
    }

    # Retry with exponential backoff (max 2 retries)
    max_attempts = 3
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            resp = await _asyncio.to_thread(
                requests.post,
                pinned_url,
                data=payload,
                headers=headers,
                timeout=5.0,
                verify=True,
            )
            ok = 200 <= resp.status_code < 300
            _repo.record_delivery(
                webhook_id,
                status_code=resp.status_code,
                success=ok,
                event_type="ping",
                payload_size=len(payload),
            )
            return {"success": ok, "status_code": resp.status_code, "attempts": attempt + 1}
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < max_attempts - 1:
                await _asyncio.sleep(0.5 * (2**attempt))  # 0.5s, 1s

    _repo.record_delivery(
        webhook_id,
        status_code=0,
        success=False,
        event_type="ping",
        payload_size=len(payload),
    )
    return {"success": False, "error": str(last_exc), "attempts": max_attempts}


@router.get(
    "/{webhook_id}/deliveries",
    summary="Historial de entregas",
    responses={
        401: {"description": "API key inválida"},
        404: {"description": "No encontrado"},
    },
)
async def deliveries(
    webhook_id: int,
    limit: int = Query(50, ge=1, le=200),
    _ctx: dict[str, Any] = Depends(_require_admin),
) -> list[dict[str, Any]]:
    """Devuelve las últimas entregas realizadas para este webhook."""
    if _repo.get_by_id(webhook_id) is None:
        raise HTTPException(status_code=404, detail="Webhook no encontrado.")
    return _repo.list_deliveries(webhook_id, limit=limit)
