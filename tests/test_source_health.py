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


def _fila(source: str, status: str, exito_hace_h: float | None) -> dict[str, object]:
    ahora = datetime.now(UTC)
    return {
        "source": source,
        "status": status,
        "last_started_at": ahora.isoformat(),
        "last_success_at": (
            None if exito_hace_h is None else (ahora - timedelta(hours=exito_hace_h)).isoformat()
        ),
        "fetched": 0,
        "parsed": 0,
        "discarded": 0,
        "errors": 0,
    }


def _frescura(filas: list[dict[str, object]]):
    with (
        patch("services.source_health.SourceHealthRepository.list_health", return_value=filas),
        patch("services.source_health.SourceHealthRepository.latency_samples", return_value=[]),
    ):
        return get_source_freshness()


def test_los_lotes_historicos_no_cuentan_como_fuentes():
    """Un ``bulk_YYYYMM`` es la carga de un mes, no una fuente que vigilar.

    En producción había cuatro (uno fallido, dos «ejecutándose» desde hacía
    meses, uno terminado en septiembre) y dejaban la celda «Fuentes al día» en
    7 de 11 para siempre: un aviso que no se apaga deja de leerse.
    """
    result = _frescura(
        [
            _fila("placsp", "success", 2),
            _fila("bulk_202607", "failed", None),
            _fila("bulk_202608", "running", None),
            _fila("placsp_watched_company_awards_bulk_202606", "success", 300),
        ]
    )

    por_id = {s.source: s for s in result.sources}
    assert not por_id["placsp"].is_backfill
    for lote in ("bulk_202607", "bulk_202608", "placsp_watched_company_awards_bulk_202606"):
        assert por_id[lote].is_backfill, lote
        assert not por_id[lote].is_degraded, lote
    assert (result.healthy_sources, result.total_sources) == (1, 1)
    assert result.healthy_sources_pct == 100.0


def test_un_lote_fallido_conserva_su_estado():
    """Que no cuente no significa que se esconda: su estado viaja tal cual."""
    result = _frescura([_fila("bulk_202607", "failed", None)])

    assert result.sources[0].status == "failed"
    assert (result.healthy_sources, result.total_sources) == (0, 0)


def test_cada_fuente_se_mide_contra_el_sla_de_su_registro():
    """Las RSS regionales son semanales: 60 h sin run no es una degradación.

    El panel usaba 36 h para todas mientras el healthcheck —el que avisa— usa el
    ``max_lag_hours`` de cada una: Ops marcaba en rojo lo que nadie iba a alertar.
    """
    result = _frescura(
        [
            _fila("galicia_rss", "success", 60),
            _fila("placsp", "success", 60),
            _fila("conector_sin_registrar", "success", 60),
        ]
    )

    por_id = {s.source: s for s in result.sources}
    assert not por_id["galicia_rss"].is_degraded
    assert por_id["placsp"].is_degraded
    # Sin registro no hay SLA propio: se queda con el umbral del carril diario.
    assert por_id["conector_sin_registrar"].is_degraded
