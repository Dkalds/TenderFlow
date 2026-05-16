"""Gestión de webhooks salientes (B5).

Tabla ``webhooks`` gestiona suscripciones HTTP de clientes externos a eventos
del sistema (e.g. ``watchlist_match``, ``daily_summary``).

Cuando se dispara un evento, :func:`trigger_event` envía un POST firmado con
HMAC-SHA256 al ``url`` registrado. La firma viaja en la cabecera
``X-Webhook-Signature`` para que el receptor pueda validar autenticidad.

Las entregas son **best-effort**: timeout de 5s, reintentos limitados,
``failure_count`` se incrementa para detectar webhooks moribundos.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from typing import Any

import requests

from db.database import connect, now_utc_iso
from observability.logging import get_logger

log = get_logger(__name__)

_DELIVERY_TIMEOUT_S = 5.0
_MAX_FAILURES_BEFORE_DISABLE = 10


def _sign(secret: str, payload: bytes) -> str:
    """Firma HMAC-SHA256 en hex del payload con el secret del webhook."""
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def create_webhook(*, name: str, url: str, event_types: list[str]) -> tuple[int, str]:
    """Crea un webhook nuevo y devuelve (id, secret).

    El secret se genera de forma criptográficamente segura y solo se devuelve
    en la creación. Después se almacena para firmar payloads pero no se
    expone vía API.
    """
    secret = secrets.token_urlsafe(32)
    now = now_utc_iso()
    with connect() as c:
        cur = c.execute(
            "INSERT INTO webhooks "
            "(name, url, secret, event_types, active, created_at) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (name, url, secret, ",".join(event_types), now),
        )
        webhook_id = int(cur.lastrowid or 0)
    log.info("webhook_created", webhook_id=webhook_id, url=url, events=event_types)
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
        cur = c.execute("DELETE FROM webhooks WHERE id = ?", (webhook_id,))
        return cur.rowcount > 0


def trigger_event(event_type: str, payload: dict[str, Any]) -> int:
    """Dispara ``event_type`` a todos los webhooks activos suscritos.

    Devuelve el número de entregas exitosas (HTTP 2xx).
    """
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

    for wid, url, secret, events_csv in rows:
        events = {e.strip() for e in events_csv.split(",")}
        if event_type not in events and "*" not in events:
            continue

        signature = _sign(secret, body)
        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Signature": f"sha256={signature}",
            "X-Webhook-Event": event_type,
            "User-Agent": "licitaciones-sap-webhook/1.0",
        }
        try:
            resp = requests.post(url, data=body, headers=headers, timeout=_DELIVERY_TIMEOUT_S)
            ok = 200 <= resp.status_code < 300
            _record_delivery(wid, resp.status_code, ok)
            if ok:
                successful += 1
        except requests.RequestException as exc:
            log.warning("webhook_delivery_failed", webhook_id=wid, error=str(exc))
            _record_delivery(wid, 0, False)

    return successful


def _record_delivery(webhook_id: int, status_code: int, success: bool) -> None:
    """Actualiza last_triggered_at, last_status y failure_count.

    Si ``failure_count`` supera el umbral, deshabilita el webhook.
    """
    with connect() as c:
        if success:
            c.execute(
                "UPDATE webhooks SET last_triggered_at = ?, last_status = ?, "
                "failure_count = 0 WHERE id = ?",
                (now_utc_iso(), status_code, webhook_id),
            )
        else:
            c.execute(
                "UPDATE webhooks SET last_triggered_at = ?, last_status = ?, "
                "failure_count = failure_count + 1, "
                "active = CASE WHEN failure_count + 1 >= ? THEN 0 ELSE active END "
                "WHERE id = ?",
                (now_utc_iso(), status_code, _MAX_FAILURES_BEFORE_DISABLE, webhook_id),
            )
