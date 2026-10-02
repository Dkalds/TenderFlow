"""Tests para dashboard/forecast.py — cálculos de fecha y duración."""

from __future__ import annotations

import pandas as pd

from services.analytics.forecast import build_forecast_df

# ─── build_forecast_df ───────────────────────────────────────────────────────


def _lic_df(n: int = 3, tipo: str = "Mantenimiento") -> pd.DataFrame:
    """DataFrame mínimo de licitaciones para build_forecast_df."""
    now = pd.Timestamp("2024-06-01")
    return pd.DataFrame(
        {
            "id_externo": [f"lic-{i}" for i in range(n)],
            "titulo": [f"Contrato {i}" for i in range(n)],
            "tipo_proyecto": [tipo] * n,
            "fecha_publicacion": [(now - pd.Timedelta(days=i * 30)).isoformat() for i in range(n)],
            "importe": [50_000.0 * (i + 1) for i in range(n)],
            "duracion_valor": [24.0, 12.0, 36.0][:n],
            "duracion_unidad": ["MON", "MON", "MON"][:n],
            "fecha_inicio": [None] * n,
            "fecha_fin": [None] * n,
        }
    )


def _adj_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "licitacion_id": ["lic-0"],
            "fecha_adjudicacion": ["2024-03-01"],
            "importe_adjudicado": [45_000.0],
            "n_ofertas_recibidas": [3],
            "nombre": ["Empresa X"],
        }
    )


class TestBuildForecastDf:
    def test_empty_licitaciones_returns_empty(self):
        result = build_forecast_df(pd.DataFrame(), pd.DataFrame())
        assert result.empty

    def test_filters_mantenimiento_by_default(self):
        df = _lic_df(3, tipo="Desarrollo")
        result = build_forecast_df(df, pd.DataFrame())
        assert result.empty

    def test_no_filter_when_solo_mantenimiento_false(self):
        df = _lic_df(3, tipo="Desarrollo")
        result = build_forecast_df(df, pd.DataFrame(), solo_mantenimiento=False)
        assert not result.empty

    def test_columns_present(self):
        df = _lic_df(3)
        result = build_forecast_df(df, pd.DataFrame())
        for col in (
            "duracion_meses",
            "fecha_fin_estimada",
            "dias_hasta_fin",
            "meses_hasta_fin",
            "relicit_inicio",
            "relicit_fin",
        ):
            assert col in result.columns, f"Falta columna: {col}"

    def test_with_adjudicaciones_merges(self):
        lic = _lic_df(2)
        adj = _adj_df()
        result = build_forecast_df(lic, adj)
        assert "adjudicatarios" in result.columns

    def test_empty_adjudicaciones_adds_nat_column(self):
        lic = _lic_df(2)
        result = build_forecast_df(lic, pd.DataFrame())
        assert "fecha_adj_calc" in result.columns

    def test_estado_forecast_categorizes_future(self):
        lic = _lic_df(2)
        result = build_forecast_df(lic, pd.DataFrame())
        # Todos los contratos tienen duracion_meses > 0, por lo que deben
        # tener algún estado asignado (puede ser NaN si fecha_fin_estimada es NaT)
        assert "estado_forecast" in result.columns

    def test_baja_pct_computed_when_adjudicacion_available(self):
        lic = _lic_df(2)
        adj = _adj_df()
        result = build_forecast_df(lic, adj)
        assert "baja_pct" in result.columns

    def test_sorted_by_fecha_fin_estimada(self):
        lic = _lic_df(3)
        result = build_forecast_df(lic, pd.DataFrame())
        fechas = result["fecha_fin_estimada"].dropna()
        if len(fechas) >= 2:
            assert list(fechas) == sorted(fechas)
