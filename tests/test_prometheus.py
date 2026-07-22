"""Tests para el writer Prometheus del scraper."""

from __future__ import annotations

from observability import prometheus


def test_text_metrics_include_empresa_resolution_snapshot(monkeypatch, tmp_path):
    metrics_file = tmp_path / "scraper.prom"
    monkeypatch.setattr(prometheus, "_METRICS_DIR", tmp_path)
    monkeypatch.setattr(prometheus, "_METRICS_FILE", metrics_file)
    monkeypatch.setattr(
        prometheus,
        "_empresa_resolution_snapshot",
        lambda: (75, 25),
    )
    monkeypatch.setattr("db.database.count_licitaciones", lambda: 10)

    prometheus._write_text_file(prometheus.RunInstrumentation(source="test"))

    content = metrics_file.read_text(encoding="utf-8")
    assert "tenderflow_adjudicaciones_empresa_enlazadas 75" in content
    assert "tenderflow_adjudicaciones_empresa_pendientes 25" in content
