"""Rutas /api/v1/webhooks — gestión de suscripciones a eventos.

Endpoints:
    POST   /api/v1/webhooks              — crear (devuelve secret una sola vez)
    GET    /api/v1/webhooks              — listar (sin secret)
    GET    /api/v1/webhooks/{id}         — detalle
    PATCH  /api/v1/webhooks/{id}         — actualizar campos opcionales
    DELETE /api/v1/webhooks/{id}         — eliminar
    POST   /api/v1/webhooks/{id}/ping    — enviar entrega de prueba
    GET    /api/v1/webhooks/{id}/deliveries — historial de entregas

Desde S4.2 del plan 2026-09 v2 **un webhook pertenece a una organización**:
lo crea y lo gestiona cualquier miembro con permiso de escritura
(``require_organization(write=True)``), no el administrador de la instancia. El
motivo es que la restricción anterior no protegía nada —el recurso no tenía
dueño, así que la única forma de que un equipo tuviera su canal era que otro se
lo creara— y a cambio dejaba la integración de Slack o Teams de cada equipo en
la cola de un administrador.

Las filas anteriores a la revisión ``v108`` no tienen organización. Se tratan
como **globales**: siguen entregando y siguen viéndose desde la vista de
``/ops`` (``GET /webhooks/global``, solo administradores), pero ningún miembro
las ve ni las edita desde su equipo.

Consecuencia deliberada: **un principal sin fila de usuario ya no gestiona
webhooks**. Resolver la organización activa empieza por leer el usuario, así
que una credencial huérfana falla en vez de caer a una vista sin ámbito. No es
una regresión funcional: ``api/auth.py`` rechaza en prod y staging una API key
sin dueño (``unbound_api_key_rejected``) y ``create_api_key`` ni siquiera deja
emitirla, de modo que el único principal sin usuario posible es el de
desarrollo/tests. Degradar aquí a la vista global para tolerarlo habría dado a
esa credencial de compatibilidad **más** alcance que a un miembro real —el de
todas las organizaciones a la vez—, que es exactamente el agujero que S4.2
viene a cerrar.
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
from api.routes.dual_auth import require_admin, require_any_auth
from api.tenancy import require_organization, resolve_organization_ctx
from config.settings import settings
from db.audit import log_event
from db.events import registrar_metrica_pendientes
from db.repositories.webhooks import WebhookRepository
from observability.logging import get_logger
from shared.events import (
    FORMATOS,
    Formato,
    normalizar_formato,
    renderizar,
    suscripciones_validas,
)
from shared.outbound_http import pinned_https_request
from shared.ssrf import validate_outbound_url

log = get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

#: Vocabulario de suscripción. Sale del catálogo de ``shared/events.py`` —
#: tipos exactos y comodines de familia (``pursuit.*``, ``licitacion.*``,
#: ``adjudicacion.*``, ``renovacion.*``, ``ficha.*``)— más los dos nombres
#: legacy que hay suscritos en producción desde antes del catálogo.
#:
#: `solicitud_acceso.creada` (hoy en el catálogo) lo emite
#: `publico_solicitudes.py` cuando entra una petición desde la landing: sin una
#: suscripción a ese evento, la cola de acceso —que se atiende a mano— solo se
#: descubre abriendo el panel.
_EVENTOS_LEGACY = ("watchlist_match", "daily_summary")

_VALID_EVENTS = frozenset({*suscripciones_validas(), *_EVENTOS_LEGACY})
_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _allowed_webhook_hosts() -> frozenset[str]:
    return frozenset(
        host.strip() for host in settings.WEBHOOK_ALLOWED_HOSTS.split(",") if host.strip()
    )


def _validate_webhook_url(url: str) -> str:
    allowed_hosts = _allowed_webhook_hosts()
    if settings.ENV in ("prod", "staging") and not allowed_hosts:
        raise ValueError("Los webhooks salientes están deshabilitados: falta WEBHOOK_ALLOWED_HOSTS")
    validate_outbound_url(url, allowed_hosts=allowed_hosts or None)
    return url


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
        examples=[["pursuit.*"]],
    )
    # `| None` y no `= "json"` a propósito: el generador del cliente TS trata
    # una propiedad con `default` como obligatoria en el cuerpo, así que un
    # default aquí obligaría a TODOS los llamantes existentes a mandar el campo.
    # `None` es «no me importa el formato» y el servidor lo resuelve a `json`.
    formato: Formato | None = Field(
        default=None,
        description="Plantilla del cuerpo entregado: JSON crudo, Block Kit de "
        "Slack o Adaptive Card de Teams. Por defecto, JSON.",
    )
    organization_id: int | None = Field(
        default=None,
        ge=1,
        description="Organización dueña del webhook; por defecto, la personal del usuario.",
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


class WebhookDelivery(BaseModel):
    """Una entrega registrada de un webhook.

    Antes esta ruta devolvía ``list[dict[str, Any]]`` y el cliente generado la
    veía como `{ [key: string]: unknown }[]`, obligando al frontend a
    redeclarar la forma a mano — el anti-patrón que ya hizo que el Radar
    pintase campos inexistentes.
    """

    id: int
    webhook_id: int
    event_type: str
    status_code: int | None = None
    success: bool
    payload_size: int | None = None
    created_at: str


class WebhookEventTypes(BaseModel):
    """Tipos de evento a los que un webhook puede suscribirse, y formatos.

    Los sirve el backend en vez de que la UI los duplique: la lista es la misma
    que valida `WebhookCreate.event_types`, así que no pueden divergir. Los
    formatos viajan aquí por el mismo motivo — el selector de plantilla de la
    UI ofrecía tres literales escritos a mano.
    """

    event_types: list[str]
    formatos: list[str] = list(FORMATOS)


class WebhookUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    url: str | None = None
    event_types: list[str] | None = None
    active: bool | None = None
    formato: Formato | None = None

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
    formato: Formato = "json"
    organization_id: int | None = None
    secret: str = Field(
        ...,
        description="Secret para verificar firma HMAC (X-Webhook-Signature). "
        "Solo se devuelve en la creación; guárdalo de forma segura.",
    )


# ── Endpoints ────────────────────────────────────────────────────────────────

_repo = WebhookRepository()

# `domain_events_pending` se publica al importar el router, que es lo que
# ocurre al montar la app. El colector vive en `db/events.py` (donde está el
# SQL, ADR-022) y se registra desde aquí porque este módulo es la superficie
# HTTP del backbone de eventos y `api/routes/metrics.py` solo sabe serializar
# el registro, no qué hay que meter en él. Es best-effort: sin
# `prometheus_client` no hace nada.
registrar_metrica_pendientes()


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
    ctx: dict[str, Any] = Depends(require_any_auth),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> WebhookCreateResponse:
    """Crea un webhook en tu organización. Devuelve el ``secret`` solo aquí.

    Si se incluye ``Idempotency-Key``, una segunda request con la misma
    clave devuelve la respuesta original sin crear un duplicado.
    """
    ctx = await resolve_organization_ctx(ctx, body.organization_id, write=True)
    organization_id = int(ctx["organization_id"])
    formato = normalizar_formato(body.formato)
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
                    formato=normalizar_formato(str(cached.get("formato") or "")),
                    organization_id=organization_id,
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
            _repo.create,
            name=body.name,
            url=body.url,
            event_types=body.event_types,
            organization_id=organization_id,
            created_by=int(ctx["user_id"]) if ctx.get("user_id") is not None else None,
            formato=formato,
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
    await run_db(
        log_event,
        event_type="webhook.created",
        user_key=_actor_key(ctx),
        resource=f"webhook:{webhook_id}",
        detail={
            "name": body.name,
            "events": body.event_types,
            "organization_id": organization_id,
        },
    )
    response_data = WebhookCreateResponse(
        id=webhook_id,
        name=body.name,
        url=body.url,
        event_types=body.event_types,
        formato=formato,
        organization_id=organization_id,
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
                "formato": formato,
                "_request_fingerprint": fingerprint,
            },
        )
        if not finalized:
            log.error("webhook_idempotency_finalize_failed", webhook_id=webhook_id)

    return response_data


class WebhookOut(BaseModel):
    """Webhook sin secret (el secret solo viaja al crearlo)."""

    id: int
    name: str | None
    url: str
    event_types: list[str]
    # `bool`, no `int`: la columna guarda 0/1 —herencia de SQLite— pero eso es
    # su representación en disco, no el contrato. El PATCH ya recibía
    # `active: bool | None`, así que el cliente escribía un booleano y leía un
    # entero; Pydantic hace la coerción y la asimetría desaparece.
    active: bool | None
    created_at: str | None
    last_triggered_at: str | None
    last_status: int | None
    failure_count: int | None
    # `None` en las filas anteriores a la revisión v108: son los webhooks
    # globales de la instancia, sin dueño y visibles solo desde /ops.
    organization_id: int | None = None
    created_by: int | None = None
    formato: Formato = "json"


class WebhookPingResult(BaseModel):
    """Entrega de prueba; los campos son condicionales según el fallo."""

    success: bool
    status_code: int | None = None
    attempts: int | None = None
    error: str | None = None


@router.get(
    "",
    summary="Listar los webhooks de tu organización (sin secret)",
    responses={401: {"description": "API key inválida"}},
)
async def list_all(
    ctx: dict[str, Any] = Depends(require_organization()),
) -> list[WebhookOut]:
    """Listado de webhooks de la organización activa, sin el secret."""
    # Devolvía `list[dict[str, Any]]` -> `unknown[]` en el cliente, mientras el
    # detalle de aquí al lado ya devolvía `WebhookOut`. Las dos consultas del
    # repositorio proyectan las MISMAS columnas: la lista y el detalle
    # describían la misma fila con dos contratos, uno tipado y otro no.
    rows = await run_db(_repo.list_for_organization, int(ctx["organization_id"]))
    return [WebhookOut(**row) for row in rows]


@router.get(
    "/global",
    summary="Listar TODOS los webhooks de la instancia (vista de /ops)",
    responses={401: {"description": "API key inválida"}, 403: {"description": "Requiere admin"}},
)
async def list_global(
    _ctx: dict[str, Any] = Depends(require_admin),
) -> list[WebhookOut]:
    """Todos los webhooks, de cualquier organización y sin dueño.

    Es la vista que se queda en ``/ops`` cuando la gestión por equipo se muda a
    ``/equipo``: el administrador de la instancia sigue necesitando ver las
    integraciones globales (las anteriores a ``v108``, que no tienen
    organización) y el estado agregado de entregas.
    """
    return [WebhookOut(**row) for row in await run_db(_repo.list_all)]


@router.get(
    "/event-types",
    summary="Tipos de evento a los que suscribirse",
    responses={401: {"description": "API key inválida"}},
)
async def event_types(
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> WebhookEventTypes:
    """Lista los eventos válidos, derivada de la misma constante que valida el alta.

    Declarada **antes** que ``/{webhook_id}``: FastAPI resuelve por orden de
    declaración y, con la ruta paramétrica delante, ``/webhooks/event-types``
    entraba por ella y moría en la validación de ``webhook_id: int`` con un 422.
    """
    return WebhookEventTypes(event_types=sorted(_VALID_EVENTS), formatos=list(FORMATOS))


@router.get(
    "/{webhook_id}",
    summary="Detalle de un webhook",
    responses={401: {"description": "API key inválida"}, 404: {"description": "No encontrado"}},
)
async def get_one(
    webhook_id: int,
    ctx: dict[str, Any] = Depends(require_organization()),
) -> WebhookOut:
    wh = await run_db(_repo.get_by_id, webhook_id, organization_id=int(ctx["organization_id"]))
    if wh is None:
        raise HTTPException(status_code=404, detail="Webhook no encontrado.")
    return WebhookOut(**wh)


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
    ctx: dict[str, Any] = Depends(require_organization(write=True)),
) -> WebhookOut:
    """Actualiza nombre, URL, event_types, formato o active de un webhook."""
    organization_id = int(ctx["organization_id"])
    found = await run_db(
        _repo.update,
        webhook_id,
        name=body.name,
        url=body.url,
        event_types=body.event_types,
        active=body.active,
        formato=body.formato,
        organization_id=organization_id,
    )
    if not found:
        raise HTTPException(status_code=404, detail="Webhook no encontrado.")
    await run_db(
        log_event,
        event_type="webhook.updated",
        user_key=_actor_key(ctx),
        resource=f"webhook:{webhook_id}",
    )
    wh = await run_db(_repo.get_by_id, webhook_id, organization_id=organization_id)
    if wh is None:  # borrado concurrente entre el update y la relectura
        raise HTTPException(status_code=404, detail="Webhook no encontrado.")
    return WebhookOut(**wh)


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
    ctx: dict[str, Any] = Depends(require_organization(write=True)),
) -> None:
    if not await run_db(_repo.delete, webhook_id, organization_id=int(ctx["organization_id"])):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe")
    await run_db(
        log_event,
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
    ctx: dict[str, Any] = Depends(require_organization(write=True)),
) -> WebhookPingResult:
    """Envía un payload de prueba al URL del webhook para verificar conectividad.

    El cuerpo va **en el formato configurado** en el webhook: un ping que
    siempre saliera en JSON no probaría lo único que se quiere probar antes de
    activar una integración de Slack o Teams — que la plantilla llega y se
    pinta.
    """
    import asyncio as _asyncio
    import hashlib
    import hmac as _hmac
    import json

    wh = await run_db(_repo.get_by_id, webhook_id, organization_id=int(ctx["organization_id"]))
    if wh is None:
        raise HTTPException(status_code=404, detail="Webhook no encontrado.")

    secret = await run_db(_repo.get_secret, webhook_id)
    if not secret:
        raise HTTPException(status_code=500, detail="Secret no disponible.")

    from db.database import now_utc_iso

    payload = json.dumps(
        renderizar(
            "ping",
            {"message": "Test delivery", "webhook_id": webhook_id},
            formato=str(wh.get("formato") or ""),
            timestamp=now_utc_iso(),
        ),
        ensure_ascii=False,
    ).encode()
    sig = _hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    url = str(wh["url"])
    try:
        _validate_webhook_url(url)
    except ValueError as exc:
        log.warning("webhook_ping_ssrf_blocked", webhook_id=webhook_id, error=str(exc))
        return WebhookPingResult(success=False, error=f"SSRF blocked: {exc}")

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
            await run_db(
                _repo.record_delivery,
                webhook_id,
                status_code=status_code,
                success=ok,
                event_type="ping",
                payload_size=len(payload),
            )
            return WebhookPingResult(success=ok, status_code=status_code, attempts=attempt + 1)
        except (RequestException, ValueError) as exc:
            last_exc = exc
            if attempt < max_attempts - 1:
                await _asyncio.sleep(0.5 * (2**attempt))  # 0.5s, 1s

    await run_db(
        _repo.record_delivery,
        webhook_id,
        status_code=0,
        success=False,
        event_type="ping",
        payload_size=len(payload),
    )
    return WebhookPingResult(success=False, error=str(last_exc), attempts=max_attempts)


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
    ctx: dict[str, Any] = Depends(require_organization()),
) -> list[WebhookDelivery]:
    """Devuelve las últimas entregas realizadas para este webhook."""
    scope = int(ctx["organization_id"])
    if await run_db(_repo.get_by_id, webhook_id, organization_id=scope) is None:
        raise HTTPException(status_code=404, detail="Webhook no encontrado.")
    rows = await run_db(_repo.list_deliveries, webhook_id, limit=limit)
    return [WebhookDelivery(**row) for row in rows]
