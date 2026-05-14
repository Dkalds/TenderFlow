"""Tests para scheduler.anomaly_alerts."""

from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import pytest


# ── helpers de datos de test ────────────────────────────────────────────


def _make_lic(importe: float | None = 100_000.0, organo: str = "Org A") -> dict:
    return {
        "id_externo": "TEST-001",
        "titulo": "Sistema SAP test",
        "organo_contratacion": organo,
        "importe": importe,
    }


def _make_adj(imp_lic: float, imp_adj: float) -> dict:
    return {
        "licitacion_id": "TEST-001",
        "titulo": "Sistema SAP test",
        "nombre": "Empresa Test SL",
        "importe_licitacion": imp_lic,
        "importe_adjudicado": imp_adj,
    }


# ── check_importe_anomalo ────────────────────────────────────────────────


class TestCheckImporteAnomalo:
    def test_detecta_importe_alto(self):
        from scheduler.anomaly_alerts import check_importe_anomalo

        lics = [_make_lic(importe=10_000_000.0)]
        # Simular historial con media=100k, std=10k → threshold ≈ 120k con sigma=2
        with patch("scheduler.anomaly_alerts._query_historico_organo", return_value=(100_000.0, 10_000.0)):
            alerts = check_importe_anomalo(lics, sigma=2.0)
        assert len(alerts) == 1
        assert "anómalo" in alerts[0].lower() or "anomal" in alerts[0].lower()

    def test_no_alerta_importe_normal(self):
        from scheduler.anomaly_alerts import check_importe_anomalo

        lics = [_make_lic(importe=110_000.0)]
        with patch("scheduler.anomaly_alerts._query_historico_organo", return_value=(100_000.0, 10_000.0)):
            alerts = check_importe_anomalo(lics, sigma=2.0)
        # 110k < 100k + 2*10k = 120k → no alerta
        assert len(alerts) == 0

    def test_sin_muestras_suficientes_no_alerta(self):
        from scheduler.anomaly_alerts import check_importe_anomalo

        lics = [_make_lic(importe=999_999.0)]
        with patch("scheduler.anomaly_alerts._query_historico_organo", return_value=(0.0, 0.0)):
            alerts = check_importe_anomalo(lics, sigma=2.0)
        assert len(alerts) == 0

    def test_importe_none_ignorado(self):
        from scheduler.anomaly_alerts import check_importe_anomalo

        lics = [_make_lic(importe=None)]
        with patch("scheduler.anomaly_alerts._query_historico_organo", return_value=(100_000.0, 10_000.0)):
            alerts = check_importe_anomalo(lics, sigma=2.0)
        assert len(alerts) == 0


# ── check_baja_temeraria ─────────────────────────────────────────────────


class TestCheckBajaTemeraria:
    def test_detecta_baja_alta(self):
        from scheduler.anomaly_alerts import check_baja_temeraria

        # 90% de baja
        adjs = [_make_adj(imp_lic=1_000_000.0, imp_adj=100_000.0)]
        alerts = check_baja_temeraria(adjs, threshold_pct=80.0)
        assert len(alerts) == 1
        assert "80" in alerts[0] or "90" in alerts[0]

    def test_no_alerta_baja_normal(self):
        from scheduler.anomaly_alerts import check_baja_temeraria

        # 20% de baja
        adjs = [_make_adj(imp_lic=1_000_000.0, imp_adj=800_000.0)]
        alerts = check_baja_temeraria(adjs, threshold_pct=80.0)
        assert len(alerts) == 0

    def test_exactamente_en_umbral(self):
        from scheduler.anomaly_alerts import check_baja_temeraria

        # exactamente 80%
        adjs = [_make_adj(imp_lic=1_000_000.0, imp_adj=200_000.0)]
        alerts = check_baja_temeraria(adjs, threshold_pct=80.0)
        assert len(alerts) == 1

    def test_importe_cero_ignorado(self):
        from scheduler.anomaly_alerts import check_baja_temeraria

        adjs = [_make_adj(imp_lic=0.0, imp_adj=0.0)]
        alerts = check_baja_temeraria(adjs, threshold_pct=80.0)
        assert len(alerts) == 0


# ── check_spike_publicaciones ────────────────────────────────────────────


class TestCheckSpikePublicaciones:
    def test_detecta_spike(self):
        from scheduler.anomaly_alerts import check_spike_publicaciones

        with (
            patch("scheduler.anomaly_alerts._query_volumen_diario_30d", return_value=10.0),
            patch("scheduler.anomaly_alerts._query_volumen_hoy", return_value=50),
        ):
            alerts = check_spike_publicaciones(factor=3.0)
        assert len(alerts) == 1

    def test_no_spike_normal(self):
        from scheduler.anomaly_alerts import check_spike_publicaciones

        with (
            patch("scheduler.anomaly_alerts._query_volumen_diario_30d", return_value=10.0),
            patch("scheduler.anomaly_alerts._query_volumen_hoy", return_value=15),
        ):
            alerts = check_spike_publicaciones(factor=3.0)
        assert len(alerts) == 0

    def test_sin_historial_no_alerta(self):
        from scheduler.anomaly_alerts import check_spike_publicaciones

        with patch("scheduler.anomaly_alerts._query_volumen_diario_30d", return_value=0.0):
            alerts = check_spike_publicaciones(factor=3.0)
        assert len(alerts) == 0


# ── run_anomaly_checks ───────────────────────────────────────────────────


class TestRunAnomalyChecks:
    def test_disabled_returns_zero(self, monkeypatch):
        from config import settings
        monkeypatch.setattr(settings, "ANOMALY_ALERT_ENABLED", False)
        from scheduler.anomaly_alerts import run_anomaly_checks

        result = run_anomaly_checks()
        assert result == 0

    def test_runs_all_checks(self, monkeypatch):
        from config import settings
        monkeypatch.setattr(settings, "ANOMALY_ALERT_ENABLED", True)
        monkeypatch.setattr(settings, "ANOMALY_IMPORTE_SIGMA", 2.0)
        monkeypatch.setattr(settings, "ANOMALY_BAJA_THRESHOLD", 80.0)
        monkeypatch.setattr(settings, "ANOMALY_SPIKE_FACTOR", 3.0)

        with (
            patch("scheduler.anomaly_alerts._query_licitaciones_nuevas_hoy", return_value=[]),
            patch("scheduler.anomaly_alerts._query_adjudicaciones_recientes", return_value=[]),
            patch("scheduler.anomaly_alerts.check_spike_publicaciones", return_value=[]),
        ):
            from scheduler.anomaly_alerts import run_anomaly_checks
            result = run_anomaly_checks()
        assert result == 0

    def test_sends_alert_when_anomalies(self, monkeypatch):
        from config import settings
        monkeypatch.setattr(settings, "ANOMALY_ALERT_ENABLED", True)
        monkeypatch.setattr(settings, "ANOMALY_IMPORTE_SIGMA", 2.0)
        monkeypatch.setattr(settings, "ANOMALY_BAJA_THRESHOLD", 80.0)
        monkeypatch.setattr(settings, "ANOMALY_SPIKE_FACTOR", 3.0)

        notify_mock = MagicMock()
        with (
            patch("scheduler.anomaly_alerts._query_licitaciones_nuevas_hoy", return_value=[]),
            patch("scheduler.anomaly_alerts._query_adjudicaciones_recientes", return_value=[]),
            patch("scheduler.anomaly_alerts.check_spike_publicaciones", return_value=["spike!"]),
            patch("scheduler.anomaly_alerts.notify", notify_mock),
        ):
            from scheduler.anomaly_alerts import run_anomaly_checks
            result = run_anomaly_checks()

        assert result == 1
        notify_mock.assert_called_once()
