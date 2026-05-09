"""Tests para observability.metrics (RunMetrics + record_run)."""

from __future__ import annotations

import pytest

from observability.metrics import RunMetrics, record_run, to_dict


def test_run_metrics_defaults():
    m = RunMetrics(run_id="abc", started_at="2026-04-19T00:00:00")
    assert m.months_attempted == 0
    assert m.status == "running"
    assert m.licitaciones_nuevas == 0


def test_to_dict_roundtrip():
    m = RunMetrics(run_id="abc", started_at="x", months_ok=3)
    d = to_dict(m)
    assert d["run_id"] == "abc"
    assert d["months_ok"] == 3


def test_record_run_persists_success(tmp_db):
    db_mod, _ = tmp_db
    with record_run("run-ok") as m:
        m.months_attempted = 2
        m.months_ok = 2
        m.licitaciones_nuevas = 5
    with db_mod.connect() as c:
        row = c.execute(
            "SELECT status, months_ok, licitaciones_nuevas FROM extraction_runs WHERE run_id = ?",
            ("run-ok",),
        ).fetchone()
    assert row[0] == "ok"
    assert row[1] == 2
    assert row[2] == 5


def test_record_run_marks_partial(tmp_db):
    db_mod, _ = tmp_db
    with record_run("run-partial") as m:
        m.months_attempted = 2
        m.months_ok = 1
        m.months_failed = 1
    with db_mod.connect() as c:
        row = c.execute(
            "SELECT status FROM extraction_runs WHERE run_id = ?",
            ("run-partial",),
        ).fetchone()
    assert row[0] == "partial"


def test_record_run_marks_error_on_exception(tmp_db):
    db_mod, _ = tmp_db
    with pytest.raises(ValueError), record_run("run-err"):
        raise ValueError("boom")
    with db_mod.connect() as c:
        row = c.execute(
            "SELECT status FROM extraction_runs WHERE run_id = ?",
            ("run-err",),
        ).fetchone()
    assert row[0] == "error"
