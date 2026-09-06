"""Event sourcing ligero — append-only log de eventos de dominio, y **outbox**.

La tabla ``domain_events`` almacena eventos inmutables::

    domain_events(id, event_type, aggregate_id, aggregate_type,
                  payload_json, actor_id, created_at,
                  organization_id, dispatched_at)      -- v107

Desde el plan 2026-09 v2 (S4.1) esta tabla es además el **outbox** del
producto: una mutación relevante escribe su evento en la misma transacción que
el cambio, y un despachador (``scheduler/jobs/event_dispatch.py``) lo abanica
después hacia ``user_notifications``, ``pending_digests``,
``webhook_deliveries`` y la señal de caché. Antes cada productor escribía
directamente en el almacén de salida que le convenía, así que añadir un canal
obligaba a tocar todos los productores y una entrega fallida no dejaba rastro
de qué la había originado.

Dos entradas, y la diferencia importa:

- :func:`append_domain_event` **valida contra el catálogo** de
  ``shared/events.py`` y es la que usan los productores nuevos. Un tipo mal
  escrito falla donde se escribe, no seis horas después en el despachador.
- :func:`append_event` no valida. Es la puerta histórica y la siguen usando la
  señal de caché y ``services/tech_signal.py``, además de los tests que
  ejercen el log genérico con tipos inventados. Convertirla en estricta habría
  significado meter en el catálogo nombres que no son eventos de producto.

Idempotencia del abanico: ``domain_event_dispatches`` lleva un único por
``(event_id, canal)``. El despachador reclama el par antes de entregar, así
que una interrupción a mitad no duplica entregas al reintentar.

Uso:
    from db.events import append_domain_event, get_events

    append_domain_event(
        "pursuit.created", pursuit_id, "pursuit",
        {"pursuit_id": 1, "licitacion_id": "X", "organization_id": 7},
        organization_id=7, actor_id=user_id, conn=c,
    )

Replay helpers:
    replay_watchlist(user_id)  → estado actual reconstruido desde eventos
    replay_feedback()          → lista de feedback desde eventos
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

from db.database import connect, connect_read, now_utc_iso
from observability.logging import get_logger
from shared.events import Canal, validar_payload, validar_tipo

log = get_logger(__name__)

_CACHE_INVALIDATION_EVENT = "cache.invalidated"
_CACHE_INVALIDATION_AGGREGATE_ID = "global"
_CACHE_INVALIDATION_AGGREGATE_TYPE = "cache"

#: Techo de la alerta de ``domain_events_pending``. El plan pide avisar si la
#: cola supera 1.000 durante una hora; la ventana la impone la regla de
#: Prometheus, este número es el umbral que comparte con ella.
UMBRAL_PENDIENTES_ALERTA = 1000

#: TTL del muestreo de la cola para ``/metrics``. Prometheus raspa cada pocos
#: segundos y el conteo es una lectura a BD: sin memoización, el endpoint de
#: métricas abriría una conexión por scrape para un número que cambia lento.
_TTL_MUESTREO_PENDIENTES_S = 20.0

_pendientes_cache: tuple[float, int] = (0.0, 0)
_metrica_pendientes_registrada = False


_INSERT_EVENTO = (
    "INSERT INTO domain_events "
    "(event_type, aggregate_id, aggregate_type, payload_json, actor_id, created_at, "
    " organization_id) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id"
)


def append_event(
    event_type: str,
    aggregate_id: str | int,
    aggregate_type: str,
    payload: dict[str, Any],
    *,
    actor_id: int | None = None,
    organization_id: int | None = None,
    conn: Any | None = None,
) -> int:
    """Añade un evento al log. Devuelve el ID del evento creado.

    **No valida el tipo**: es la puerta histórica y la usan la señal de caché
    (``cache.invalidated``) y ``services/tech_signal.py`` con nombres que no
    son eventos de producto. Para todo lo que el despachador tiene que
    repartir, la puerta es :func:`append_domain_event`, que sí valida.

    ``conn`` permite escribir el evento **en la transacción de quien llama**,
    que es lo que convierte esta tabla en un outbox: si la mutación se revierte,
    su evento se va con ella y nadie entrega un aviso de algo que no pasó. Sin
    ``conn`` abre su propia transacción, como siempre.

    ``actor_id`` es el id numérico del usuario que origina el evento:
    ``domain_events.actor_id`` es ``INTEGER`` en Postgres. Antes se insertaba
    ``str(actor_id)``, lo que SQLite aceptaba por afinidad de tipos pero
    Postgres rechaza con ``InvalidTextRepresentation`` en cuanto el valor no
    es numérico. Detectado al correr la suite contra el motor real (ADR-018).
    """
    payload_json = json.dumps(payload, ensure_ascii=False, default=str)
    params = (
        event_type,
        str(aggregate_id),
        aggregate_type,
        payload_json,
        int(actor_id) if actor_id is not None else None,
        now_utc_iso(),
        int(organization_id) if organization_id is not None else None,
    )
    if conn is not None:
        row = conn.execute(_INSERT_EVENTO, params).fetchone()
        event_id: int = int(row[0]) if row else 0
    else:
        with connect() as c:
            row = c.execute(_INSERT_EVENTO, params).fetchone()
            event_id = int(row[0]) if row else 0
    log.debug("event_appended", event_type=event_type, aggregate_id=aggregate_id, event_id=event_id)
    return event_id


def append_domain_event(
    event_type: str,
    aggregate_id: str | int,
    aggregate_type: str,
    payload: dict[str, Any],
    *,
    organization_id: int | None = None,
    actor_id: int | None = None,
    conn: Any | None = None,
) -> int:
    """Escribe un evento **del catálogo** en el outbox. Devuelve su id.

    Valida tipo y campos obligatorios contra ``shared/events.py`` antes de
    tocar la base: un evento con el nombre mal escrito, o sin los datos que su
    plantilla y su notificación necesitan, no puede llegar a la tabla.

    Raises:
        TipoDeEventoDesconocido: el tipo no está en el catálogo.
        PayloadIncompleto: faltan campos obligatorios del tipo.
    """
    validar_tipo(event_type)
    validar_payload(event_type, payload)
    return append_event(
        event_type,
        aggregate_id,
        aggregate_type,
        payload,
        actor_id=actor_id,
        organization_id=organization_id,
        conn=conn,
    )


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
        extra = " AND event_type=%s"
        params.append(event_type)
    params.append(limit)
    with connect() as c:
        cur = c.execute(
            f"SELECT id, event_type, aggregate_id, aggregate_type, payload_json, actor_id, created_at "
            f"FROM domain_events "
            f"WHERE aggregate_type=%s AND aggregate_id=%s{extra} "
            f"ORDER BY created_at, id LIMIT %s",
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
        extra = " AND created_at >= %s"
        params.append(since)
    params.append(limit)
    with connect() as c:
        cur = c.execute(
            f"SELECT id, event_type, aggregate_id, aggregate_type, payload_json, actor_id, created_at "
            f"FROM domain_events "
            f"WHERE event_type=%s{extra} "
            f"ORDER BY created_at, id LIMIT %s",
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


# ── Outbox: cola pendiente, reclamo por canal y métrica ──────────────────────


def pending_events(limit: int = 200) -> list[dict[str, Any]]:
    """Eventos aún sin despachar, del más antiguo al más nuevo.

    El orden es por ``id`` y no por ``created_at``: ``created_at`` es TEXT ISO
    y dos eventos escritos en el mismo milisegundo empatarían, mientras que la
    secuencia de la tabla es total. Con un empate, el despachador podría
    procesar dos veces la misma frontera al reanudar.
    """
    with connect_read() as c:
        cur = c.execute(
            "SELECT id, event_type, aggregate_id, aggregate_type, payload_json, "
            "       actor_id, created_at, organization_id "
            "FROM domain_events WHERE dispatched_at IS NULL ORDER BY id LIMIT %s",
            (limit,),
        )
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    eventos: list[dict[str, Any]] = []
    for row in rows:
        ev = dict(zip(cols, row, strict=False))
        try:
            ev["payload"] = json.loads(ev.pop("payload_json", "{}") or "{}")
        except (TypeError, ValueError):
            # Un payload ilegible no puede parar la cola entera: el evento se
            # despacha con payload vacío y queda el aviso para investigarlo.
            log.warning("domain_event_payload_ilegible", event_id=ev.get("id"))
            ev["payload"] = {}
        eventos.append(ev)
    return eventos


def claim_channel(event_id: int, canal: Canal) -> bool:
    """Reclama ``(event_id, canal)`` para este intento de entrega.

    Devuelve ``True`` solo si la reserva es nuestra. El único de
    ``domain_event_dispatches`` (revisión ``v107``) es lo que hace idempotente
    el abanico: un despachador interrumpido a mitad reintenta el evento entero
    y los canales ya entregados no vuelven a salir.
    """
    with connect() as c:
        cur = c.execute(
            "INSERT INTO domain_event_dispatches (event_id, canal, created_at) "
            "VALUES (%s, %s, %s) ON CONFLICT (event_id, canal) DO NOTHING",
            (event_id, canal, now_utc_iso()),
        )
        return bool(cur.rowcount > 0)


def release_channel(event_id: int, canal: Canal) -> None:
    """Libera un reclamo cuyo canal falló, para que el reintento lo repita.

    Sin esto, un webhook caído consumiría su reserva en el primer intento y la
    entrega no se volvería a intentar jamás: la idempotencia se convertiría en
    pérdida de mensajes.
    """
    with connect() as c:
        c.execute(
            "DELETE FROM domain_event_dispatches WHERE event_id = %s AND canal = %s",
            (event_id, canal),
        )


def mark_dispatched(event_id: int) -> None:
    """Marca el evento como despachado (todos sus canales resueltos)."""
    with connect() as c:
        c.execute(
            "UPDATE domain_events SET dispatched_at = %s WHERE id = %s AND dispatched_at IS NULL",
            (now_utc_iso(), event_id),
        )


def count_pending_events() -> int:
    """Cuántos eventos esperan despacho. Alimenta ``domain_events_pending``."""
    with connect_read() as c:
        row = c.execute("SELECT COUNT(*) FROM domain_events WHERE dispatched_at IS NULL").fetchone()
    return int(row[0]) if row else 0


def _pendientes_muestreados() -> int:
    """Conteo de la cola con TTL, para no pegarle a la BD en cada scrape."""
    global _pendientes_cache

    ahora = time.monotonic()
    sellado, valor = _pendientes_cache
    if ahora - sellado < _TTL_MUESTREO_PENDIENTES_S:
        return valor
    medido = count_pending_events()
    _pendientes_cache = (ahora, medido)
    return medido


def registrar_metrica_pendientes() -> None:
    """Publica ``domain_events_pending`` en el registro por defecto. Idempotente.

    Es un colector y no una gauge que alguien tenga que refrescar: la cola la
    llena la API y la vacía el scheduler, así que no hay un punto del proceso
    web donde «actualizar el número» tenga sentido. Se muestrea al servir
    ``/metrics``, con el TTL de :data:`_TTL_MUESTREO_PENDIENTES_S`.

    Best-effort de principio a fin: sin ``prometheus_client``, o si el registro
    ya lo tiene, no hace nada. La instrumentación nunca puede impedir que el
    proceso arranque.
    """
    global _metrica_pendientes_registrada

    if _metrica_pendientes_registrada:
        return
    try:
        from prometheus_client import REGISTRY
        from prometheus_client.core import GaugeMetricFamily
        from prometheus_client.registry import Collector
    except Exception:  # pragma: no cover - entorno sin prometheus_client
        log.debug("domain_events_pending_sin_prometheus")
        return

    class _ColectorPendientes(Collector):
        def collect(self) -> Any:
            gauge = GaugeMetricFamily(
                "domain_events_pending",
                "Eventos de dominio pendientes de despacho (outbox)",
            )
            try:
                gauge.add_metric([], float(_pendientes_muestreados()))
            except Exception:
                # Un /metrics que devuelve 500 deja ciego al scrape entero.
                log.debug("domain_events_pending_no_disponible", exc_info=True)
                return
            yield gauge

    try:
        REGISTRY.register(_ColectorPendientes())
    except Exception:  # pragma: no cover - doble registro en recargas
        log.debug("domain_events_pending_ya_registrado", exc_info=True)
    _metrica_pendientes_registrada = True


def seguidores_de_licitacion(id_externo: str) -> list[dict[str, Any]]:
    """Quién sigue un expediente: favoritos y oportunidades abiertas.

    Devuelve filas ``{user_key, organization_id, user_id}``. ``user_key`` viene
    resuelto en el caso de los favoritos (``watchlist_items`` ya lo guarda) y
    llega ``None`` en el de las oportunidades, donde lo que hay es un id de
    usuario: traducirlo exige el email, y eso es trabajo del productor, no de
    esta consulta.

    Vive en este módulo —y no en un repositorio de watchlist— porque su único
    consumidor es el productor del outbox: es «a quién va este evento», la
    pregunta que el despachador contesta con ``payload["seguidores"]``. El SQL
    está en ``db/`` como manda ADR-022.

    Una oportunidad **terminal** (ganada, perdida o retirada) no cuenta: su
    expediente ya no se sigue, y avisar de que cambió el plazo de algo que se
    perdió hace un mes es ruido.
    """
    with connect_read() as c:
        cur = c.execute(
            "SELECT w.user_key, w.organization_id, NULL::int AS user_id "
            "  FROM watchlist_items w WHERE w.id_externo = %s "
            "UNION "
            "SELECT NULL, p.organization_id, p.responsible_user_id "
            "  FROM pursuits p "
            " WHERE p.licitacion_id = %s "
            "   AND p.status NOT IN ('won', 'lost', 'withdrawn') "
            "   AND p.responsible_user_id IS NOT NULL",
            (id_externo, id_externo),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


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
            "WHERE event_type = %s AND aggregate_type = %s AND aggregate_id = %s "
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
