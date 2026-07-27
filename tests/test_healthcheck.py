"""Tests para scheduler.healthcheck.run_check."""

from __future__ import annotations

from datetime import UTC


def test_healthcheck_critical_without_runs(tmp_db):
    from scheduler.healthcheck import run_check

    result = run_check()
    assert result["status"] == "critical"
    assert "sin_runs_registrados" in result["errors"]


def test_healthcheck_healthy_after_successful_run(tmp_db):
    from observability.metrics import record_run

    with record_run("run-ok") as m:
        m.months_attempted = 1
        m.months_ok = 1

    from scheduler.healthcheck import run_check

    result = run_check()
    assert result["status"] == "healthy", result


def test_healthcheck_degraded_when_last_run_stale(tmp_db):
    from datetime import datetime, timedelta

    from db.database import connect

    old = (datetime.now(UTC) - timedelta(days=5)).isoformat()
    with connect() as c:
        c.execute(
            "INSERT INTO extraction_runs "
            "(run_id, started_at, ended_at, duration_ms, status, "
            " months_attempted, months_ok) "
            "VALUES ('r-old', ?, ?, 1000, 'ok', 1, 1)",
            (old, old),
        )

    from scheduler.healthcheck import run_check

    result = run_check(freshness_hours=36)
    assert result["status"] == "degraded"
    assert any(w.startswith("last_run_stale") for w in result["warnings"])


def test_healthcheck_degraded_when_dlq_above_threshold(tmp_db):
    from datetime import datetime

    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO extraction_runs "
            "(run_id, started_at, ended_at, status) VALUES "
            "('r1', ?, ?, 'ok')",
            (datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat()),
        )
        for i in range(6):
            c.execute(
                "INSERT INTO failed_extractions (fuente, created_at) VALUES (?, ?)",
                (f"src-{i}", datetime.now(UTC).isoformat()),
            )

    from scheduler.healthcheck import run_check

    result = run_check(dlq_threshold=5)
    assert result["status"] == "degraded"
    assert any("dlq_above_threshold" in w for w in result["warnings"])


def test_healthcheck_degraded_when_empresa_resolution_below_threshold(tmp_db):
    from datetime import datetime

    from db.database import connect

    now = datetime.now(UTC).isoformat()
    with connect() as c:
        c.execute(
            "INSERT INTO extraction_runs "
            "(run_id, started_at, ended_at, status) VALUES ('r1', ?, ?, 'ok')",
            (now, now),
        )
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion) "
            "VALUES ('LIC-001', 'Contrato de prueba', ?)",
            (now,),
        )
        c.execute(
            "INSERT INTO adjudicaciones "
            "(licitacion_id, nombre, fecha_extraccion) VALUES ('LIC-001', 'Empresa', ?)",
            (now,),
        )

    from scheduler.healthcheck import run_check

    result = run_check()
    assert result["status"] == "degraded"
    assert result["info"]["empresa_resolution"]["pct_filas"] == 0.0
    assert any("empresa_resolution_below_threshold" in w for w in result["warnings"])


def test_healthcheck_counts_pending_review_as_covered(tmp_db):
    from datetime import datetime

    from db.database import connect

    now = datetime.now(UTC).isoformat()
    with connect() as c:
        c.execute(
            "INSERT INTO extraction_runs "
            "(run_id, started_at, ended_at, status) VALUES ('r1', ?, ?, 'ok')",
            (now, now),
        )
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion) "
            "VALUES ('LIC-001', 'Contrato de prueba', ?)",
            (now,),
        )
        c.execute(
            "INSERT INTO adjudicaciones "
            "(licitacion_id, nombre, nif, fecha_extraccion) "
            "VALUES ('LIC-001', 'Empresa Candidata S.L.', 'B12345678', ?)",  # pragma: allowlist secret -- NIF sintético
            (now,),
        )
        c.execute(
            "INSERT INTO empresa_review_queue "
            "(nombre_original, alias_normalizado, nif, score, status, created_at) "
            "VALUES ('Empresa Candidata S.L.', 'EMPRESA CANDIDATA', "
            "'B12345678', 0.95, 'pending', ?)",
            (now,),
        )

    from scheduler.healthcheck import run_check

    result = run_check()
    resolution = result["info"]["empresa_resolution"]
    assert resolution == {
        "total": 1,
        "enlazadas": 0,
        "en_revision": 1,
        "pendientes": 0,
        "pct_filas": 100.0,
    }
    assert not any("empresa_resolution_below_threshold" in w for w in result["warnings"])


def test_healthcheck_main_returns_0_for_healthy(tmp_db):
    from unittest.mock import patch

    from observability.metrics import record_run

    with record_run("run-main-ok") as m:
        m.months_attempted = 1
        m.months_ok = 1

    from scheduler.healthcheck import main

    with patch("sys.argv", ["healthcheck"]):
        code = main()

    assert code == 0


def test_healthcheck_main_returns_1_for_degraded(tmp_db):
    from datetime import datetime, timedelta
    from unittest.mock import patch

    from db.database import connect

    old = (datetime.now(UTC) - timedelta(days=5)).isoformat()
    with connect() as c:
        c.execute(
            "INSERT INTO extraction_runs "
            "(run_id, started_at, ended_at, duration_ms, status, "
            " months_attempted, months_ok) "
            "VALUES ('r-deg', ?, ?, 1000, 'ok', 1, 1)",
            (old, old),
        )

    from scheduler.healthcheck import main

    with patch("sys.argv", ["healthcheck"]):
        code = main()

    assert code == 1


def test_healthcheck_main_alert_mode_returns_0(tmp_db):
    from unittest.mock import patch

    from scheduler.healthcheck import main

    # No runs → critical, but --alert mode should still return 0
    with patch("sys.argv", ["healthcheck", "--alert"]), patch("scheduler.healthcheck.notify"):
        code = main()

    assert code == 0
