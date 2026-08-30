"""Job de alertas para las reglas de watchlist por criterio (mi-watchlist).

Para cada regla **activa** que este "due" segun su frecuencia
(``immediate``/``daily``/``weekly``), busca licitaciones nuevas (con
``fecha_publicacion`` posterior a ``last_notified_at``) que coincidan con sus
criterios y:

1. Escribe un registro en ``user_notifications`` (INSERT OR IGNORE) para la
   bandeja in-app del usuario.
2. Si la regla tiene ``email`` configurado, encola en ``pending_digests``
   para que ``send_pending_digests`` lo entregue por email.
3. Dispara el evento ``watchlist_rule.matched`` a los webhooks externos
   suscritos (best-effort, no bloquea si falla).

Ya NO llama a ``notify()`` global (que mandaba todo al ALERT_EMAIL_TO).
La entrega por email queda sujeta a la frecuencia de la regla; ``immediate``
se entregara en el proximo run del job de digests (~4h en GH Actions).

Espeja ``scheduler/watchlist_alerts.py`` (watchlist de empresas) pero sobre la
tabla ``watchlist_rules`` (RFC ux-mi-watchlist, increment 4).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from db.database import connect, connect_read
from observability import get_logger
from services.watchlist_rules import WatchlistRule, matches_since

log = get_logger(__name__)

# Ventana inicial cuando la regla nunca notifico.
_LOOKBACK_DAYS = 30
# Intervalo minimo entre alertas segun frecuencia (``immediate`` no espera).
_FREQ_INTERVAL = {"daily": timedelta(days=1), "weekly": timedelta(days=7)}

#: Días que la ventana de búsqueda retrocede sobre la última notificación.
#:
#: Dos, y no cero, porque ``fecha_publicacion`` es un día y la ventana avanza a
#: una hora: sin solape, lo ingerido después de la evaluación del día se perdía
#: para siempre. Y dos, y no diez, porque el solape solo es gratis mientras el
#: anti-join contra ``user_notifications`` pueda descartarlo con el índice
#: único; una ventana muy larga acabaría pagando el escaneo sin cubrir ningún
#: caso nuevo — la ingesta tardía real es de horas, no de días.
_VENTANA_GRACIA_DIAS = 2


def _load_active_rules() -> list[dict[str, Any]]:
    # Intentar con la columna email (v47). Fallback a query sin email en BDs legacy.
    try:
        with connect_read() as c:
            cur = c.execute(
                "SELECT id, user_key, nombre, keyword, cpv, min_importe, ccaa, "
                "frequency, active, last_notified_at, email, organization_id, visibility "
                "FROM watchlist_rules WHERE active = 1"
            )
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        return [dict(zip(cols, r, strict=False)) for r in rows]
    except Exception:
        with connect_read() as c:
            cur = c.execute(
                "SELECT id, user_key, nombre, keyword, cpv, min_importe, ccaa, "
                "frequency, active, last_notified_at "
                "FROM watchlist_rules WHERE active = 1"
            )
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        return [dict(zip(cols, r, strict=False)) for r in rows]


def _is_due(row: dict[str, Any], now: datetime) -> bool:
    """La regla debe evaluarse ya, segun su frecuencia y ultima notificacion?"""
    last = row.get("last_notified_at")
    if not last:
        return True
    freq = row.get("frequency") or "daily"
    if freq == "immediate":
        return True
    interval = _FREQ_INTERVAL.get(freq, _FREQ_INTERVAL["daily"])
    try:
        last_dt = datetime.fromisoformat(str(last))
    except ValueError:
        return True
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=UTC)
    return (now - last_dt) >= interval


def _since_date(row: dict[str, Any], default_since: str) -> str:
    """Fecha desde la que buscar matches: la última notificación menos la gracia.

    El corte no puede ser la fecha exacta de la última notificación. ``since``
    se compara contra ``fecha_publicacion``, que tiene granularidad de día,
    mientras que la ventana avanza a la hora en que corre el job: un expediente
    publicado el día D pero ingerido después de la evaluación de ese día caía
    fuera de la ventana siguiente y no volvía a entrar nunca.

    Restar :data:`_VENTANA_GRACIA_DIAS` hace que la ventana **se solape a
    propósito**. Volver a mirar dos días no cuesta nada —el anti-join de
    ``matches_since`` descarta lo ya notificado antes de gastar el ``LIMIT``— y
    a cambio cubre tanto la ingesta tardía del mismo día como la de la víspera,
    que es la que producen los conectores que corren después del carril diario.
    """
    last = row.get("last_notified_at")
    if not last:
        return default_since
    try:
        ultimo = datetime.fromisoformat(str(last))
    except (ValueError, TypeError):
        # Marca ilegible: se cae al lookback largo en vez de inventar un corte.
        # Con el anti-join, mirar de más es barato; mirar de menos pierde avisos.
        return default_since
    if ultimo.tzinfo is None:
        ultimo = ultimo.replace(tzinfo=UTC)
    return (ultimo - timedelta(days=_VENTANA_GRACIA_DIAS)).date().isoformat()


def _row_to_rule(row: dict[str, Any]) -> WatchlistRule:
    return WatchlistRule(
        id=row.get("id"),
        nombre=row.get("nombre"),
        keyword=row.get("keyword"),
        cpv=row.get("cpv"),
        min_importe=row.get("min_importe"),
        ccaa=row.get("ccaa"),
        frequency=row.get("frequency") or "daily",
        active=True,
        organization_id=row.get("organization_id"),
        visibility=row.get("visibility") or "private",
    )


def _update_last_notified(rule_id: int, ts: str) -> None:
    with connect() as c:
        c.execute(
            "UPDATE watchlist_rules SET last_notified_at = %s WHERE id = %s",
            (ts, rule_id),
        )


def _build_title(rule: WatchlistRule, n: int) -> str:
    """Titulo corto para la notificacion in-app."""
    nombre = rule.nombre or rule.keyword or (f"CPV {rule.cpv}" if rule.cpv else None) or "tu regla"
    return f"{n} licitacion(es) nueva(s) para «{nombre}»"


def _build_body(rule: WatchlistRule, matches: list[dict[str, Any]]) -> str:
    """Texto del cuerpo para email / in-app."""
    crit: list[str] = []
    if rule.keyword:
        crit.append(f"keyword: {rule.keyword}")
    if rule.cpv:
        crit.append(f"CPV: {rule.cpv}")
    if rule.min_importe:
        crit.append(f"importe >= {rule.min_importe:,.0f} EUR")
    if rule.ccaa:
        crit.append(f"CCAA: {rule.ccaa}")
    header = rule.nombre or " | ".join(crit) or "tu regla"
    lines = [f"{len(matches)} licitacion(es) nueva(s) para <<{header}>>:\n"]
    for lic in matches[:10]:
        importe = f"{lic['importe']:,.0f} EUR" if lic.get("importe") else "---"
        url = lic.get("url") or ""
        lines.append(
            f"  * [{lic.get('fecha_publicacion', '?')}] {lic.get('titulo', '?')} | {importe}\n"
            f"    {url}"
        )
    if len(matches) > 10:
        lines.append(f"  ... y {len(matches) - 10} mas.")
    return "\n".join(lines)


def _write_user_notifications(
    user_key: str,
    rule_id: int,
    matches: list[dict[str, Any]],
    rule: WatchlistRule,
    now_ts: str,
) -> int:
    """Escribe notificaciones in-app con INSERT OR IGNORE (idempotente).

    Tolerante a la ausencia de la tabla (BDs sin migracion v48).
    Returns: numero de filas insertadas (las que no eran duplicados).
    """
    inserted = 0
    title = _build_title(rule, len(matches))
    try:
        with connect() as c:
            for lic in matches:
                lic_id = str(lic.get("id_externo") or "")
                if not lic_id:
                    continue
                body = f"{lic.get('titulo', '?')} | {lic.get('organo_contratacion', '?')}"
                cur = c.execute(
                    "INSERT INTO user_notifications "
                    "(user_key, created_at, type, title, body, licitacion_id, rule_id, "
                    " organization_id) "
                    "VALUES (%s, %s, 'rule_match', %s, %s, %s, %s, %s) "
                    "ON CONFLICT(user_key, licitacion_id, type) DO NOTHING",
                    (
                        user_key,
                        now_ts,
                        title,
                        body,
                        lic_id,
                        rule_id,
                        rule.organization_id,
                    ),
                )
                inserted += cur.rowcount
    except Exception as exc:
        # Si la tabla no existe (BD legacy sin migrar), continuar sin crash
        log.debug("user_notifications_write_skip", error=str(exc)[:100])
    return inserted


def _enqueue_pending_digest(
    user_key: str,
    email: str,
    rule_id: int,
    matches: list[dict[str, Any]],
    frequency: str,
    rule: WatchlistRule,
    now_ts: str,
) -> None:
    """Encola matches en pending_digests para entrega por email."""
    from services.watchlist import store_pending_digest

    for lic in matches:
        lic_id = str(lic.get("id_externo") or "")
        if not lic_id:
            continue
        store_pending_digest(user_key, email, rule_id, lic_id, frequency, now_ts)


def check_rules_and_notify(*, limit_per_rule: int = 50) -> int:
    """Evalua las reglas activas "due" y persiste alertas de matches nuevos.

    - Escribe en ``user_notifications`` (in-app) para todos los matches.
    - Si la regla tiene email, encola en ``pending_digests``.

    Returns:
        Numero de reglas que dispararon al menos una notificacion.
    """
    now = datetime.now(UTC)
    now_ts = now.isoformat()
    default_since = (now - timedelta(days=_LOOKBACK_DAYS)).date().isoformat()

    rules = _load_active_rules()
    if not rules:
        log.debug("watchlist_rules_empty")
        return 0

    alerted = 0
    for row in rules:
        if not _is_due(row, now):
            continue
        rule = _row_to_rule(row)
        user_key = str(row["user_key"])
        new_matches = matches_since(
            rule,
            _since_date(row, default_since),
            limit=limit_per_rule,
            user_key=user_key,
        )
        if len(new_matches) >= limit_per_rule:
            # La página se llenó: hay más matches de los que caben en una
            # evaluación. No se pierden —el anti-join hace que la siguiente
            # empiece por los que quedaron— pero conviene que se vea, porque
            # una regla que satura el tope cada día es una regla mal acotada.
            log.warning(
                "watchlist_rule_matches_truncados",
                rule_id=int(row["id"]),
                limit=limit_per_rule,
            )
        # Mover la ventana siempre (haya o no matches) para no re-escanear. Es
        # seguro justo porque el corte ya no es lo que decide qué es nuevo: la
        # ventana se solapa y la deduplicación la hace el anti-join.
        _update_last_notified(int(row["id"]), now_ts)
        if not new_matches:
            continue

        rule_id = int(row["id"])
        email = row.get("email")

        # 1. Notificaciones in-app (siempre)
        written = _write_user_notifications(user_key, rule_id, new_matches, rule, now_ts)

        # 2. Email via pending_digests (solo si hay email configurado)
        if email:
            _enqueue_pending_digest(
                user_key,
                email,
                rule_id,
                new_matches,
                row.get("frequency") or "daily",
                rule,
                now_ts,
            )

        log.info(
            "watchlist_rule_alert",
            rule_id=rule_id,
            total=len(new_matches),
            in_app=written,
            has_email=bool(email),
        )

        # B5: dispara webhook a suscriptores externos (best-effort, no bloquea).
        try:
            from db.webhooks import trigger_event

            trigger_event(
                "watchlist_rule.matched",
                {
                    "rule_id": rule_id,
                    "user_key": user_key,
                    "nombre": rule.nombre,
                    "keyword": rule.keyword,
                    "cpv": rule.cpv,
                    "total_matches": len(new_matches),
                    "licitaciones": [lic.get("id_externo") for lic in new_matches],
                },
            )
        except Exception:
            log.warning("webhook_trigger_failed", exc_info=True)

        alerted += 1

    return alerted
