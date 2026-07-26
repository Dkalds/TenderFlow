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

import hashlib
import hmac
import json
import re
import secrets
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, field_validator
from requests import RequestException

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from config.settings import settings
from db.audit import log_event
from db.repositories.webhooks import WebhookRepository
from observability.logging import get_logger
from shared.outbound_http import pinned_https_request
from shared.ssrf import validate_outbound_url

log = get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

_VALID_EVENTS = {"watchlist_match", "daily_summary", "watchlist_rule.matched", "*"}
_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _allowed_webhook_hosts() -> frozenset[str]:
    return frozenset(host.strip() for host in settings.WEBHOOK_ALLOWED_HOSTS.split(",") if host.strip())


def _validate_webhook_url(url: str) -> str:
    allowed_hosts = _allowed_webhook_hosts()
    if settings.ENV in ("prod", "staging") and not allowed_hosts:
        raise ValueError("Los webhooks salientes están deshabilitados: falta WEBHOOK_ALLOWED_HOSTS")
    validate_outbound_url(url, allowed_hosts=allowed_hosts or None)
    return url


def _require_admin(user: dict[str, Any] = Depends(require_any_auth)) -> dict[str, Any]:
    """Verifica que el usuario autenticado sea admin (recurso compartido)."""
    if not user.get("is_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required.")
    return user


def _actor_key(ctx: dict[str, Any]) -> str:
    """Identificador corto para audit log — misma convención que feedback.py/me.py."""
    material = str(ctx.get("user_key") or ctx.get("key_hash") or ctx.get("user_id") or "session")
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def _idempotency_endpoint(ctx: dict[str, Any]) -> str:
    """Namespace an idempotency key by its authenticated owner."""
    return f"webhook.create:{_actor_key(ctx)}"


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
        if not v.startswith("https://"):
            raise ValueError("URL debe usar https://")
        if len(v) > 500:
            raise ValueError("URL demasiado larga (máx 500 chars)")
        return _validate_webhook_url(v)

    @field_validator("event_types")
    @classmethod
    def validate_events(cls, v: list[str]) -> list[str]:
        invalid = [e for e in v if e not in _VALID_EVENTS]
        if invalid:
            raise ValueError(f"Eventos inválidos: {invalid}. Permitidos: {sorted(_VALID_EVENTS)}")
        return v


def _request_fingerprint(body: WebhookCreate) -> str:
    payload = json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _post_pinned_webhook(url: str, payload: bytes, headers: dict[str, str]) -> int:
    """Send one webhook delivery with DNS pinning, TLS verification and no redirects."""
    allowed_hosts = _allowed_webhook_hosts()
    with pinned_https_request(
        "POST",
        url,
        body=payload,
        headers=headers,
        timeout_seconds=5.0,
        allowed_hosts=allowed_hosts or None,
    ) as response:
        return response.status_code


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
        if not v.startswith("https://"):
            raise ValueError("URL debe usar https://")
        if len(v) > 500:
            raise ValueError("URL demasiado larga")
        return _validate_webhook_url(v)

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
    response: Response,
    ctx: dict[str, Any] = Depends(_require_admin),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> WebhookCreateResponse:
    """Crea un webhook. Devuelve el ``secret`` solo en esta respuesta.

    Si se incluye ``Idempotency-Key``, una segunda request con la misma
    clave devuelve la respuesta original sin crear un duplicado.
    """
    response.headers["Cache-Control"] = "no-store"
    endpoint = _idempotency_endpoint(ctx)
    fingerprint = _request_fingerprint(body)
    reservation_token: str | None = None

    # -- Idempotency check/reservation --
    if idempotency_key:
        if not _IDEMPOTENCY_KEY_RE.fullmatch(idempotency_key):
            raise HTTPException(status_code=400, detail="Invalid Idempotency-Key format.")
        reservation_token = secrets.token_urlsafe(24)
        owns_reservation, cached = await run_db(
            _repo.idempotency_reserve,
            idempotency_key,
            endpoint,
            fingerprint,
            reservation_token,
            settings.IDEMPOTENCY_TTL_SECONDS,
        )
        if not owns_reservation:
            cached_fingerprint = str(cached.get("_request_fingerprint") or "")
            if not hmac.compare_digest(cached_fingerprint, fingerprint):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency-Key was already used with a different request.",
                )
            if cached.get("_pending"):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="An identical request is still being processed.",
                    headers={"Retry-After": "1"},
                )
            try:
                webhook_id = int(cached["id"])
                secret = await run_db(_repo.get_secret, webhook_id)
                if not secret:
                    raise ValueError("secret unavailable")
                log.info(
                    "webhook_create_idempotent_hit",
                    idempotency_key_hash=hashlib.sha256(idempotency_key.encode()).hexdigest()[:12],
                )
                return WebhookCreateResponse(
                    id=webhook_id,
                    name=str(cached["name"]),
                    url=str(cached["url"]),
                    event_types=list(cached["event_types"]),
                    secret=secret,
                )
            except (KeyError, TypeError, ValueError):
                # Do not replay a legacy cache row that may contain a secret or
                # lacks a request fingerprint; a caller must use a new key.
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency-Key cannot be safely replayed. Use a new key.",
                ) from None

    try:
        webhook_id, secret = await run_db(
            _repo.create, name=body.name, url=body.url, event_types=body.event_types
        )
    except Exception:
        if idempotency_key and reservation_token:
            await run_db(_repo.idempotency_release, idempotency_key, endpoint, reservation_token)
        raise
    if not secret:
        if idempotency_key and reservation_token:
            await run_db(_repo.idempotency_release, idempotency_key, endpoint, reservation_token)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook creation did not produce a signing secret.",
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

    # -- Persist idempotency result without the webhook secret --
    if idempotency_key and reservation_token:
        finalized = await run_db(
            _repo.idempotency_finalize,
            idempotency_key,
            endpoint,
            reservation_token,
            {
                "id": webhook_id,
                "name": body.name,
                "url": body.url,
                "event_types": body.event_types,
                "_request_fingerprint": fingerprint,
            },
        )
        if not finalized:
            log.error("webhook_idempotency_finalize_failed", webhook_id=webhook_id)

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

    url = str(wh["url"])
    try:
        _validate_webhook_url(url)
    except ValueError as exc:
        log.warning("webhook_ping_ssrf_blocked", webhook_id=webhook_id, error=str(exc))
        return {"success": False, "error": f"SSRF blocked: {exc}"}

    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Signature": f"sha256={sig}",
        "X-Webhook-Event": "ping",
        "User-Agent": "licitaciones-sap-webhook/1.0",
    }

    # Retry with exponential backoff (max 2 retries)
    max_attempts = 3
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            status_code = await _asyncio.to_thread(
                _post_pinned_webhook,
                url,
                payload,
                headers,
            )
            ok = 200 <= status_code < 300
            _repo.record_delivery(
                webhook_id,
                status_code=status_code,
                success=ok,
                event_type="ping",
                payload_size=len(payload),
            )
            return {"success": ok, "status_code": status_code, "attempts": attempt + 1}
        except (RequestException, ValueError) as exc:
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
