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
