"""Job de alertas para las reglas de watchlist por criterio (mi-watchlist).

Para cada regla **activa** que esté "due" según su frecuencia
(``immediate``/``daily``/``weekly``), busca licitaciones nuevas (con
``fecha_publicacion`` posterior a ``last_notified_at``) que coincidan con sus
criterios y emite una alerta (``notify`` → email/log), actualizando
``last_notified_at``.

Espeja ``scheduler/watchlist_alerts.py`` (watchlist de empresas) pero sobre la tabla
``watchlist_rules`` (RFC ux-mi-watchlist, increment 4). Itera sobre los ``user_key``
distintos presentes en la tabla, así que funciona sin depender de cómo se derive el
``user_key`` (la API lo deriva del auth ctx; aquí no hay request).

Pensado para correr tras el pipeline de ingesta, en el mismo punto que
``watchlist_alerts.check_and_notify`` (ver ``scheduler/pipeline_runs.py``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from db.database import connect
from observability import AlertLevel, get_logger, notify
from services.watchlist_rules import WatchlistRule, matches_since

log = get_logger(__name__)

# Ventana inicial cuando la regla nunca notificó.
_LOOKBACK_DAYS = 30
# Intervalo mínimo entre alertas según frecuencia (``immediate`` no espera).
_FREQ_INTERVAL = {"daily": timedelta(days=1), "weekly": timedelta(days=7)}


def _load_active_rules() -> list[dict[str, Any]]:
    with connect() as c:
        cur = c.execute(
            "SELECT id, user_key, nombre, keyword, cpv, min_importe, ccaa, "
            "frequency, active, last_notified_at FROM watchlist_rules WHERE active = 1"
        )
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    return [dict(zip(cols, r, strict=False)) for r in rows]


def _is_due(row: dict[str, Any], now: datetime) -> bool:
    """¿La regla debe evaluarse ya, según su frecuencia y última notificación?"""
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
    """Fecha desde la que buscar matches: la última notificación o el lookback."""
    last = row.get("last_notified_at")
    return str(last)[:10] if last else default_since


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
    )


def _update_last_notified(rule_id: int, ts: str) -> None:
    with connect() as c:
        c.execute(
            "UPDATE watchlist_rules SET last_notified_at = ? WHERE id = ?",
            (ts, rule_id),
        )


def _build_body(rule: WatchlistRule, matches: list[dict[str, Any]]) -> str:
    crit: list[str] = []
    if rule.keyword:
        crit.append(f"keyword: {rule.keyword}")
    if rule.cpv:
        crit.append(f"CPV: {rule.cpv}")
    if rule.min_importe:
        crit.append(f"importe ≥ {rule.min_importe:,.0f} €")
    if rule.ccaa:
        crit.append(f"CCAA: {rule.ccaa}")
    header = rule.nombre or " | ".join(crit) or "tu regla"
    lines = [f"{len(matches)} licitación(es) nueva(s) para «{header}»:\n"]
    for lic in matches[:10]:
        importe = f"{lic['importe']:,.0f} €" if lic.get("importe") else "—"
        url = lic.get("url") or ""
        lines.append(
            f"  • [{lic.get('fecha_publicacion', '?')}] {lic.get('titulo', '?')} | {importe}\n"
            f"    {url}"
        )
    if len(matches) > 10:
        lines.append(f"  … y {len(matches) - 10} más.")
    return "\n".join(lines)


def check_rules_and_notify(*, limit_per_rule: int = 50) -> int:
    """Evalúa las reglas activas "due" y emite alertas de matches nuevos.

    Returns:
        Número de reglas que dispararon alerta.
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
        new_matches = matches_since(rule, _since_date(row, default_since), limit=limit_per_rule)
        # Mover la ventana siempre (haya o no matches) para no re-escanear.
        _update_last_notified(int(row["id"]), now_ts)
        if not new_matches:
            continue
        notify(
            AlertLevel.INFO,
            f"Watchlist: {len(new_matches)} licitación(es) nueva(s)",
            _build_body(rule, new_matches),
            rule_id=row["id"],
            total=len(new_matches),
            frequency=row.get("frequency"),
        )
        log.info("watchlist_rule_alert_sent", rule_id=row["id"], total=len(new_matches))
        alerted += 1

    return alerted
