"""KPI bar del dashboard — extraído de app.py para reutilización y tests."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from dashboard.components.icons import icon
from dashboard.components.kpi import kpi_card
from dashboard.kpi_config import KPI_FORMULAS
from dashboard.utils.dates import month_period
from dashboard.utils.format import fmt_eur


@st.cache_data(show_spinner=False, persist="disk")
def compute_kpis(df: pd.DataFrame) -> dict[str, float | int]:
    """Calcula los KPIs principales sobre el dataframe filtrado.

    Usa Polars para las agregaciones cuando está disponible (2-5× más rápido).
    Cae a pandas si Polars no está instalado.
    """
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

    try:
        import polars as pl

        now_utc = pd.Timestamp.now(tz="UTC")
        # Normalizar timezone del dataframe: Polars requiere consistencia
        fpub = df["fecha_publicacion"]
        if getattr(fpub.dt, "tz", None) is None:
            t30_back = now_utc.tz_localize(None) - pd.Timedelta(days=30)
            t60_back = now_utc.tz_localize(None) - pd.Timedelta(days=60)
        else:
            t30_back = now_utc - pd.Timedelta(days=30)
            t60_back = now_utc - pd.Timedelta(days=60)

        pl_df = pl.from_pandas(df[["importe", "organo_contratacion", "ccaa", "fecha_publicacion"]])

        aggs = pl_df.select(
            pl.col("importe").sum().alias("importe_total"),
            pl.col("importe").mean().alias("importe_medio"),
            pl.col("organo_contratacion").n_unique().alias("n_organos"),
            pl.col("ccaa").n_unique().alias("n_ccaa"),
        ).row(0)
        importe_total, importe_medio, n_organos, n_ccaa = aggs

        # Ventanas temporales en pandas (más simple para dates con tz)
        ult30_n = int((fpub >= t30_back).sum())
        prev30_n = int(((fpub < t30_back) & (fpub >= t60_back)).sum())
    except ImportError:
        # Polars no instalado — pandas puro
        importe_total = float(df["importe"].sum(skipna=True))
        importe_medio = float(df["importe"].mean(skipna=True) or 0)
        n_organos = int(df["organo_contratacion"].nunique())
        n_ccaa = int(df["ccaa"].nunique())
        hoy = pd.Timestamp.now(tz="UTC")
        fpub = df["fecha_publicacion"]
        if getattr(fpub.dt, "tz", None) is None:
            hoy = hoy.tz_localize(None)
        t30_back = hoy - pd.Timedelta(days=30)
        t60_back = hoy - pd.Timedelta(days=60)
        ult30_n = int((fpub >= t30_back).sum())
        prev30_n = int(((fpub < t30_back) & (fpub >= t60_back)).sum())

    delta_n = ult30_n - prev30_n
    delta_pct = (delta_n / prev30_n * 100) if prev30_n else 0.0
    return {
        "total": total,
        "importe_total": float(importe_total or 0),
        "importe_medio": float(importe_medio or 0),
        "n_organos": int(n_organos),
        "n_ccaa": int(n_ccaa),
        "delta_n": delta_n,
        "delta_pct": delta_pct,
        "prev30_size": prev30_n,
    }


@st.cache_data(ttl=60, show_spinner=False)
def _load_precomputed_kpis() -> dict[str, Any]:
    """Lee snapshots globales de KPI si existen; falla en silencio."""
    try:
        from scheduler.kpi_precompute import get_all_latest

        return get_all_latest()
    except Exception:
        return {}


def _snapshot_kpis(snapshot: dict[str, Any], expected_rows: int) -> dict[str, float | int] | None:
    """Adapta un snapshot global al contrato de ``compute_kpis``.

    Solo se usa si el total del snapshot coincide con el DataFrame recibido.
    Eso evita mostrar KPIs globales cuando el usuario tiene filtros activos.
    """
    total = snapshot.get("total_licitaciones")
    if total is None or int(total) != expected_rows:
        return None
    cur30 = int(snapshot.get("licitaciones_30d") or 0)
    prev30 = int(snapshot.get("licitaciones_30d_prev") or 0)
    delta_n = cur30 - prev30
    return {
        "total": int(total),
        "importe_total": float(snapshot.get("importe_total") or 0.0),
        "importe_medio": float(snapshot.get("importe_medio") or 0.0),
        "n_organos": int(snapshot.get("n_organos") or 0),
        "n_ccaa": int(snapshot.get("n_ccaa") or 0),
        "delta_n": delta_n,
        "delta_pct": (delta_n / prev30 * 100) if prev30 else 0.0,
        "prev30_size": prev30,
    }


@st.cache_data(show_spinner=False, persist="disk")
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
    sub["_mes"] = month_period(sub["fecha_publicacion"])
    if value_col and value_col in sub.columns:
        s = sub.groupby("_mes")[value_col].sum(min_count=1).fillna(0)
    else:
        s = sub.groupby("_mes").size()
    # Reindexar para incluir meses vacíos (continuidad visual del sparkline)
    full_idx = pd.period_range(end=hoy.to_period("M"), periods=12, freq="M")
    s = s.reindex(full_idx, fill_value=0)
    return [float(v) for v in s.tolist()]


def _snapshot_series(snapshot: dict[str, Any], key: str) -> list[float] | None:
    serie = snapshot.get("serie_mensual_24m")
    if not isinstance(serie, list):
        return None
    tail = serie[-12:]
    values = [float(item.get(key) or 0.0) for item in tail if isinstance(item, dict)]
    return values or None


def _analytics_freshness_caption() -> str | None:
    """Devuelve el texto de frescura del snapshot Parquet, o ``None`` si no hay manifest.

    Lee ``generated_at`` de ``DATA_DIR/parquet/_manifest.json`` (RFC 086).
    No lanza excepciones — si el manifest no existe o falla la lectura, no se
    muestra ningún indicador.
    """
    try:
        from datetime import datetime

        from config import settings
        from shared.parquet_manifest import read_manifest

        manifest_path = settings.DATA_DIR / "parquet" / "_manifest.json"
        manifest = read_manifest(manifest_path)
        if manifest is None:
            return None
        ts = datetime.fromisoformat(manifest.generated_at)
        return f"Datos analíticos a las {ts.strftime('%H:%M')}"
    except Exception:
        return None


@st.fragment
def render_kpi_bar(df: pd.DataFrame) -> None:
    """Renderiza la barra de 5 KPIs con tooltips, sparklines e iconos SVG."""
    snapshot = _load_precomputed_kpis()
    snapshot_k = _snapshot_kpis(snapshot, len(df))
    k = snapshot_k or compute_kpis(df)
    spark_count = _snapshot_series(snapshot, "n") if snapshot_k is not None else None
    spark_imp = _snapshot_series(snapshot, "importe") if snapshot_k is not None else None
    spark_count = spark_count or _last_12m_series(df) or None
    spark_imp = spark_imp or _last_12m_series(df, value_col="importe") or None
    delta_up = k["delta_n"] >= 0
    delta_txt = f"{k['delta_pct']:+.0f}% últ. 30d" if k["prev30_size"] else "sin comparativa"

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.markdown(
            kpi_card(
                "Licitaciones",
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
                tooltip=(
                    "Media aritmética del importe de licitación (sin IVA) "
                    "sobre todas las licitaciones en el rango filtrado. "
                    "Fórmula: Importe total / Nº licitaciones con importe informado."
                ),
            ),
            unsafe_allow_html=True,
        )
    with c4:
        st.markdown(
            kpi_card(
                "Órganos distintos",
                f"{k['n_organos']}",
                icon=icon("building-2", 18),
                tooltip=(
                    "Número de órganos de contratación únicos que han publicado "
                    "al menos una licitación en el rango filtrado. "
                    "Un mismo organismo puede publicar múltiples licitaciones."
                ),
            ),
            unsafe_allow_html=True,
        )
    with c5:
        st.markdown(
            kpi_card(
                "CCAA cubiertas",
                f"{k['n_ccaa']}/17",
                icon=icon("map", 18),
                tooltip=(
                    "Comunidades autónomas con al menos una licitación en el rango filtrado. "
                    "El total posible es 17 (sin contar Ceuta y Melilla). "
                    "Una CCAA se asigna por el código NUTS3 del órgano contratante."
                ),
            ),
            unsafe_allow_html=True,
        )

    freshness = _analytics_freshness_caption()
    if freshness:
        st.caption(freshness)
