"""KPI bar del dashboard — extraído de app.py para reutilización y tests."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.components.icons import icon
from dashboard.components.kpi import kpi_card
from dashboard.kpi_config import KPI_FORMULAS
from dashboard.utils.format import fmt_eur


@st.cache_data(show_spinner=False)
def _compute_kpis_cached(
    n_rows: int,
    importe_total: float,
    importe_medio: float,
    n_organos: int,
    n_ccaa: int,
    delta_n: int,
    delta_pct: float,
    prev30_size: int,
) -> dict[str, float | int]:
    """Capa de caché sobre los KPIs ya calculados (evita recálculo en reruns)."""
    return {
        "total": n_rows,
        "importe_total": importe_total,
        "importe_medio": importe_medio,
        "n_organos": n_organos,
        "n_ccaa": n_ccaa,
        "delta_n": delta_n,
        "delta_pct": delta_pct,
        "prev30_size": prev30_size,
    }


def compute_kpis(df: pd.DataFrame) -> dict[str, float | int]:
    """Calcula los KPIs principales sobre el dataframe filtrado."""
    total = len(df)
    if total == 0:
        return {
            "total": 0,
            "importe_total": 0.0,
            "importe_medio": 0.0,
            "n_organos": 0,
            "n_ccaa": 0,
            "delta_n": 0,
            "delta_pct": 0,
            "prev30_size": 0,
        }

    importe_total = float(df["importe"].sum(skipna=True))
    importe_medio = float(df["importe"].mean(skipna=True) or 0)
    n_organos = int(df["organo_contratacion"].nunique())
    n_ccaa = int(df["ccaa"].nunique())

    hoy = pd.Timestamp.now(tz="UTC")
    fpub = df["fecha_publicacion"]
    if getattr(fpub.dt, "tz", None) is None:
        hoy = hoy.tz_localize(None)
    ult30 = df[fpub >= (hoy - pd.Timedelta(days=30))]
    prev30 = df[(fpub < (hoy - pd.Timedelta(days=30))) & (fpub >= (hoy - pd.Timedelta(days=60)))]
    delta_n = len(ult30) - len(prev30)
    delta_pct = (delta_n / len(prev30) * 100) if len(prev30) else 0.0

    # Delegar a capa cacheada para evitar recálculo en reruns de Streamlit
    return _compute_kpis_cached(
        n_rows=total,
        importe_total=importe_total,
        importe_medio=importe_medio,
        n_organos=n_organos,
        n_ccaa=n_ccaa,
        delta_n=delta_n,
        delta_pct=delta_pct,
        prev30_size=len(prev30),
    )


@st.cache_data(show_spinner=False)
def _last_12m_series(df: pd.DataFrame, value_col: str | None = None) -> list[float]:
    """Devuelve la serie agregada por mes de los últimos 12 meses.

    Si `value_col` es None cuenta filas; si se proporciona suma esa columna.
    Pensado para alimentar el sparkline inline de las KPI cards.
    """
    if df.empty or "fecha_publicacion" not in df.columns:
        return []
    fpub = df["fecha_publicacion"]
    hoy = pd.Timestamp.now(tz="UTC")
    if getattr(fpub.dt, "tz", None) is None:
        hoy = hoy.tz_localize(None)
    desde = hoy - pd.DateOffset(months=12)
    sub = df[fpub >= desde].copy()
    if sub.empty:
        return []
    sub["_mes"] = sub["fecha_publicacion"].dt.to_period("M")
    if value_col and value_col in sub.columns:
        s = sub.groupby("_mes")[value_col].sum(min_count=1).fillna(0)
    else:
        s = sub.groupby("_mes").size()
    # Reindexar para incluir meses vacíos (continuidad visual del sparkline)
    full_idx = pd.period_range(end=hoy.to_period("M"), periods=12, freq="M")
    s = s.reindex(full_idx, fill_value=0)
    return [float(v) for v in s.tolist()]


@st.fragment
def render_kpi_bar(df: pd.DataFrame) -> None:
    """Renderiza la barra de 5 KPIs con tooltips, sparklines e iconos SVG."""
    k = compute_kpis(df)
    spark_count = _last_12m_series(df) or None
    spark_imp = _last_12m_series(df, value_col="importe") or None
    delta_up = k["delta_n"] >= 0
    delta_txt = f"{k['delta_pct']:+.0f}% últ. 30d" if k["prev30_size"] else "sin comparativa"

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.markdown(
            kpi_card(
                "Licitaciones SAP",
                f"{k['total']:,}",
                delta=delta_txt,
                delta_up=delta_up,
                icon=icon("layout-dashboard", 18),
                sparkline=spark_count,
                tooltip=KPI_FORMULAS.get("licitaciones_30d"),
            ),
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            kpi_card(
                "Importe total",
                fmt_eur(k["importe_total"]),
                icon=icon("euro", 18),
                sparkline=spark_imp,
                tooltip=KPI_FORMULAS.get("importe_30d"),
            ),
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            kpi_card(
                "Importe medio",
                fmt_eur(k["importe_medio"]),
                icon=icon("trending-up", 18),
                tooltip="Importe medio por licitación en el rango filtrado.",
            ),
            unsafe_allow_html=True,
        )
    with c4:
        st.markdown(
            kpi_card(
                "Órganos distintos",
                f"{k['n_organos']}",
                icon=icon("building-2", 18),
                tooltip="Número de órganos de contratación distintos en el rango filtrado.",
            ),
            unsafe_allow_html=True,
        )
    with c5:
        st.markdown(
            kpi_card(
                "CCAA cubiertas",
                f"{k['n_ccaa']}/17",
                icon=icon("map", 18),
                tooltip="Comunidades autónomas con al menos una licitación en el rango filtrado.",
            ),
            unsafe_allow_html=True,
        )
