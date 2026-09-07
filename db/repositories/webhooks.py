"""Repository para webhooks."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger
from shared.crypto import DERIVED_SECRET_SENTINEL, derive_webhook_secret, is_derived_secret

log = get_logger(__name__)


def _split_event_types(raw: Any) -> list[str]:
    """``event_types`` se guarda como TEXT (CSV) en la tabla; los consumidores
    de la API esperan una lista (contrato de ``WebhookCreateResponse``/UI)."""
    if not raw:
        return []
    return [e for e in str(raw).split(",") if e]


def _get_webhook_master_key() -> str:
    """Obtiene la clave maestra para derivar secretos de webhook."""
    from config.settings import settings

    key = settings.WEBHOOK_SIGNING_KEY.get_secret_value()
    if not key:
        key = settings.SIGNING_KEY.get_secret_value()
    return key


#: Columnas que proyectan lista y detalle. Una sola constante porque la
#: divergencia entre las dos ya produjo un contrato tipado y otro opaco para la
#: misma fila (ver el docstring de ``list_all``).
_COLUMNAS = (
    "id, name, url, event_types, active, created_at, "
    "last_triggered_at, last_status, failure_count, "
    "organization_id, created_by, formato"
)


def resolve_stored_secret(webhook_id: int, stored: str) -> str:
    """Secret efectivo a partir del valor almacenado, sin volver a la BD.

    ``WebhookRepository.get_secret`` hace lo mismo con una consulta propia; el
    despachador ya trae la columna en la fila del abanico y hacer N consultas
    más para re-leer lo que tiene delante sería una llamada por entrega.
    """
    if is_derived_secret(stored):
        master_key = _get_webhook_master_key()
        if master_key:
            return derive_webhook_secret(master_key, webhook_id)
    return stored


class WebhookRepository:
    def create(
        self,
        *,
        name: str,
        url: str,
        event_types: list[str],
        organization_id: int | None = None,
        created_by: int | None = None,
        formato: str = "json",
    ) -> tuple[int, str]:
        now = now_utc_iso()
        master_key = _get_webhook_master_key()

        with connect() as c:
            # RETURNING y no lastval(): de este id se deriva el secret HMAC del
            # webhook, así que tiene que ser el de ESTA fila sin ambigüedad.
            row = c.execute(
                "INSERT INTO webhooks "
                "(name, url, secret, event_types, active, created_at, "
                " organization_id, created_by, formato) "
                "VALUES (%s, %s, %s, %s, 1, %s, %s, %s, %s) RETURNING id",
                (
                    name,
                    url,
                    DERIVED_SECRET_SENTINEL,
                    ",".join(event_types),
                    now,
                    organization_id,
                    created_by,
                    formato,
                ),
            ).fetchone()
            webhook_id = int(row[0]) if row else 0

        if master_key:
            secret = derive_webhook_secret(master_key, webhook_id)
        else:
            import secrets as _secrets

            secret = _secrets.token_urlsafe(32)
            with connect() as c:
                c.execute(
                    "UPDATE webhooks SET secret = %s WHERE id = %s",
                    (secret, webhook_id),
                )

        return webhook_id, secret

    def list_all(self) -> list[dict[str, Any]]:
        """Todos los webhooks de la instancia. Solo lo usa la vista global de ``/ops``.

        Para lo que ve un equipo está ``list_for_organization``: desde S4.2 un
        miembro gestiona los webhooks de SU organización, y esta consulta —sin
        predicado de ámbito— enseñaría también los de las demás.
        """
        with connect_read() as c:
            cur = c.execute(f"SELECT {_COLUMNAS} FROM webhooks ORDER BY id")
            rows = rows_to_dicts(cur)
        for row in rows:
            row["event_types"] = _split_event_types(row.get("event_types"))
        return rows

    def list_for_organization(self, organization_id: int) -> list[dict[str, Any]]:
        """Webhooks de una organización. Nunca los de otra, ni los globales.

        Los globales (``organization_id IS NULL``) son las filas anteriores a
        la revisión ``v108``: no tienen dueño y quedan solo en la vista de
        ``/ops`` a propósito. Incluirlos aquí daría a cualquier miembro de
        cualquier organización acceso a la integración de la instancia.
        """
        with connect_read() as c:
            cur = c.execute(
                f"SELECT {_COLUMNAS} FROM webhooks WHERE organization_id = %s ORDER BY id",
                (organization_id,),
            )
            rows = rows_to_dicts(cur)
        for row in rows:
            row["event_types"] = _split_event_types(row.get("event_types"))
        return rows

    def get_by_id(
        self, webhook_id: int, *, organization_id: int | None = None
    ) -> dict[str, Any] | None:
        """Detalle de un webhook, opcionalmente acotado a una organización.

        Con ``organization_id`` devuelve ``None`` si la fila es de otra
        organización: el aislamiento se resuelve en el predicado y no
        comparando en el handler, que es donde se olvida.
        """
        sql = f"SELECT {_COLUMNAS} FROM webhooks WHERE id = %s"
        params: list[Any] = [webhook_id]
        if organization_id is not None:
            sql += " AND organization_id = %s"
            params.append(organization_id)
        with connect_read() as c:
            cur = c.execute(sql, params)
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d[0] for d in cur.description]
            result = dict(zip(cols, row, strict=False))
        result["event_types"] = _split_event_types(result.get("event_types"))
        return result

    def list_active_subscribers(
        self, *, organization_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Webhooks activos candidatos a recibir un evento.

        Devuelve la fila con ``event_types`` ya troceado y el ``secret``
        resuelto; el filtro por tipo lo aplica ``shared.events.suscripcion_cubre``
        (que entiende los comodines de familia) en vez de repetir aquí una
        comparación de cadenas que solo cubriría el tipo exacto.

        ``organization_id`` acota a los de esa organización **más** los
        globales sin dueño: un evento de la organización 7 sale por sus
        webhooks y por la integración de instancia, nunca por los de la 8.
        """
        sql = "SELECT id, url, secret, event_types, formato, organization_id FROM webhooks WHERE active = 1"
        params: list[Any] = []
        if organization_id is not None:
            sql += " AND (organization_id = %s OR organization_id IS NULL)"
            params.append(organization_id)
        with connect_read() as c:
            rows = rows_to_dicts(c.execute(sql, params))
        for row in rows:
            row["event_types"] = _split_event_types(row.get("event_types"))
        return rows

    def delete(self, webhook_id: int, *, organization_id: int | None = None) -> bool:
        sql = "DELETE FROM webhooks WHERE id = %s"
        params: list[Any] = [webhook_id]
        if organization_id is not None:
            sql += " AND organization_id = %s"
            params.append(organization_id)
        with connect() as c:
            cur = c.execute(sql, params)
            return cast(bool, cur.rowcount > 0)

    def update(
        self,
        webhook_id: int,
        *,
        name: str | None,
        url: str | None,
        event_types: list[str] | None,
        active: bool | None,
        formato: str | None = None,
        organization_id: int | None = None,
    ) -> bool:
        """Actualiza campos opcionales. Devuelve True si encontró el registro.

        ``organization_id`` acota **a qué fila** se aplica el update, no la
        cambia: un webhook no se muda de organización, se borra y se crea.
        """
        sets: list[str] = []
        params: list[Any] = []
        if name is not None:
            sets.append("name = %s")
            params.append(name)
        if url is not None:
            sets.append("url = %s")
            params.append(url)
        if event_types is not None:
            sets.append("event_types = %s")
            params.append(",".join(event_types))
        if active is not None:
            sets.append("active = %s")
            params.append(1 if active else 0)
        if formato is not None:
            sets.append("formato = %s")
            params.append(formato)
        if not sets:
            return True
        params.append(webhook_id)
        sql = "UPDATE webhooks SET " + ", ".join(sets) + " WHERE id = %s"
        if organization_id is not None:
            sql += " AND organization_id = %s"
            params.append(organization_id)
        with connect() as c:
            cur = c.execute(sql, tuple(params))
            return cast(bool, cur.rowcount > 0)

    def get_secret(self, webhook_id: int) -> str | None:
        """Get the effective signing secret for a webhook.

        For derived secrets, re-derives from the master key.
        For legacy secrets, returns the stored value.
        """
        with connect_read() as c:
            row = c.execute("SELECT secret FROM webhooks WHERE id = %s", (webhook_id,)).fetchone()
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
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (webhook_id, event_type, status_code, 1 if success else 0, payload_size, now),
                )
            except Exception:
                log.debug("webhook_delivery_insert_failed", webhook_id=webhook_id, exc_info=True)
            if success:
                c.execute(
                    "UPDATE webhooks SET last_triggered_at = %s, last_status = %s, failure_count = 0 WHERE id = %s",
                    (now, status_code, webhook_id),
                )
            else:
                c.execute(
                    "UPDATE webhooks SET last_triggered_at = %s, last_status = %s, "
                    "failure_count = failure_count + 1, "
                    "active = CASE WHEN failure_count + 1 >= 10 THEN 0 ELSE active END "
                    "WHERE id = %s",
                    (now, status_code, webhook_id),
                )

    def list_deliveries(self, webhook_id: int, limit: int = 50) -> list[dict[str, Any]]:
        with connect_read() as c:
            try:
                cur = c.execute(
                    "SELECT id, webhook_id, event_type, status_code, success, payload_size, created_at "
                    "FROM webhook_deliveries WHERE webhook_id = %s ORDER BY created_at DESC LIMIT %s",
                    (webhook_id, limit),
                )
                return rows_to_dicts(cur)
            except Exception:
                log.warning("webhook_deliveries_list_failed", exc_info=True)
                return []

    @staticmethod
    def _idempotency_is_expired(created_at: object, max_age_seconds: int) -> bool:
        """Return whether an idempotency reservation is no longer usable."""
        if max_age_seconds <= 0 or not isinstance(created_at, str):
            return True
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            return True
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        return (datetime.now(UTC) - created.astimezone(UTC)).total_seconds() > max_age_seconds

    def idempotency_reserve(
        self,
        key: str,
        endpoint: str,
        request_fingerprint: str,
        reservation_token: str,
        max_age_seconds: int,
    ) -> tuple[bool, dict[str, Any]]:
        """Atomically claim a scoped idempotency key.

        A pending reservation deliberately makes concurrent retries fail closed
        instead of creating a second webhook. The caller finalizes it only
        after the webhook has been created successfully.
        """
        import json

        pending = {
            "_pending": True,
            "_request_fingerprint": request_fingerprint,
            "_reservation_token": reservation_token,
        }
        with connect() as c:
            row = c.execute(
                "SELECT response_json, created_at FROM idempotency_keys WHERE idem_key = %s AND endpoint = %s",
                (key, endpoint),
            ).fetchone()
            if row is not None and self._idempotency_is_expired(row[1], max_age_seconds):
                c.execute(
                    "DELETE FROM idempotency_keys WHERE idem_key = %s AND endpoint = %s",
                    (key, endpoint),
                )
                row = None
            if row is None:
                inserted = c.execute(
                    "INSERT INTO idempotency_keys (idem_key, endpoint, response_json, created_at) "
                    "VALUES (%s, %s, %s, %s) ON CONFLICT(idem_key, endpoint) DO NOTHING",
                    (key, endpoint, json.dumps(pending, ensure_ascii=False), now_utc_iso()),
                )
                if inserted.rowcount > 0:
                    return True, pending
                # Otro proceso ganó la carrera entre nuestro SELECT e INSERT.
                # Releer la fila evita un 500 por violación de unicidad y deja
                # la petición concurrente en estado pendiente (fail closed).
                row = c.execute(
                    "SELECT response_json, created_at FROM idempotency_keys "
                    "WHERE idem_key = %s AND endpoint = %s",
                    (key, endpoint),
                ).fetchone()
                if row is None:
                    return False, {}
                try:
                    inserted_value = cast(dict[str, Any], json.loads(row[0]))
                except Exception:
                    log.warning("idempotency_inserted_value_unreadable", exc_info=True)
                    inserted_value = {}
                # Algunos adaptadores no informan rowcount de INSERT de forma
                # uniforme. El token aleatorio identifica inequívocamente
                # nuestra propia reserva también en ese caso.
                if inserted_value.get("_reservation_token") == reservation_token:
                    return True, pending
        try:
            return False, cast(dict[str, Any], json.loads(row[0]))
        except Exception:
            # A malformed legacy cache entry is not trusted and never returned.
            log.warning("idempotency_reserve_failed", exc_info=True)
            return False, {}

    def idempotency_finalize(
        self,
        key: str,
        endpoint: str,
        reservation_token: str,
        response: dict[str, Any],
    ) -> bool:
        """Replace our pending reservation with a secret-free response."""
        import json

        with connect() as c:
            row = c.execute(
                "SELECT response_json FROM idempotency_keys WHERE idem_key = %s AND endpoint = %s",
                (key, endpoint),
            ).fetchone()
            if row is None:
                return False
            try:
                pending = cast(dict[str, Any], json.loads(row[0]))
            except Exception:
                log.warning("idempotency_finalize_failed", exc_info=True)
                return False
            if pending.get("_reservation_token") != reservation_token:
                return False
            c.execute(
                "UPDATE idempotency_keys SET response_json = %s WHERE idem_key = %s AND endpoint = %s",
                (json.dumps(response, ensure_ascii=False), key, endpoint),
            )
        return True

    def idempotency_release(self, key: str, endpoint: str, reservation_token: str) -> None:
        """Release only our own pending reservation after a failed create."""
        import json

        with connect() as c:
            row = c.execute(
                "SELECT response_json FROM idempotency_keys WHERE idem_key = %s AND endpoint = %s",
                (key, endpoint),
            ).fetchone()
            if row is None:
                return
            try:
                pending = cast(dict[str, Any], json.loads(row[0]))
            except Exception:
                # Sin poder leer la reserva no se puede liberar: la key queda
                # ocupada hasta que expire, bloqueando reintentos legítimos.
                log.warning("idempotency_release_payload_ilegible", exc_info=True)
                return
            if pending.get("_pending") and pending.get("_reservation_token") == reservation_token:
                c.execute(
                    "DELETE FROM idempotency_keys WHERE idem_key = %s AND endpoint = %s",
                    (key, endpoint),
                )
