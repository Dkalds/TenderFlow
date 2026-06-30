"""Tests de seed_negatives: distribución temporal de negativos (anti-leakage)."""

from __future__ import annotations

import scraper.ml_training as mt


def test_seed_negatives_spreads_across_months(monkeypatch) -> None:
    calls: list[tuple[int, int, int]] = []

    def fake_collect(year, month, limit, *, include_ti):
        calls.append((year, month, limit))
        return [], 0, 0

    monkeypatch.setattr(mt, "_collect_negatives_from_month", fake_collect)
    monkeypatch.setattr("db.database.init_db", lambda: None)

    result = mt.seed_negatives(year=2025, month=3, max_negatives=300, spread_months=3)

    # Tres meses hacia atrás desde el base, incluido.
    months = [(y, m) for y, m, _ in calls]
    assert months == [(2025, 3), (2025, 2), (2025, 1)]
    # Cupo repartido: 300 // 3 = 100 por mes.
    assert all(limit == 100 for _, _, limit in calls)
    assert result["inserted"] == 0


def test_seed_negatives_crosses_year_boundary(monkeypatch) -> None:
    calls: list[tuple[int, int, int]] = []

    def fake_collect(year, month, limit, *, include_ti):
        calls.append((year, month, limit))
        return [], 0, 0

    monkeypatch.setattr(mt, "_collect_negatives_from_month", fake_collect)
    monkeypatch.setattr("db.database.init_db", lambda: None)

    mt.seed_negatives(year=2025, month=1, max_negatives=200, spread_months=3)

    months = [(y, m) for y, m, _ in calls]
    assert months == [(2025, 1), (2024, 12), (2024, 11)]


def test_seed_negatives_single_month_backward_compat(monkeypatch) -> None:
    calls: list[tuple[int, int, int]] = []

    def fake_collect(year, month, limit, *, include_ti):
        calls.append((year, month, limit))
        return [], 0, 0

    monkeypatch.setattr(mt, "_collect_negatives_from_month", fake_collect)
    monkeypatch.setattr("db.database.init_db", lambda: None)

    mt.seed_negatives(year=2025, month=3, max_negatives=500)

    # spread_months=1 (default): un solo mes con el cupo completo.
    assert calls == [(2025, 3, 500)]
