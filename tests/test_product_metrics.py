"""Las métricas de producto usan denominadores de outcome explícitos."""

from services.product_metrics import build_product_status


def test_product_status_uses_resolved_outcomes_for_win_rate():
    rows = [
        {
            "organization_id": 7,
            "organization_name": "Equipo",
            "id": 1,
            "outcome": "won",
            "submitted_at": "2026-07-01T00:00:00+00:00",
            "awarded_amount_eur": 120_000,
            "identified_at": "2026-06-29T00:00:00+00:00",
            "decision_at": "2026-06-30T00:00:00+00:00",
        },
        {
            "organization_id": 7,
            "organization_name": "Equipo",
            "id": 2,
            "outcome": "pending",
            "submitted_at": None,
            "awarded_amount_eur": None,
            "identified_at": "2026-07-02T00:00:00+00:00",
            "decision_at": None,
        },
    ]

    result = build_product_status(rows)

    assert result.totals.pursuits_identified == 2
    assert result.totals.win_rate == 1.0
    assert result.totals.awarded_amount_eur == 120_000
    assert result.totals.median_decision_time_hours == 24
