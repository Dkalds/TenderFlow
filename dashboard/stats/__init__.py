"""Paquete de estadísticas — re-exporta todo desde _base para backward compat.

Uso: ``from dashboard.stats import kpis, por_mes, ...``

Submódulos disponibles para imports directos:
  - dashboard.stats.competencia
  - dashboard.stats.geografia
  - dashboard.stats.forecasting
  - dashboard.stats.scoring
  - dashboard.stats.kpis
  - dashboard.stats.salud
  - dashboard.stats.modulos
  - dashboard.stats.dedupe
"""

from dashboard.stats._base import (  # noqa: F401
    _STRIP_RE,
    _build_searchable_text,
    _keywords_mask,
    _normalize_titulo,
    calidad_dato,
    calientes_hoy,
    ccaa_mas_activa,
    compare_periods,
    concentracion_geografica,
    dedupe_reaperturas,
    funnel_estados,
    hhi_concentracion,
    importe_medio_por_modulo,
    indice_novedad,
    is_anomaly,
    kpi_sparkline_series,
    kpis,
    kpis_organo,
    lead_time_medio,
    load_dataframe,
    media_movil,
    mes_pico,
    pct_multi_modulo,
    pct_oferta_unica,
    por_cpv,
    por_estado,
    por_mes,
    portfolio_match,
    ratio_relicitacion,
    risk_flags,
    score_oportunidad,
    tasa_anulacion,
    tasa_conversion_organo,
    ticket_medio_por_plataforma,
    top_modulo_yoy,
    top_organos,
    velocity_funnel,
    vencen_en,
    ventana_anticipacion,
    yoy_delta,
)

__all__ = [
    "calidad_dato",
    "calientes_hoy",
    "ccaa_mas_activa",
    "compare_periods",
    "concentracion_geografica",
    "dedupe_reaperturas",
    "funnel_estados",
    "hhi_concentracion",
    "importe_medio_por_modulo",
    "indice_novedad",
    "is_anomaly",
    "kpi_sparkline_series",
    "kpis",
    "kpis_organo",
    "lead_time_medio",
    "load_dataframe",
    "media_movil",
    "mes_pico",
    "pct_multi_modulo",
    "pct_oferta_unica",
    "por_cpv",
    "por_estado",
    "por_mes",
    "portfolio_match",
    "ratio_relicitacion",
    "risk_flags",
    "score_oportunidad",
    "tasa_anulacion",
    "tasa_conversion_organo",
    "ticket_medio_por_plataforma",
    "top_modulo_yoy",
    "top_organos",
    "velocity_funnel",
    "vencen_en",
    "ventana_anticipacion",
    "yoy_delta",
]
