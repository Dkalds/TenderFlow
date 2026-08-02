"""Event sourcing ligero — append-only log de eventos de dominio.

La tabla ``domain_events`` (ya en SCHEMA) almacena eventos inmutables:

    domain_events(id, event_type, aggregate_id, aggregate_type,
                  payload_json, actor_id, created_at)

Uso:
    from db.events import append_event, get_events

    append_event("watchlist.item_added", user_id, "user",
                 {"id_externo": "PRO/2024/123"}, actor_id=user_id)

    events = get_events("user", user_id)

Replay helpers:
    replay_watchlist(user_id)  → estado actual reconstruido desde eventos
    replay_feedback()          → lista de feedback desde eventos
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from db.database import connect, connect_read, now_utc_iso
from observability.logging import get_logger

log = get_logger(__name__)

_CACHE_INVALIDATION_EVENT = "cache.invalidated"
_CACHE_INVALIDATION_AGGREGATE_ID = "global"
_CACHE_INVALIDATION_AGGREGATE_TYPE = "cache"


def append_event(
    event_type: str,
    aggregate_id: str | int,
    aggregate_type: str,
    payload: dict[str, Any],
    *,
    actor_id: int | None = None,
) -> int:
    """Añade un evento al log. Devuelve el ID del evento creado.

    ``actor_id`` es el id numérico del usuario que origina el evento:
    ``domain_events.actor_id`` es ``INTEGER`` tanto en el schema SQLite
    (``db/schema.py``) como en Postgres. Antes se insertaba
    ``str(actor_id)``, lo que SQLite acepta por afinidad de tipos pero
    Postgres rechaza con ``InvalidTextRepresentation`` en cuanto el valor no
    es numérico. Detectado al correr la suite contra el motor real (ADR-018).
    """
    payload_json = json.dumps(payload, ensure_ascii=False, default=str)
    with connect() as c:
        cur = c.execute(
            "INSERT INTO domain_events "
            "(event_type, aggregate_id, aggregate_type, payload_json, actor_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                event_type,
                str(aggregate_id),
                aggregate_type,
                payload_json,
                int(actor_id) if actor_id is not None else None,
                now_utc_iso(),
            ),
        )
        event_id: int = cur.lastrowid or 0
    log.debug("event_appended", event_type=event_type, aggregate_id=aggregate_id, event_id=event_id)
    return event_id


def get_events(
    aggregate_type: str,
    aggregate_id: str | int,
    *,
    event_type: str | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Devuelve todos los eventos de un agregado, ordenados por created_at."""
    params: list[Any] = [aggregate_type, str(aggregate_id)]
    extra = ""
    if event_type:
        extra = " AND event_type=?"
        params.append(event_type)
    params.append(limit)
    with connect() as c:
        cur = c.execute(
            f"SELECT id, event_type, aggregate_id, aggregate_type, payload_json, actor_id, created_at "
            f"FROM domain_events "
            f"WHERE aggregate_type=? AND aggregate_id=?{extra} "
            f"ORDER BY created_at, id LIMIT ?",
            params,
        )
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    events = []
    for row in rows:
        ev = dict(zip(cols, row, strict=False))
        ev["payload"] = json.loads(ev.pop("payload_json", "{}") or "{}")
        events.append(ev)
    return events


def get_events_by_type(
    event_type: str,
    *,
    since: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Devuelve eventos de un tipo concreto, opcionalmente desde una fecha ISO."""
    params: list[Any] = [event_type]
    extra = ""
    if since:
        extra = " AND created_at >= ?"
        params.append(since)
    params.append(limit)
    with connect() as c:
        cur = c.execute(
            f"SELECT id, event_type, aggregate_id, aggregate_type, payload_json, actor_id, created_at "
            f"FROM domain_events "
            f"WHERE event_type=?{extra} "
            f"ORDER BY created_at, id LIMIT ?",
            params,
        )
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    events = []
    for row in rows:
        ev = dict(zip(cols, row, strict=False))
        ev["payload"] = json.loads(ev.pop("payload_json", "{}") or "{}")
        events.append(ev)
    return events


def append_cache_invalidation_event() -> int:
    """Persiste una señal global de invalidación visible entre procesos.

    El scraper de GitHub Actions y el API de Render no comparten filesystem,
    pero sí la base Postgres. El event log append-only ya existente permite
    transportar la señal sin añadir schema ni infraestructura nueva.
    """
    return append_event(
        _CACHE_INVALIDATION_EVENT,
        _CACHE_INVALIDATION_AGGREGATE_ID,
        _CACHE_INVALIDATION_AGGREGATE_TYPE,
        {},
    )


def get_latest_cache_invalidation_timestamp() -> float:
    """Devuelve el instante de la última invalidación global, o ``0.0``."""
    with connect_read() as c:
        row = c.execute(
            "SELECT created_at FROM domain_events "
            "WHERE event_type = ? AND aggregate_type = ? AND aggregate_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (
                _CACHE_INVALIDATION_EVENT,
                _CACHE_INVALIDATION_AGGREGATE_TYPE,
                _CACHE_INVALIDATION_AGGREGATE_ID,
            ),
        ).fetchone()
    if row is None or row[0] is None:
        return 0.0
    try:
        parsed = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
    except ValueError:
        log.warning("cache_invalidation_timestamp_invalid", value=str(row[0]))
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


# ── Replay helpers ─────────────────────────────────────────────────────────────


def replay_watchlist(user_id: int | str) -> list[dict[str, Any]]:
    """Reconstruye el estado de la watchlist de un usuario reproduciendo sus eventos.

    Eventos soportados:
    - ``watchlist.item_added``   → añade item al estado
    - ``watchlist.item_removed`` → elimina item del estado

    Devuelve lista de items activos (en el mismo orden en que se añadieron).
    """
    events = get_events("user", user_id)
    state: dict[str, dict[str, Any]] = {}  # id_externo → item

    for ev in events:
        if ev["event_type"] == "watchlist.item_added":
            key = ev["payload"].get("id_externo") or ev["payload"].get("rule_id") or str(ev["id"])
            state[key] = ev["payload"]
        elif ev["event_type"] == "watchlist.item_removed":
            key = ev["payload"].get("id_externo") or ev["payload"].get("rule_id")
            if key:
                state.pop(key, None)

    return list(state.values())


def replay_feedback() -> list[dict[str, Any]]:
    """Devuelve el feedback efectivo reconstruido desde eventos (el último por expediente)."""
    events = get_events_by_type("feedback.submitted")
    # Last-write-wins per expediente
    by_expediente: dict[str, dict[str, Any]] = {}
    for ev in events:
        exp = ev["payload"].get("expediente")
        if exp:
            by_expediente[exp] = {
                "expediente": exp,
                "relevante": ev["payload"].get("relevante"),
                "nota": ev["payload"].get("nota", ""),
                "submitted_at": ev["created_at"],
                "actor_id": ev["actor_id"],
            }
    return list(by_expediente.values())
