"""Almacén genérico de idempotencia sobre ``idempotency_keys`` (C8.4).

La tabla existe desde ``v51`` y la usaban dos sitios con su propia copia del
mismo SQL (``db/repositories/feedback.py`` y ``db/repositories/webhooks.py``).
Ninguna de las dos copias miraba el TTL: una clave de hace un año seguía
devolviendo su respuesta cacheada, así que ``IDEMPOTENCY_TTL_SECONDS`` era una
variable que nadie leía y la retención de la tabla no significaba nada para el
comportamiento.

Este módulo es el estrato único que ese SQL debía tener (ADR-022) y el que
consumen las escrituras de usuario de C8.4: favoritos, reglas, empresas
vigiladas y descartes.

**Qué garantiza y qué no.** Garantiza que un reintento con la misma clave
devuelve la misma respuesta mientras la clave no caduque. No garantiza
exclusión mutua entre dos peticiones concurrentes con la misma clave: las dos
pueden ejecutar el efecto antes de que ninguna haya escrito la marca. Para las
escrituras de C8.4 eso es aceptable porque todas son idempotentes por
naturaleza (añadir dos veces el mismo favorito deja un favorito), y decirlo
aquí es preferible a prometer una exclusión que este diseño no da.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from config.settings import settings
from db.database import connect, connect_read, now_utc_iso
from observability.logging import get_logger

log = get_logger(__name__)

#: Tope de longitud de la clave, alineado con el `max_length` de la cabecera.
MAX_KEY_LENGTH = 200


def _caducada(created_at: str | None) -> bool:
    """¿La marca es más vieja que ``IDEMPOTENCY_TTL_SECONDS``?

    Una fila sin fecha legible se trata como caducada: reprocesar es el
    comportamiento seguro, y servir una respuesta cuya antigüedad no se puede
    determinar no lo es.
    """
    if not created_at:
        return True
    try:
        marca = datetime.fromisoformat(str(created_at))
    except ValueError:
        log.warning("idempotency_created_at_ilegible", created_at=str(created_at)[:40])
        return True
    if marca.tzinfo is None:
        marca = marca.replace(tzinfo=UTC)
    return datetime.now(UTC) - marca > timedelta(seconds=settings.IDEMPOTENCY_TTL_SECONDS)


def scope(nombre: str, *, user_key: str, organization_id: int | None = None) -> str:
    """Ámbito de una clave de idempotencia: nunca es solo el nombre del endpoint.

    La clave la elige el cliente, así que dos usuarios pueden mandar la misma.
    Si el ámbito fuera solo `"watchlist_items"`, el segundo recibiría la
    respuesta del primero — una fuga de datos entre cuentas a través de un
    mecanismo que existe para evitar duplicados. Por eso el ámbito lleva
    siempre la identidad de quien escribe, y la organización cuando la hay.
    """
    partes = [nombre, user_key]
    if organization_id is not None:
        partes.append(str(organization_id))
    return ":".join(partes)


def cached_response(key: str | None, endpoint: str) -> dict[str, Any] | None:
    """Respuesta guardada para *key* en *endpoint*, si existe y no caducó."""
    if not key:
        return None
    with connect_read() as c:
        row = c.execute(
            "SELECT response_json, created_at FROM idempotency_keys "
            "WHERE idem_key = %s AND endpoint = %s",
            (key[:MAX_KEY_LENGTH], endpoint),
        ).fetchone()
    if not row:
        return None
    if _caducada(row[1]):
        return None
    try:
        cargado = json.loads(row[0])
    except (TypeError, ValueError):
        # Un JSON corrupto se presenta como "no hay clave" y la petición se
        # reprocesa. Es la única salida que no devuelve basura al cliente.
        log.warning("idempotency_payload_corrupto", endpoint=endpoint)
        return None
    return cargado if isinstance(cargado, dict) else None


def store_response(key: str | None, endpoint: str, response: dict[str, Any]) -> None:
    """Guarda la respuesta de *key* en *endpoint*. Sin clave, no hace nada."""
    if not key:
        return
    with connect() as c:
        c.execute(
            "INSERT INTO idempotency_keys "
            "(idem_key, endpoint, response_json, created_at) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT(idem_key, endpoint) DO NOTHING",
            (
                key[:MAX_KEY_LENGTH],
                endpoint,
                json.dumps(response, ensure_ascii=False),
                now_utc_iso(),
            ),
        )
