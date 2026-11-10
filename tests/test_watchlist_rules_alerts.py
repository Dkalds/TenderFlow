"""Tests del job de alertas de reglas de watchlist (scheduler/watchlist_rules_alerts).

Cubre: due/no-due por frecuencia, reglas inactivas, sin matches (mueve ventana),
corte temporal, deduplicación por anti-join y escritura en user_notifications.

Desde 2026-11 el job solo escribe ``watchlist_rule.matched`` en el outbox; la
campana y el digest los escribe el despachador. :func:`_pasada` hace lo que el
cierre canónico: el paso ``watchlist_notify`` y, después, ``event_dispatch``.

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


def _regla(nombre: str, rule: WatchlistRule) -> int:
    """Una regla como las crea la API: de un usuario real y con organización.

    `POST /watchlist/rules` exige organización desde S4.3, y una alerta sin
    ella no aparece en ninguna campana: desde v162 el job la descarta en vez
    de escribirla invisible, así que una regla sin organización ya no sirve
    para probar que notifica. Tampoco sirve una sin `user_id` (v181): el job
    no la evalúa porque no tiene a quién avisar.
    """
    from db.repositories.organizations import OrganizationRepository
    from db.users import create_user

    owner = create_user(
        email=f"{nombre}-{rule.keyword.lower()}-{rule.frequency}@example.test",
        password_hash="test-hash",  # pragma: allowlist secret -- literal de test
        display_name=nombre,
    )
    org = int(OrganizationRepository().create_organization(f"org-{owner}", owner)["id"])
    return create_rule(owner, rule, organization_id=org)


def _pasada(**kwargs) -> int:
    """El job de reglas y el despachador, en el orden del cierre canónico."""
    from scheduler.jobs.event_dispatch import dispatch_pending

    n = watchlist_rules_alerts.check_rules_and_notify(**kwargs)
    dispatch_pending()
    return n


def _set_last_notified(c, rule_id, iso_ts):
    c.execute("UPDATE watchlist_rules SET last_notified_at = %s WHERE id = %s", (iso_ts, rule_id))


def test_sin_reglas_devuelve_cero(tmp_db):
    _, _ = tmp_db
    assert watchlist_rules_alerts.check_rules_and_notify() == 0


def test_regla_due_con_matches_nuevos_notifica(tmp_db):
    from db.database import connect

    _, _ = tmp_db
    rid = _regla("user-a", WatchlistRule(keyword="SAP", frequency="daily"))
    with connect() as c:
        _insert_lic(c, "L1", titulo="Implantacion SAP", fecha=_recent(3))

    n = _pasada()
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
    rid = _regla("user-a", WatchlistRule(keyword="SAP"))
    with connect() as c:
        c.execute("UPDATE watchlist_rules SET active = 0 WHERE id = %s", (rid,))
        _insert_lic(c, "L1", titulo="SAP", fecha=_recent(3))

    assert watchlist_rules_alerts.check_rules_and_notify() == 0


def test_regla_no_due_se_salta(tmp_db):
    from db.database import connect

    _, _ = tmp_db
    rid = _regla("user-a", WatchlistRule(keyword="SAP", frequency="daily"))
    with connect() as c:
        _set_last_notified(c, rid, datetime.now(UTC).isoformat())  # recien notificada
        _insert_lic(c, "L1", titulo="SAP", fecha=_recent(1))

    assert watchlist_rules_alerts.check_rules_and_notify() == 0


def test_sin_matches_no_notifica_pero_mueve_ventana(tmp_db):
    from db.database import connect

    _, _ = tmp_db
    rid = _regla("user-a", WatchlistRule(keyword="NOEXISTE"))
    assert watchlist_rules_alerts.check_rules_and_notify() == 0
    with connect() as c:
        last = c.execute(
            "SELECT last_notified_at FROM watchlist_rules WHERE id = %s", (rid,)
        ).fetchone()[0]
    assert last is not None  # la ventana se movio aunque no haya matches


# ---------------------------------------------------------------------------
# S4.1: el aviso a las integraciones sale por el outbox, no por `trigger_event`
#
# Estos tres tests espiaban `db.webhooks.trigger_event`, que era como el job
# entregaba a los webhooks **antes** de S4: una conexión HTTP por suscriptor
# dentro de la evaluación de las reglas. Ahora el job escribe
# `watchlist_rule.matched` en `domain_events` y el reparto lo hace
# `scheduler/jobs/event_dispatch.py`. El monkeypatch sobre `trigger_event`
# dejó de interceptar nada, así que uno de los tres falló (`assert 0 == 1`) y
# los otros dos pasaban en vacío — comprobaban el comportamiento de una función
# que ya nadie llama en este camino. Se reescriben contra el outbox, que es
# donde vive ahora la garantía; la entrega HTTP en sí tiene sus propios tests
# en `tests/test_s4_outbox.py`.
# ---------------------------------------------------------------------------


def _eventos_de_regla() -> list[dict]:
    from db.events import pending_events

    return [e for e in pending_events() if e["event_type"] == "watchlist_rule.matched"]


def test_regla_due_con_matches_escribe_el_evento_en_el_outbox(tmp_db):
    """F12·C2c: cada regla con matches nuevos emite ``watchlist_rule.matched``."""
    from db.database import connect

    _, _ = tmp_db
    rid = _regla("user-a", WatchlistRule(keyword="SAP", frequency="daily"))
    with connect() as c:
        _insert_lic(c, "L1", titulo="Implantacion SAP", fecha=_recent(3))

    n = watchlist_rules_alerts.check_rules_and_notify()
    assert n == 1

    eventos = _eventos_de_regla()
    assert len(eventos) == 1
    payload = eventos[0]["payload"]
    assert payload["rule_id"] == rid
    assert payload["keyword"] == "SAP"
    assert payload["total_matches"] == 1
    assert payload["licitaciones"] == ["L1"]


def test_si_el_outbox_falla_la_ventana_no_avanza(tmp_db, monkeypatch):
    """El evento es la alerta: si no se escribe, la regla sigue pendiente.

    Hasta 2026-11 el evento solo llevaba el webhook y era best-effort, porque
    la campana ya estaba escrita. Ahora tragarse el fallo perdería el aviso.
    """
    from db.database import connect

    _, _ = tmp_db

    def _boom(*_args, **_kwargs):
        raise RuntimeError("outbox no disponible")

    monkeypatch.setattr(watchlist_rules_alerts, "append_domain_event", _boom)

    rid = _regla("user-a", WatchlistRule(keyword="SAP", frequency="daily"))
    with connect() as c:
        _insert_lic(c, "L1", titulo="Implantacion SAP", fecha=_recent(3))

    assert _pasada() == 0  # el fallo de una regla no propaga

    with connect() as c:
        last = c.execute(
            "SELECT last_notified_at FROM watchlist_rules WHERE id = %s", (rid,)
        ).fetchone()[0]
        count = c.execute(
            "SELECT COUNT(*) FROM user_notifications WHERE type = 'rule_match'"
        ).fetchone()[0]
    assert last is None
    assert count == 0

    monkeypatch.undo()
    assert _pasada() == 1  # la pasada siguiente lo recupera


def test_sin_matches_no_escribe_evento(tmp_db):
    _, _ = tmp_db
    _regla("user-a", WatchlistRule(keyword="NOEXISTE"))
    assert watchlist_rules_alerts.check_rules_and_notify() == 0
    assert _eventos_de_regla() == []


def test_solo_matches_posteriores_a_last_notified(tmp_db):
    from db.database import connect

    _, _ = tmp_db
    rid = _regla("user-a", WatchlistRule(keyword="SAP", frequency="daily"))
    with connect() as c:
        _set_last_notified(c, rid, (datetime.now(UTC) - timedelta(days=2)).isoformat())
        # El corte efectivo es `last_notified_at - _VENTANA_GRACIA_DIAS`, o sea
        # hace 4 días: "OLD" se elige claramente fuera de esa ventana para que
        # el test siga midiendo el corte y no el margen exacto de la gracia.
        _insert_lic(c, "OLD", titulo="SAP viejo", fecha=_recent(10))  # antes del corte
        _insert_lic(c, "NEW", titulo="SAP nuevo", fecha=_recent(1))  # despues del corte

    n = _pasada()
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
    rid = _regla("user-a", WatchlistRule(keyword="SAP", frequency="immediate"))
    hoy = datetime.now(UTC)
    with connect() as c:
        # La regla ya se evaluó hoy — es el estado normal de producción, no un
        # caso raro: el job corre cada 4 h y mueve la ventana siempre.
        _set_last_notified(c, rid, hoy.isoformat())
        _insert_lic(c, "HOY", titulo="Implantacion SAP", fecha=hoy.date().isoformat())

    assert _pasada() == 1

    with connect() as c:
        notifs = c.execute(
            "SELECT licitacion_id FROM user_notifications WHERE type = 'rule_match'"
        ).fetchall()
    assert {r[0] for r in notifs} == {"HOY"}


def test_no_repite_una_notificacion_ya_escrita(tmp_db):
    """La ventana se solapa a propósito; quien deduplica es el anti-join."""
    from db.database import connect

    _, _ = tmp_db
    _regla("user-a", WatchlistRule(keyword="SAP", frequency="immediate"))
    with connect() as c:
        _insert_lic(c, "L1", titulo="SAP", fecha=_recent(0))

    assert _pasada() == 1
    # Segunda pasada inmediata: la misma licitación sigue dentro de la ventana
    # (por eso el anti-join es imprescindible), pero ya no es nueva.
    assert _pasada() == 0

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
    _regla("user-a", WatchlistRule(keyword="SAP", frequency="immediate"))
    with connect() as c:
        for i, dias in enumerate((0, 1, 2)):
            _insert_lic(c, f"L{i}", titulo="SAP", fecha=_recent(dias))

    assert _pasada(limit_per_rule=2) == 1
    assert _pasada(limit_per_rule=2) == 1

    with connect() as c:
        notifs = c.execute(
            "SELECT licitacion_id FROM user_notifications WHERE type = 'rule_match'"
        ).fetchall()
    assert {r[0] for r in notifs} == {"L0", "L1", "L2"}


# ── Idempotencia del reparto por el outbox ───────────────────────────────────


def test_con_el_aviso_en_cola_la_regla_no_se_reevalua(tmp_db):
    """Sin despacho entre pasadas, la segunda no emite lo mismo otra vez.

    El anti-join mira la campana, que todavía no existe: sin la guarda, el
    webhook recibiría las mismas licitaciones dos veces.
    """
    from db.database import connect

    _, _ = tmp_db
    _regla("user-a", WatchlistRule(keyword="SAP", frequency="immediate"))
    with connect() as c:
        _insert_lic(c, "L1", titulo="SAP", fecha=_recent(0))

    assert watchlist_rules_alerts.check_rules_and_notify() == 1
    assert watchlist_rules_alerts.check_rules_and_notify() == 0
    assert len(_eventos_de_regla()) == 1


def test_repetir_la_pasada_no_duplica_campana_digest_ni_webhook(tmp_db, monkeypatch):
    """Una regla con correo y un webhook suscrito: dos pasadas, una salida de cada.

    Y el correo de la regla no llega al webhook: el despachador lo lee de la
    regla para el digest y no lo pone en el evento.
    """
    import db.webhooks as salida
    from db.database import connect
    from db.repositories.webhooks import WebhookRepository

    _, _ = tmp_db
    entregas: list[bytes] = []
    monkeypatch.setattr(
        WebhookRepository,
        "list_active_subscribers",
        lambda self, **_: [
            {
                "id": 1,
                "url": "https://hooks.example.test/x",
                "secret": "s",  # pragma: allowlist secret -- literal de test
                "event_types": ["watchlist_rule.matched"],
                "formato": "json",
            }
        ],
    )
    monkeypatch.setattr(
        salida, "entregar_firmado", lambda **kw: entregas.append(kw["body"]) or True
    )

    rid = _regla("user-a", WatchlistRule(keyword="SAP", frequency="weekly"))
    with connect() as c:
        c.execute(
            "UPDATE watchlist_rules SET email = 'regla-privada@example.test' WHERE id = %s",
            (rid,),
        )
        _insert_lic(c, "L1", titulo="SAP uno", fecha=_recent(0))
        _insert_lic(c, "L2", titulo="SAP dos", fecha=_recent(1))

    assert _pasada() == 1
    assert _pasada() == 0
    with connect() as c:
        c.execute("UPDATE watchlist_rules SET last_notified_at = NULL WHERE id = %s", (rid,))
    assert _pasada() == 0  # ventana reabierta: el anti-join ya ve la campana

    with connect() as c:
        campana = c.execute(
            "SELECT licitacion_id, rule_id FROM user_notifications "
            "WHERE type = 'rule_match' ORDER BY licitacion_id"
        ).fetchall()
        digest = c.execute(
            "SELECT licitacion_id, recipient_email, frequency, entry_id FROM pending_digests "
            "ORDER BY licitacion_id"
        ).fetchall()
    assert [tuple(f) for f in campana] == [("L1", rid), ("L2", rid)]
    assert [tuple(f) for f in digest] == [
        ("L1", "regla-privada@example.test", "weekly", rid),
        ("L2", "regla-privada@example.test", "weekly", rid),
    ]
    assert len(entregas) == 1
    assert b"regla-privada" not in entregas[0]
