"""SLA por fuente: frescura, latencia observada y degradación."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from services.source_health import get_source_freshness


def test_source_freshness_exposes_latency_and_stale_cursor():
    now = datetime.now(UTC)
    health_rows = [
        {
            "source": "placsp",
            "status": "success",
            "last_success_at": (now - timedelta(hours=2)).isoformat(),
            "last_seen_updated": now.isoformat(),
            "cursor_updated_at": now.isoformat(),
            "fetched": 10,
            "parsed": 8,
            "discarded": 2,
            "errors": 0,
        },
        {
            "source": "pscp_cat",
            "status": "failed",
            "last_success_at": (now - timedelta(hours=80)).isoformat(),
            "last_seen_updated": "2026-06-19T00:00:00+00:00",
            "cursor_updated_at": (now - timedelta(hours=80)).isoformat(),
            "fetched": 0,
            "parsed": 0,
            "discarded": 0,
            "errors": 1,
        },
    ]
    latency = [
        {
            "fuente": "placsp",
            "fecha_actualizacion_fuente": now.isoformat(),
            "fecha_extraccion": (now + timedelta(hours=3)).isoformat(),
        }
    ]

    with (
        patch(
            "services.source_health.SourceHealthRepository.list_health",
            return_value=health_rows,
        ),
        patch(
            "services.source_health.SourceHealthRepository.latency_samples",
            return_value=latency,
        ),
    ):
        result = get_source_freshness()

    placsp = next(source for source in result.sources if source.source == "placsp")
    pscp = next(source for source in result.sources if source.source == "pscp_cat")
    assert placsp.detected_within_24h_pct == 100.0
    assert placsp.sample_size == 1
    assert not placsp.is_degraded
    assert pscp.is_degraded
    assert pscp.warning is not None
    assert result.healthy_sources_pct == 50.0
