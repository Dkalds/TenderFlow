"""Tests del job de alertas de reglas de watchlist (scheduler/watchlist_rules_alerts).

Cubre: due/no-due por frecuencia, reglas inactivas, sin matches (mueve ventana) y
que solo se notifican licitaciones posteriores a last_notified_at.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from scheduler import watchlist_rules_alerts
from services.watchlist_rules import WatchlistRule, create_rule


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


def _recent(days_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).date().isoformat()


def _insert_lic(c, lic_id, *, titulo="Lic", cpv=None, importe=None, ccaa=None, fecha=None):
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, cpv, importe, ccaa, fuente, "
        "fecha_publicacion, fecha_extraccion) "
        "VALUES (?, ?, ?, ?, ?, 'placsp', ?, datetime('now'))",
        (lic_id, titulo, cpv, importe, ccaa, fecha or _recent(5)),
    )


def _set_last_notified(c, rule_id, iso_ts):
    c.execute("UPDATE watchlist_rules SET last_notified_at = ? WHERE id = ?", (iso_ts, rule_id))


def test_sin_reglas_devuelve_cero(db):
    with patch("scheduler.watchlist_rules_alerts.notify") as mock_notify:
        assert watchlist_rules_alerts.check_rules_and_notify() == 0
    mock_notify.assert_not_called()


def test_regla_due_con_matches_nuevos_notifica(db):
    from db.database import connect

    rid = create_rule("user-a", WatchlistRule(keyword="SAP", frequency="daily"))
    with connect() as c:
        _insert_lic(c, "L1", titulo="Implantación SAP", fecha=_recent(3))

    with patch("scheduler.watchlist_rules_alerts.notify") as mock_notify:
        n = watchlist_rules_alerts.check_rules_and_notify()

    assert n == 1
    mock_notify.assert_called_once()
    assert mock_notify.call_args.kwargs["total"] == 1
    with connect() as c:
        last = c.execute(
            "SELECT last_notified_at FROM watchlist_rules WHERE id = ?", (rid,)
        ).fetchone()[0]
    assert last is not None


def test_regla_inactiva_se_ignora(db):
    from db.database import connect

    rid = create_rule("user-a", WatchlistRule(keyword="SAP"))
    with connect() as c:
        c.execute("UPDATE watchlist_rules SET active = 0 WHERE id = ?", (rid,))
        _insert_lic(c, "L1", titulo="SAP", fecha=_recent(3))

    with patch("scheduler.watchlist_rules_alerts.notify") as mock_notify:
        assert watchlist_rules_alerts.check_rules_and_notify() == 0
    mock_notify.assert_not_called()


def test_regla_no_due_se_salta(db):
    from db.database import connect

    rid = create_rule("user-a", WatchlistRule(keyword="SAP", frequency="daily"))
    with connect() as c:
        _set_last_notified(c, rid, datetime.now(UTC).isoformat())  # recién notificada
        _insert_lic(c, "L1", titulo="SAP", fecha=_recent(1))

    with patch("scheduler.watchlist_rules_alerts.notify") as mock_notify:
        assert watchlist_rules_alerts.check_rules_and_notify() == 0
    mock_notify.assert_not_called()


def test_sin_matches_no_notifica_pero_mueve_ventana(db):
    from db.database import connect

    rid = create_rule("user-a", WatchlistRule(keyword="NOEXISTE"))
    with patch("scheduler.watchlist_rules_alerts.notify") as mock_notify:
        assert watchlist_rules_alerts.check_rules_and_notify() == 0
    mock_notify.assert_not_called()
    with connect() as c:
        last = c.execute(
            "SELECT last_notified_at FROM watchlist_rules WHERE id = ?", (rid,)
        ).fetchone()[0]
    assert last is not None  # la ventana se movió aunque no haya matches


def test_solo_matches_posteriores_a_last_notified(db):
    from db.database import connect

    rid = create_rule("user-a", WatchlistRule(keyword="SAP", frequency="daily"))
    with connect() as c:
        _set_last_notified(c, rid, (datetime.now(UTC) - timedelta(days=2)).isoformat())
        _insert_lic(c, "OLD", titulo="SAP viejo", fecha=_recent(5))  # antes del corte
        _insert_lic(c, "NEW", titulo="SAP nuevo", fecha=_recent(1))  # después del corte

    with patch("scheduler.watchlist_rules_alerts.notify") as mock_notify:
        n = watchlist_rules_alerts.check_rules_and_notify()

    assert n == 1
    assert mock_notify.call_args.kwargs["total"] == 1  # solo NEW
