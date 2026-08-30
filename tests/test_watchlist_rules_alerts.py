"""Tests del job de alertas de reglas de watchlist (scheduler/watchlist_rules_alerts).

Cubre: due/no-due por frecuencia, reglas inactivas, sin matches (mueve ventana),
corte temporal, deduplicación por anti-join y escritura en user_notifications.

El corte temporal se prueba en sus DOS formas, y la segunda es la que faltaba
hasta el 2026-08-30: días distintos (siempre funcionó) y **el mismo día que el
cursor**, que es el estado normal de producción y no notificaba nunca.
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
        "VALUES (%s, %s, %s, %s, %s, 'placsp', %s, CURRENT_TIMESTAMP)",
        (lic_id, titulo, cpv, importe, ccaa, fecha or _recent(5)),
    )


def _set_last_notified(c, rule_id, iso_ts):
    c.execute("UPDATE watchlist_rules SET last_notified_at = %s WHERE id = %s", (iso_ts, rule_id))


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
            "SELECT last_notified_at FROM watchlist_rules WHERE id = %s", (rid,)
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
        c.execute("UPDATE watchlist_rules SET active = 0 WHERE id = %s", (rid,))
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
            "SELECT last_notified_at FROM watchlist_rules WHERE id = %s", (rid,)
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
        # El corte efectivo es `last_notified_at - _VENTANA_GRACIA_DIAS`, o sea
        # hace 4 días: "OLD" se elige claramente fuera de esa ventana para que
        # el test siga midiendo el corte y no el margen exacto de la gracia.
        _insert_lic(c, "OLD", titulo="SAP viejo", fecha=_recent(10))  # antes del corte
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


# ── El corte del mismo día ────────────────────────────────────────────────────
#
# Los tests de arriba siembran la licitación en un día DISTINTO del cursor, que
# es el caso que siempre funcionó. El que rompía en producción es el otro: el
# cursor y la publicación en el MISMO día. Con el filtro exclusivo (`>`) y una
# ventana que avanza en cada evaluación, ese expediente quedaba excluido para
# siempre — y como el carril diario corre a las 00:0x UTC, "el mismo día" es
# casi todo lo que se publica.


def test_notifica_lo_publicado_el_mismo_dia_en_que_la_regla_ya_se_evaluo(tmp_db):
    """Regresión del P0: cursor y publicación en el mismo día.

    Con el corte exclusivo anterior este test devolvía 0 notificaciones y
    ninguna alerta se disparaba nunca más después de la primera evaluación.
    """
    from db.database import connect

    _, _ = tmp_db
    rid = create_rule("user-a", WatchlistRule(keyword="SAP", frequency="immediate"))
    hoy = datetime.now(UTC)
    with connect() as c:
        # La regla ya se evaluó hoy — es el estado normal de producción, no un
        # caso raro: el job corre cada 4 h y mueve la ventana siempre.
        _set_last_notified(c, rid, hoy.isoformat())
        _insert_lic(c, "HOY", titulo="Implantacion SAP", fecha=hoy.date().isoformat())

    assert watchlist_rules_alerts.check_rules_and_notify() == 1

    with connect() as c:
        notifs = c.execute(
            "SELECT licitacion_id FROM user_notifications WHERE type = 'rule_match'"
        ).fetchall()
    assert {r[0] for r in notifs} == {"HOY"}


def test_no_repite_una_notificacion_ya_escrita(tmp_db):
    """La ventana se solapa a propósito; quien deduplica es el anti-join."""
    from db.database import connect

    _, _ = tmp_db
    create_rule("user-a", WatchlistRule(keyword="SAP", frequency="immediate"))
    with connect() as c:
        _insert_lic(c, "L1", titulo="SAP", fecha=_recent(0))

    assert watchlist_rules_alerts.check_rules_and_notify() == 1
    # Segunda pasada inmediata: la misma licitación sigue dentro de la ventana
    # (por eso el anti-join es imprescindible), pero ya no es nueva.
    assert watchlist_rules_alerts.check_rules_and_notify() == 0

    with connect() as c:
        total = c.execute(
            "SELECT COUNT(*) FROM user_notifications WHERE type = 'rule_match'"
        ).fetchone()[0]
    assert total == 1


def test_el_tope_no_se_gasta_en_lo_ya_notificado(tmp_db):
    """Con más matches que tope, las pasadas siguientes drenan el resto.

    Antes el ``LIMIT`` se aplicaba sobre filas ya notificadas, así que las
    coincidencias por encima del tope no se alcanzaban nunca: el INSERT las
    descartaba por el índice único y la siguiente pasada volvía a traer las
    mismas.
    """
    from db.database import connect

    _, _ = tmp_db
    create_rule("user-a", WatchlistRule(keyword="SAP", frequency="immediate"))
    with connect() as c:
        for i, dias in enumerate((0, 1, 2)):
            _insert_lic(c, f"L{i}", titulo="SAP", fecha=_recent(dias))

    assert watchlist_rules_alerts.check_rules_and_notify(limit_per_rule=2) == 1
    assert watchlist_rules_alerts.check_rules_and_notify(limit_per_rule=2) == 1

    with connect() as c:
        notifs = c.execute(
            "SELECT licitacion_id FROM user_notifications WHERE type = 'rule_match'"
        ).fetchall()
    assert {r[0] for r in notifs} == {"L0", "L1", "L2"}
