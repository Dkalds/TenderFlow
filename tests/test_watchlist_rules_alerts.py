"""Tests del job de alertas de reglas de watchlist (scheduler/watchlist_rules_alerts).

Cubre: due/no-due por frecuencia, reglas inactivas, sin matches (mueve ventana),
solo licitaciones posteriores a last_notified_at, y escritura en user_notifications.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scheduler import watchlist_rules_alerts
from services.watchlist_rules import WatchlistRule, create_rule


def _recent(days_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).date().isoformat()


def _insert_lic(c, lic_id, *, titulo="Lic", cpv=None, importe=None, ccaa=None, fecha=None):
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, cpv, importe, ccaa, fuente, "
        "fecha_publicacion, fecha_extraccion) "
        "VALUES (?, ?, ?, ?, ?, 'placsp', ?, CURRENT_TIMESTAMP)",
        (lic_id, titulo, cpv, importe, ccaa, fecha or _recent(5)),
    )


def _set_last_notified(c, rule_id, iso_ts):
    c.execute("UPDATE watchlist_rules SET last_notified_at = ? WHERE id = ?", (iso_ts, rule_id))


def test_sin_reglas_devuelve_cero(tmp_db):
    _, _ = tmp_db
    assert watchlist_rules_alerts.check_rules_and_notify() == 0


def test_regla_due_con_matches_nuevos_notifica(tmp_db):
    from db.database import connect

    _, _ = tmp_db
    rid = create_rule("user-a", WatchlistRule(keyword="SAP", frequency="daily"))
    with connect() as c:
        _insert_lic(c, "L1", titulo="Implantacion SAP", fecha=_recent(3))

    n = watchlist_rules_alerts.check_rules_and_notify()
    assert n == 1

    # Verifica que se actualizo last_notified_at
    with connect() as c:
        last = c.execute(
            "SELECT last_notified_at FROM watchlist_rules WHERE id = ?", (rid,)
        ).fetchone()[0]
    assert last is not None

    # Verifica que se escribio en user_notifications
    with connect() as c:
        count = c.execute(
            "SELECT COUNT(*) FROM user_notifications WHERE user_key LIKE '%' AND type = 'rule_match'"
        ).fetchone()[0]
    assert count >= 1


def test_regla_inactiva_se_ignora(tmp_db):
    from db.database import connect

    _, _ = tmp_db
    rid = create_rule("user-a", WatchlistRule(keyword="SAP"))
    with connect() as c:
        c.execute("UPDATE watchlist_rules SET active = 0 WHERE id = ?", (rid,))
        _insert_lic(c, "L1", titulo="SAP", fecha=_recent(3))

    assert watchlist_rules_alerts.check_rules_and_notify() == 0


def test_regla_no_due_se_salta(tmp_db):
    from db.database import connect

    _, _ = tmp_db
    rid = create_rule("user-a", WatchlistRule(keyword="SAP", frequency="daily"))
    with connect() as c:
        _set_last_notified(c, rid, datetime.now(UTC).isoformat())  # recien notificada
        _insert_lic(c, "L1", titulo="SAP", fecha=_recent(1))

    assert watchlist_rules_alerts.check_rules_and_notify() == 0


def test_sin_matches_no_notifica_pero_mueve_ventana(tmp_db):
    from db.database import connect

    _, _ = tmp_db
    rid = create_rule("user-a", WatchlistRule(keyword="NOEXISTE"))
    assert watchlist_rules_alerts.check_rules_and_notify() == 0
    with connect() as c:
        last = c.execute(
            "SELECT last_notified_at FROM watchlist_rules WHERE id = ?", (rid,)
        ).fetchone()[0]
    assert last is not None  # la ventana se movio aunque no haya matches


def test_regla_due_con_matches_dispara_webhook(tmp_db, monkeypatch):
    """F12·C2c: cada regla con matches nuevos dispara ``watchlist_rule.matched``."""
    from db.database import connect

    _, _ = tmp_db
    calls = []
    monkeypatch.setattr(
        "db.webhooks.trigger_event", lambda event_type, payload: calls.append((event_type, payload))
    )

    rid = create_rule("user-a", WatchlistRule(keyword="SAP", frequency="daily"))
    with connect() as c:
        _insert_lic(c, "L1", titulo="Implantacion SAP", fecha=_recent(3))

    n = watchlist_rules_alerts.check_rules_and_notify()
    assert n == 1

    assert len(calls) == 1
    event_type, payload = calls[0]
    assert event_type == "watchlist_rule.matched"
    assert payload["rule_id"] == rid
    assert payload["keyword"] == "SAP"
    assert payload["total_matches"] == 1
    assert payload["licitaciones"] == ["L1"]


def test_webhook_trigger_failure_no_rompe_notificacion(tmp_db, monkeypatch):
    """El disparo de webhook es best-effort: si falla, la notificación in-app persiste."""
    from db.database import connect

    _, _ = tmp_db

    def _boom(event_type, payload):
        raise RuntimeError("webhook endpoint unreachable")

    monkeypatch.setattr("db.webhooks.trigger_event", _boom)

    create_rule("user-a", WatchlistRule(keyword="SAP", frequency="daily"))
    with connect() as c:
        _insert_lic(c, "L1", titulo="Implantacion SAP", fecha=_recent(3))

    n = watchlist_rules_alerts.check_rules_and_notify()  # no debe propagar la excepción
    assert n == 1

    with connect() as c:
        count = c.execute(
            "SELECT COUNT(*) FROM user_notifications WHERE type = 'rule_match'"
        ).fetchone()[0]
    assert count == 1


def test_sin_matches_no_dispara_webhook(tmp_db, monkeypatch):
    _, _ = tmp_db
    calls = []
    monkeypatch.setattr(
        "db.webhooks.trigger_event", lambda event_type, payload: calls.append((event_type, payload))
    )

    create_rule("user-a", WatchlistRule(keyword="NOEXISTE"))
    assert watchlist_rules_alerts.check_rules_and_notify() == 0
    assert calls == []


def test_solo_matches_posteriores_a_last_notified(tmp_db):
    from db.database import connect

    _, _ = tmp_db
    rid = create_rule("user-a", WatchlistRule(keyword="SAP", frequency="daily"))
    with connect() as c:
        _set_last_notified(c, rid, (datetime.now(UTC) - timedelta(days=2)).isoformat())
        _insert_lic(c, "OLD", titulo="SAP viejo", fecha=_recent(5))  # antes del corte
        _insert_lic(c, "NEW", titulo="SAP nuevo", fecha=_recent(1))  # despues del corte

    n = watchlist_rules_alerts.check_rules_and_notify()
    assert n == 1

    # Verifica que solo el match nuevo llego a user_notifications
    with connect() as c:
        notifs = c.execute(
            "SELECT licitacion_id FROM user_notifications WHERE type = 'rule_match'"
        ).fetchall()
    lic_ids = {r[0] for r in notifs}
    assert "NEW" in lic_ids
    assert "OLD" not in lic_ids
