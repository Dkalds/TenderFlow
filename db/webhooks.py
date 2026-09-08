"""Gestión de webhooks salientes (B5).

Tabla ``webhooks`` gestiona suscripciones HTTP de clientes externos a eventos
del sistema (e.g. ``watchlist_match``, ``daily_summary``).

Cuando se dispara un evento, :func:`trigger_event` envía un POST firmado con
HMAC-SHA256 al ``url`` registrado. La firma viaja en la cabecera
``X-Webhook-Signature`` para que el receptor pueda validar autenticidad.

Las entregas son **best-effort**: timeout de 5s, reintentos limitados,
``failure_count`` se incrementa para detectar webhooks moribundos.

**Seguridad (issue #49)**: los secretos de nuevos webhooks se derivan de una
clave maestra del servidor via HMAC. No se almacenan en texto plano.
Webhooks legacy (pre-derivación) siguen funcionando con su secret almacenado.

**Seguridad (RFC llm-dependencia-gestionada §C3.0)**: ``trigger_event`` resuelve
DNS y pinnea la IP al momento del envío (misma validación que el ping manual,
``shared/ssrf.py``) — cierra la ventana TOCTOU de DNS rebinding entre el
registro del webhook y cada entrega real.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from typing import Any, cast

import requests

from db.database import connect, now_utc_iso
from db.repositories.webhooks import (
    crear_entrega,
    marcar_para_reintento,
    marcar_webhook_tras_intento,
)
from observability.logging import get_logger
from shared.crypto import DERIVED_SECRET_SENTINEL, derive_webhook_secret, is_derived_secret
from shared.outbound_http import pinned_https_request
from shared.ssrf import validate_outbound_url

log = get_logger(__name__)

_DELIVERY_TIMEOUT_S = 5.0

#: Solicitud de acceso nueva desde la landing. La emite
#: ``api/routes/publico_solicitudes.py`` y la acepta como suscripción
#: ``api/routes/webhooks.py``; el nombre vive aquí, con el resto de la
#: maquinaria de entrega, para que los dos extremos no puedan escribirlo
#: distinto y el evento se pierda sin que falle nada.
EVENTO_SOLICITUD_ACCESO = "solicitud_acceso.creada"
_MAX_FAILURES_BEFORE_DISABLE = 10


def _allowed_webhook_hosts() -> frozenset[str]:
    from config.settings import settings

    return frozenset(
        host.strip() for host in settings.WEBHOOK_ALLOWED_HOSTS.split(",") if host.strip()
    )


def _get_webhook_master_key() -> str:
    """Obtiene la clave maestra para derivar secretos de webhook."""
    from config.settings import settings

    key = settings.WEBHOOK_SIGNING_KEY.get_secret_value()
    if not key:
        key = settings.SIGNING_KEY.get_secret_value()
    return key


def _resolve_secret(webhook_id: int, stored_secret: str) -> str:
    """Resuelve el secreto de firma para un webhook.

    Si el secreto almacenado es el sentinel de derivación, re-deriva desde
    la clave maestra. Si es un secreto legacy en texto plano, lo usa tal cual.
    """
    if is_derived_secret(stored_secret):
        master_key = _get_webhook_master_key()
        if not master_key:
            log.error("webhook_no_master_key", webhook_id=webhook_id)
            return stored_secret
        return derive_webhook_secret(master_key, webhook_id)
    return stored_secret


def _sign(secret: str, payload: bytes) -> str:
    """Firma HMAC-SHA256 en hex del payload con el secret del webhook."""
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def create_webhook(*, name: str, url: str, event_types: list[str]) -> tuple[int, str]:
    """Crea un webhook nuevo y devuelve (id, secret).

    El secret se deriva de la clave maestra del servidor + webhook_id.
    Solo se devuelve en la creación — no se almacena en texto plano.
    Si no hay clave maestra configurada (dev), se genera un secret aleatorio
    como fallback (legacy behavior).
    """
    now = now_utc_iso()
    master_key = _get_webhook_master_key()

    with connect() as c:
        # Insert with placeholder; we need the ID to derive the secret.
        # RETURNING y no lastval(): el id tiene que ser el de ESTA fila aunque
        # un trigger toque otra secuencia — de él se deriva el secret HMAC.
        row = c.execute(
            "INSERT INTO webhooks "
            "(name, url, secret, event_types, active, created_at) "
            "VALUES (%s, %s, %s, %s, 1, %s) RETURNING id",
            (name, url, DERIVED_SECRET_SENTINEL, ",".join(event_types), now),
        ).fetchone()
        webhook_id = int(row[0]) if row else 0

    if master_key:
        secret = derive_webhook_secret(master_key, webhook_id)
    else:
        # Dev fallback: generate random secret (legacy behavior)
        import secrets as _secrets

        secret = _secrets.token_urlsafe(32)
        with connect() as c:
            c.execute(
                "UPDATE webhooks SET secret = %s WHERE id = %s",
                (secret, webhook_id),
            )

    log.info("webhook_created", webhook_id=webhook_id, events=event_types)
    return webhook_id, secret


def list_webhooks() -> list[dict[str, Any]]:
    """Lista todos los webhooks (sin exponer el secret)."""
    with connect() as c:
        cur = c.execute(
            "SELECT id, name, url, event_types, active, created_at, "
            "last_triggered_at, last_status, failure_count FROM webhooks "
            "ORDER BY id"
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def delete_webhook(webhook_id: int) -> bool:
    """Borra un webhook. Devuelve True si existía."""
    with connect() as c:
        cur = c.execute("DELETE FROM webhooks WHERE id = %s", (webhook_id,))
        return cast(bool, cur.rowcount > 0)


def _cabeceras(*, secret: str, body: bytes, event_type: str, delivery_uid: str) -> dict[str, str]:
    """Cabeceras de una entrega. La firma se calcula **sobre el cuerpo dado**.

    De ahí que el cuerpo se guarde en ``webhook_deliveries.payload_json`` en vez
    de reconstruirse en el reintento: un ``timestamp`` regenerado cambiaría el
    JSON, y con él la firma, así que el receptor vería dos mensajes distintos
    donde hubo un evento. ``X-Webhook-Delivery`` es estable entre intentos por
    el mismo motivo — es lo que permite al receptor deduplicar.
    """
    return {
        "Content-Type": "application/json",
        "X-Webhook-Signature": f"sha256={_sign(secret, body)}",
        "X-Webhook-Event": event_type,
        "X-Webhook-Delivery": delivery_uid,
        "User-Agent": "licitaciones-sap-webhook/1.0",
    }


def _intentar_entrega(
    *, url: str, headers: dict[str, str], body: bytes, allowed_hosts: frozenset[str]
) -> tuple[int, str | None]:
    """Un intento HTTP. Devuelve ``(status_code, error)``; ``0`` es «sin respuesta»."""
    try:
        resp = pinned_https_request(
            "POST",
            url,
            headers=headers,
            body=body,
            timeout_seconds=_DELIVERY_TIMEOUT_S,
            allowed_hosts=allowed_hosts or None,
        )
        try:
            return resp.status_code, None
        finally:
            resp.close()
    except (requests.RequestException, ValueError) as exc:
        return 0, str(exc)


def _aplicar_decision(*, webhook_id: int, status_code: int, exito: bool, decision: Any) -> None:
    """Traduce la decisión de reintento al estado del **webhook** (no de la entrega).

    Los tres casos no son intercambiables:

    - éxito → ``failure_count`` a cero.
    - fallo con reintento por delante → solo ``last_status``. Sumar aquí
      contaría el mismo evento hasta seis veces y desactivaría el webhook por
      media hora de caída del receptor, que es justo lo que el reintento existe
      para absorber.
    - fallo definitivo → suma y, en el umbral, desactiva.
    """
    if exito or decision.desactivar:
        _record_delivery(webhook_id, status_code, exito)
    else:
        marcar_webhook_tras_intento(webhook_id, status_code=status_code, exito=False)


def trigger_event(event_type: str, payload: dict[str, Any]) -> int:
    """Dispara ``event_type`` a todos los webhooks activos suscritos.

    Devuelve el número de entregas exitosas **en el primer intento** (HTTP 2xx).
    Las que fallan quedan en ``webhook_deliveries`` con estado ``pending`` y
    fecha del siguiente intento; las reenvía
    ``scheduler.jobs.webhook_reintentos``. Antes de C2.4 se perdían: un receptor
    en despliegue no recibía los eventos de esos minutos y nadie se lo decía.
    """
    from services.webhook_retry import decidir

    body = json.dumps(
        {"event": event_type, "data": payload, "timestamp": now_utc_iso()},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    successful = 0
    with connect() as c:
        rows = c.execute(
            "SELECT id, url, secret, event_types FROM webhooks WHERE active = 1"
        ).fetchall()

    for wid, url, stored_secret, events_csv in rows:
        events = {e.strip() for e in events_csv.split(",")}
        if event_type not in events and "*" not in events:
            continue

        try:
            allowed_hosts = _allowed_webhook_hosts()
            from config.settings import settings

            if settings.ENV in ("prod", "staging") and not allowed_hosts:
                raise ValueError("WEBHOOK_ALLOWED_HOSTS no está configurado")
            validate_outbound_url(url, allowed_hosts=allowed_hosts or None)
        except ValueError as exc:
            # Un bloqueo SSRF no se reintenta: el destino no va a dejar de ser
            # una IP privada dentro de seis horas, y encolarlo solo repetiría la
            # resolución DNS que se acaba de rechazar.
            log.warning("webhook_trigger_ssrf_blocked", webhook_id=wid, error=str(exc))
            _record_delivery(wid, 0, False)
            continue

        delivery_uid = uuid.uuid4().hex
        secret = _resolve_secret(wid, stored_secret)
        headers = _cabeceras(
            secret=secret, body=body, event_type=event_type, delivery_uid=delivery_uid
        )
        status_code, error = _intentar_entrega(
            url=url, headers=headers, body=body, allowed_hosts=allowed_hosts
        )
        ok = 200 <= status_code < 300
        if not ok and error:
            log.warning("webhook_delivery_failed", webhook_id=wid, error=error)

        decision = decidir(exito=ok, intentos_hechos=1)
        crear_entrega(
            webhook_id=wid,
            event_type=event_type,
            payload_json=body.decode("utf-8"),
            delivery_uid=delivery_uid,
            estado=decision.estado,
            status_code=status_code,
            success=ok,
            proximo_intento=(
                decision.proximo_intento.isoformat() if decision.proximo_intento else None
            ),
            error=error,
        )
        _aplicar_decision(webhook_id=wid, status_code=status_code, exito=ok, decision=decision)
        if ok:
            successful += 1

    return successful


def reenviar(entrega: dict[str, Any]) -> bool:
    """Reintenta una entrega pendiente. Devuelve si esta vez salió.

    La usa ``scheduler.jobs.webhook_reintentos``. El cuerpo y el identificador
    son los de la entrega original —no se regeneran—, así que el receptor ve el
    mismo mensaje con la misma firma y puede deduplicar por
    ``X-Webhook-Delivery``.
    """
    from services.webhook_retry import decidir

    wid = int(entrega["webhook_id"])
    entrega_id = int(entrega["id"])
    with connect() as c:
        fila = c.execute("SELECT url, secret FROM webhooks WHERE id = %s", (wid,)).fetchone()
    if fila is None:
        marcar_para_reintento(
            entrega_id, estado="failed", proximo_intento=None, error="webhook borrado"
        )
        return False

    url, stored_secret = fila[0], fila[1]
    body = cast(str, entrega["payload_json"]).encode("utf-8")
    try:
        allowed_hosts = _allowed_webhook_hosts()
        validate_outbound_url(url, allowed_hosts=allowed_hosts or None)
    except ValueError as exc:
        # Definitivo, no pendiente: reencolarlo repetiría el mismo rechazo cada
        # ventana hasta agotar los seis intentos sin haber salido a la red.
        marcar_para_reintento(
            entrega_id, estado="failed", proximo_intento=None, error=f"SSRF: {exc}"
        )
        return False

    headers = _cabeceras(
        secret=_resolve_secret(wid, stored_secret),
        body=body,
        event_type=cast(str, entrega["event_type"]),
        delivery_uid=cast(str, entrega["delivery_uid"]),
    )
    status_code, error = _intentar_entrega(
        url=url, headers=headers, body=body, allowed_hosts=allowed_hosts
    )
    ok = 200 <= status_code < 300
    decision = decidir(exito=ok, intentos_hechos=int(entrega.get("intentos") or 1) + 1)
    marcar_para_reintento(
        entrega_id,
        estado=decision.estado,
        proximo_intento=(
            decision.proximo_intento.isoformat() if decision.proximo_intento else None
        ),
        error=error,
    )
    _aplicar_decision(webhook_id=wid, status_code=status_code, exito=ok, decision=decision)
    return ok


def _record_delivery(webhook_id: int, status_code: int, success: bool) -> None:
    """Actualiza last_triggered_at, last_status y failure_count.

    Si ``failure_count`` supera el umbral, deshabilita el webhook.
    """
    with connect() as c:
        if success:
            c.execute(
                "UPDATE webhooks SET last_triggered_at = %s, last_status = %s, "
                "failure_count = 0 WHERE id = %s",
                (now_utc_iso(), status_code, webhook_id),
            )
        else:
            c.execute(
                "UPDATE webhooks SET last_triggered_at = %s, last_status = %s, "
                "failure_count = failure_count + 1, "
                "active = CASE WHEN failure_count + 1 >= %s THEN 0 ELSE active END "
                "WHERE id = %s",
                (now_utc_iso(), status_code, _MAX_FAILURES_BEFORE_DISABLE, webhook_id),
            )
