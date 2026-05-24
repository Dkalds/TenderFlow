"""Repository para webhooks."""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts
from shared.crypto import DERIVED_SECRET_SENTINEL, derive_webhook_secret, is_derived_secret


def _get_webhook_master_key() -> str:
    """Obtiene la clave maestra para derivar secretos de webhook."""
    from config.settings import settings

    key = settings.WEBHOOK_SIGNING_KEY.get_secret_value()
    if not key:
        key = settings.SIGNING_KEY.get_secret_value()
    return key


class WebhookRepository:
    def create(self, *, name: str, url: str, event_types: list[str]) -> tuple[int, str]:
        now = now_utc_iso()
        master_key = _get_webhook_master_key()

        with connect() as c:
            cur = c.execute(
                "INSERT INTO webhooks (name, url, secret, event_types, active, created_at) "
                "VALUES (?, ?, ?, ?, 1, ?)",
                (name, url, DERIVED_SECRET_SENTINEL, ",".join(event_types), now),
            )
            webhook_id = int(cur.lastrowid or 0)

        if master_key:
            secret = derive_webhook_secret(master_key, webhook_id)
        else:
            import secrets as _secrets

            secret = _secrets.token_urlsafe(32)
            with connect() as c:
                c.execute(
                    "UPDATE webhooks SET secret = ? WHERE id = ?",
                    (secret, webhook_id),
                )

        return webhook_id, secret

    def list_all(self) -> list[dict[str, Any]]:
        with connect_read() as c:
            cur = c.execute(
                "SELECT id, name, url, event_types, active, created_at, "
                "last_triggered_at, last_status, failure_count FROM webhooks ORDER BY id"
            )
            return rows_to_dicts(cur)

    def get_by_id(self, webhook_id: int) -> dict[str, Any] | None:
        with connect_read() as c:
            cur = c.execute(
                "SELECT id, name, url, event_types, active, created_at, "
                "last_triggered_at, last_status, failure_count FROM webhooks WHERE id = ?",
                (webhook_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row, strict=False))

    def delete(self, webhook_id: int) -> bool:
        with connect() as c:
            cur = c.execute("DELETE FROM webhooks WHERE id = ?", (webhook_id,))
            return cur.rowcount > 0

    def update(
        self,
        webhook_id: int,
        *,
        name: str | None,
        url: str | None,
        event_types: list[str] | None,
        active: bool | None,
    ) -> bool:
        """Actualiza campos opcionales. Devuelve True si encontró el registro."""
        sets: list[str] = []
        params: list[Any] = []
        if name is not None:
            sets.append("name = ?")
            params.append(name)
        if url is not None:
            sets.append("url = ?")
            params.append(url)
        if event_types is not None:
            sets.append("event_types = ?")
            params.append(",".join(event_types))
        if active is not None:
            sets.append("active = ?")
            params.append(1 if active else 0)
        if not sets:
            return True
        params.append(webhook_id)
        with connect() as c:
            cur = c.execute(
                "UPDATE webhooks SET " + ", ".join(sets) + " WHERE id = ?",
                tuple(params),
            )
            return cur.rowcount > 0

    def get_secret(self, webhook_id: int) -> str | None:
        """Get the effective signing secret for a webhook.

        For derived secrets, re-derives from the master key.
        For legacy secrets, returns the stored value.
        """
        with connect_read() as c:
            row = c.execute("SELECT secret FROM webhooks WHERE id = ?", (webhook_id,)).fetchone()
        if not row:
            return None
        stored = str(row[0])
        if is_derived_secret(stored):
            master_key = _get_webhook_master_key()
            if master_key:
                return derive_webhook_secret(master_key, webhook_id)
        return stored

    def record_delivery(
        self,
        webhook_id: int,
        *,
        status_code: int,
        success: bool,
        event_type: str,
        payload_size: int,
    ) -> None:
        """Registra una entrega en webhook_deliveries y actualiza stats."""
        now = now_utc_iso()
        with connect() as c:
            try:
                c.execute(
                    "INSERT INTO webhook_deliveries "
                    "(webhook_id, event_type, status_code, success, payload_size, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (webhook_id, event_type, status_code, 1 if success else 0, payload_size, now),
                )
            except Exception:
                pass  # tabla no existe aún — no crítico
            if success:
                c.execute(
                    "UPDATE webhooks SET last_triggered_at = ?, last_status = ?, failure_count = 0 WHERE id = ?",
                    (now, status_code, webhook_id),
                )
            else:
                c.execute(
                    "UPDATE webhooks SET last_triggered_at = ?, last_status = ?, "
                    "failure_count = failure_count + 1, "
                    "active = CASE WHEN failure_count + 1 >= 10 THEN 0 ELSE active END "
                    "WHERE id = ?",
                    (now, status_code, webhook_id),
                )

    def list_deliveries(self, webhook_id: int, limit: int = 50) -> list[dict[str, Any]]:
        with connect_read() as c:
            try:
                cur = c.execute(
                    "SELECT id, webhook_id, event_type, status_code, success, payload_size, created_at "
                    "FROM webhook_deliveries WHERE webhook_id = ? ORDER BY created_at DESC LIMIT ?",
                    (webhook_id, limit),
                )
                return rows_to_dicts(cur)
            except Exception:
                return []

    def idempotency_get(self, key: str, endpoint: str = "webhooks") -> dict[str, Any] | None:
        import json

        with connect_read() as c:
            row = c.execute(
                "SELECT response_json FROM idempotency_keys WHERE idem_key = ? AND endpoint = ?",
                (key, endpoint),
            ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except Exception:
            return None

    def idempotency_store(
        self, key: str, endpoint: str = "webhooks", response: dict[str, Any] | None = None
    ) -> None:
        import json

        if response is None:
            response = {}
        with connect() as c:
            c.execute(
                "INSERT OR IGNORE INTO idempotency_keys (idem_key, endpoint, response_json, created_at) "
                "VALUES (?, ?, ?, ?)",
                (key, endpoint, json.dumps(response, ensure_ascii=False), now_utc_iso()),
            )
