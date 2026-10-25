"""Tests de scheduler/jobs/watchlist_rules.py (plan Pliegos+RAG, C2a).

Cierra el ítem P2 del backlog ("Registrar watchlist_rules_alerts en el
registry de scheduler/jobs"): el job existe, está en ``build_default_registry``
(ver ``test_loop.py``), y no duplica notificaciones si la pipeline canónica
y este job corren ambos sobre la misma BD.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scheduler.jobs import watchlist_rules as job
from services.watchlist_rules import WatchlistRule, create_rule


def _recent(days_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).date().isoformat()


def _insert_lic(c, lic_id, *, titulo="Lic", fecha=None):
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, fuente, fecha_publicacion, "
        "fecha_extraccion) VALUES (%s, %s, 'placsp', %s, CURRENT_TIMESTAMP)",
        (lic_id, titulo, fecha or _recent(3)),
    )


def _regla(user_key: str, rule: WatchlistRule) -> int:
    """Una regla como las crea la API: con organización.

    `POST /watchlist/rules` exige organización desde S4.3, y una alerta sin
    ella no aparece en ninguna campana: desde v162 el job la descarta en vez
    de escribirla invisible, así que una regla sin organización ya no sirve
    para probar que notifica.
    """
    from db.repositories.organizations import OrganizationRepository
    from db.users import create_user

    owner = create_user(
        email=f"{user_key}-{rule.keyword.lower()}-{rule.frequency}@example.test",
        password_hash="test-hash",  # pragma: allowlist secret -- literal de test
        display_name=user_key,
    )
    org = int(OrganizationRepository().create_organization(f"org-{owner}", owner)["id"])
    return create_rule(user_key, rule, organization_id=org)


def test_run_disabled_by_default_is_noop(tmp_db, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "WATCHLIST_RULES_JOB_ENABLED", False, raising=False)
    _, _ = tmp_db
    from db.database import connect

    _regla("user-a", WatchlistRule(keyword="SAP", frequency="daily"))
    with connect() as c:
        _insert_lic(c, "L1", titulo="Implantacion SAP")

    result = job.run()

    assert result == 0
    with connect() as c:
        count = c.execute("SELECT COUNT(*) FROM user_notifications").fetchone()[0]
    assert count == 0  # el job no tocó nada -- confirma que es un no-op real


def test_run_enabled_delegates_to_check_rules_and_notify(tmp_db, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "WATCHLIST_RULES_JOB_ENABLED", True, raising=False)
    _, _ = tmp_db
    from db.database import connect

    _regla("user-a", WatchlistRule(keyword="SAP", frequency="daily"))
    with connect() as c:
        _insert_lic(c, "L1", titulo="Implantacion SAP")

    result = job.run()

    assert result == 1
    with connect() as c:
        count = c.execute(
            "SELECT COUNT(*) FROM user_notifications WHERE type = 'rule_match'"
        ).fetchone()[0]
    assert count == 1


def test_anti_doble_ejecucion_pipeline_y_job_activos_una_sola_notificacion(tmp_db, monkeypatch):
    """Escenario del plan: la pipeline canónica (_run_watchlist_notify) y este
    job dedicado corren ambos sobre la misma BD (p.ej. durante una migración
    de plano de orquestación, ADR-012). Debe quedar exactamente UNA
    notificación in-app por (usuario, licitación) -- no dos."""
    from config import settings

    monkeypatch.setattr(settings, "WATCHLIST_RULES_JOB_ENABLED", True, raising=False)
    _, _ = tmp_db
    from db.database import connect
    from scheduler.watchlist_rules_alerts import check_rules_and_notify

    _regla("user-a", WatchlistRule(keyword="SAP", frequency="immediate"))
    with connect() as c:
        _insert_lic(c, "L1", titulo="Implantacion SAP S/4HANA")

    # 1) La pipeline canónica corre primero (scheduler/pipeline_runs.py::_run_watchlist_notify)
    check_rules_and_notify()
    # 2) El job dedicado corre después sobre la MISMA licitación (frequency
    #    "immediate" -- is_due() siempre True, así que reintentaría sin la
    #    guarda de idempotencia de user_notifications).
    job.run()

    with connect() as c:
        rows = c.execute(
            "SELECT user_key, licitacion_id, COUNT(*) as n FROM user_notifications "
            "WHERE type = 'rule_match' GROUP BY user_key, licitacion_id"
        ).fetchall()

    assert len(rows) == 1  # una sola combinación (usuario, licitación)
    assert rows[0][2] == 1  # y con una sola fila -- no duplicada
