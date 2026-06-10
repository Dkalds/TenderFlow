"""Cálculo de estadísticas a partir de la BD."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd

from config import settings
from dashboard.utils.dates import month_start
from observability.logging import get_logger
from services.licitaciones import load_stats_dataframe as svc_load_stats

log = get_logger(__name__)

try:  # pragma: no cover - fallback when Streamlit runtime no disponible
    import streamlit as _st

    _cache_resource = _st.cache_resource(ttl=settings.DASHBOARD_CACHE_TTL or None)
except Exception:  # pragma: no cover

    def _cache_resource(fn: Callable[..., Any]) -> Callable[..., Any]:  # type: ignore[misc]
        return fn


@_cache_resource
def load_dataframe() -> pd.DataFrame:
    """Carga ligera de licitaciones (sin enriquecimiento del dashboard).

    Delega en la capa de servicios. Para la versión enriquecida con
    clasificadores y caché Streamlit, usar ``dashboard.data_loader.load_dataframe``.

    Cacheada con ``@st.cache_resource`` (TTL = ``DASHBOARD_CACHE_TTL``): se reutiliza
    entre sesiones y reruns. Los consumidores no deben mutar el objeto retornado.
    """
    rows = svc_load_stats()
    df = pd.DataFrame(rows)
    if not df.empty:
        df["fecha_publicacion"] = pd.to_datetime(
            df["fecha_publicacion"],
            errors="coerce",
            utc=True,
        )
        df["importe"] = pd.to_numeric(df["importe"], errors="coerce")
    return df


def kpis(df: pd.DataFrame) -> dict[str, float | int]:
    if df.empty:
        return {"total": 0, "importe_total": 0, "importe_medio": 0, "organos": 0}
    return {
        "total": len(df),
        "importe_total": float(df["importe"].sum(skipna=True)),
        "importe_medio": float(df["importe"].mean(skipna=True) or 0),
        "organos": df["organo_contratacion"].nunique(),
    }


def por_mes(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or df["fecha_publicacion"].isna().all():
        return pd.DataFrame(columns=["mes", "n_licitaciones", "importe"])
    g = (
        df.dropna(subset=["fecha_publicacion"])
        .assign(mes=lambda x: month_start(x["fecha_publicacion"]))
        .groupby("mes")
        .agg(n_licitaciones=("id_externo", "count"), importe=("importe", "sum"))
        .reset_index()
    )
    return g


def top_organos(df: pd.DataFrame, n: int = 15) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["organo_contratacion", "n", "importe"])
    g = (
        df.groupby("organo_contratacion")
        .agg(n=("id_externo", "count"), importe=("importe", "sum"))
        .sort_values("n", ascending=False)
        .head(n)
        .reset_index()
    )
    return g


def por_estado(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["estado", "n"])
    return df.groupby("estado").size().reset_index(name="n").sort_values("n", ascending=False)


def por_cpv(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["cpv", "n"])
    return df.groupby("cpv").size().reset_index(name="n").sort_values("n", ascending=False).head(n)


# ── Nuevas funciones de KPIs ────────────────────────────────────────────


def yoy_delta(
    df: pd.DataFrame, col: str, agg: str = "count", days: int = 30
) -> tuple[float, float, float]:
    """Calcula valor actual (últimos *days* días), anterior, y % cambio.

    Returns (valor_actual, valor_anterior, pct_cambio).
    """
    hoy = pd.Timestamp.now("UTC")
    ult = df[df["fecha_publicacion"] >= (hoy - pd.Timedelta(days=days))]
    prev = df[
        (df["fecha_publicacion"] < (hoy - pd.Timedelta(days=days)))
        & (df["fecha_publicacion"] >= (hoy - pd.Timedelta(days=days * 2)))
    ]

    v_act: float
    v_prev: float
    if agg == "count":
        v_act = float(len(ult))
        v_prev = float(len(prev))
    elif agg == "sum":
        v_act = float(ult[col].sum(skipna=True))
        v_prev = float(prev[col].sum(skipna=True))
    elif agg == "mean":
        v_act = float(ult[col].mean(skipna=True) or 0)
        v_prev = float(prev[col].mean(skipna=True) or 0)
    elif agg == "nunique":
        v_act = float(ult[col].nunique())
        v_prev = float(prev[col].nunique())
    else:
        v_act = v_prev = 0

    pct = ((v_act - v_prev) / v_prev * 100) if v_prev else 0
    return v_act, v_prev, pct


def tasa_anulacion(df: pd.DataFrame) -> float:
    """% de licitaciones anuladas sobre el total (últimos 12 meses)."""
    hoy = pd.Timestamp.now("UTC")
    ult12 = df[df["fecha_publicacion"] >= (hoy - pd.Timedelta(days=365))]
    if ult12.empty:
        return 0.0
    return float((ult12["estado"] == "ANUL").sum() / len(ult12) * 100)


def lead_time_medio(adj_df: pd.DataFrame) -> float | None:
    """Días promedio desde publicación hasta adjudicación."""
    if adj_df.empty:
        return None
    fp = pd.to_datetime(adj_df["fecha_publicacion"], errors="coerce", utc=True)
    fa = pd.to_datetime(adj_df["fecha_adjudicacion"], errors="coerce")
    # Alinear timezones
    if hasattr(fp.dt, "tz"):
        fp = fp.dt.tz_localize(None)
    diff = (fa - fp).dt.days
    valid = diff[diff > 0]
    if valid.empty:
        return None
    return float(valid.median())


def funnel_estados(df: pd.DataFrame) -> pd.DataFrame:
    """Funnel de conversión por estado del proceso de contratación."""
    order = ["PUB", "EV", "RES", "ADJ", "ANUL"]
    counts = df["estado"].value_counts()
    total = len(df)
    rows = []
    for est in order:
        n = int(counts.get(est, 0))
        rows.append(
            {
                "estado": est,
                "n": n,
                "pct": (n / total * 100) if total else 0,
            }
        )
    return pd.DataFrame(rows)


def hhi_concentracion(adj_df: pd.DataFrame, group_col: str = "empresa_key") -> float:
    """Índice Herfindahl-Hirschman (0-10000) sobre importe adjudicado."""
    if adj_df.empty or "importe_adjudicado" not in adj_df.columns:
        return 0.0
    shares = adj_df.groupby(group_col)["importe_adjudicado"].sum()
    total = shares.sum()
    if total <= 0:
        return 0.0
    pct = shares / total * 100
    return float((pct**2).sum())


def pct_oferta_unica(adj_df: pd.DataFrame) -> float:
    """% de adjudicaciones con una sola oferta recibida."""
    with_data = adj_df.dropna(subset=["n_ofertas_recibidas"])
    if with_data.empty:
        return 0.0
    return float((with_data["n_ofertas_recibidas"] == 1).sum() / len(with_data) * 100)


def media_movil(series: pd.Series, window: int = 3) -> pd.Series:
    """Media móvil simple."""
    return series.rolling(window=window, min_periods=1).mean()


def ventana_anticipacion(df: pd.DataFrame) -> float | None:
    """Días medianos entre publicación y fin de contrato (anticipación comercial).

    Mide cuánto tiempo tiene el equipo comercial desde que sale la licitación
    hasta que el contrato termina. Valores altos = más margen de preparación.
    """
    if df.empty or "fecha_fin_contrato" not in df.columns:
        return None
    fp = pd.to_datetime(df["fecha_publicacion"], errors="coerce", utc=True)
    ff = pd.to_datetime(df["fecha_fin_contrato"], errors="coerce", utc=True)
    if fp.dt.tz is not None:
        fp = fp.dt.tz_localize(None)
    if ff.dt.tz is not None:
        ff = ff.dt.tz_localize(None)
    diff = (ff - fp).dt.days
    valid = diff[diff > 0]
    if valid.empty:
        return None
    return float(valid.median())


def indice_novedad(df: pd.DataFrame, df_adj: pd.DataFrame) -> float:
    """% de licitaciones cuyo (órgano, CPV a 2 dígitos) no tiene histórico de adjudicación.

    Útil para identificar "mercados vírgenes" donde aún no hay proveedor instalado.
    """
    if df.empty:
        return 0.0
    df_c = df.copy()
    df_c["_cpv2"] = df_c["cpv"].astype(str).str[:2]

    if df_adj.empty or "licitacion_id" not in df_adj.columns:
        return 100.0  # todo es "nuevo" si no hay histórico

    # Construir set de (órgano, cpv2) con histórico de adjudicación
    hist = df_adj.merge(
        df_c[["id_externo", "organo_contratacion", "_cpv2"]],
        left_on="licitacion_id",
        right_on="id_externo",
        how="inner",
    ).dropna(subset=["organo_contratacion", "_cpv2"])
    if hist.empty:
        return 100.0
    pares_historicos = set(zip(hist["organo_contratacion"], hist["_cpv2"], strict=False))

    # Contar licitaciones cuyo par no aparece en el histórico
    pares_actuales = list(zip(df_c["organo_contratacion"], df_c["_cpv2"], strict=False))
    nuevos = sum(1 for p in pares_actuales if p not in pares_historicos)
    return float(nuevos / len(df_c) * 100)


def ccaa_mas_activa(df: pd.DataFrame) -> dict[str, str | int | float] | None:
    if df.empty or "ccaa" not in df.columns:
        return None
    geo = (
        df.dropna(subset=["ccaa"])
        .groupby("ccaa")
        .agg(n=("id_externo", "count"), importe=("importe", "sum"))
        .sort_values("n", ascending=False)
    )
    if geo.empty:
        return None
    row = geo.iloc[0]
    return {
        "ccaa": str(geo.index[0]),
        "n": int(row["n"]),
        "importe": float(row["importe"] or 0),
    }


def concentracion_geografica(df: pd.DataFrame, top_n: int = 3) -> float:
    """% del importe total acumulado por las top N CCAA (0-100)."""
    if df.empty or "ccaa" not in df.columns:
        return 0.0
    geo = df.dropna(subset=["ccaa"]).groupby("ccaa")["importe"].sum().sort_values(ascending=False)
    total = geo.sum()
    if total <= 0:
        return 0.0
    return float(geo.head(top_n).sum() / total * 100)


def mes_pico(df: pd.DataFrame) -> dict[str, str | float | int] | None:
    if df.empty or "fecha_publicacion" not in df.columns:
        return None
    mensual = (
        df.dropna(subset=["fecha_publicacion"])
        .assign(_mes=lambda x: month_start(x["fecha_publicacion"]))
        .groupby("_mes")
        .agg(n=("id_externo", "count"), importe=("importe", "sum"))
        .sort_values("importe", ascending=False)
    )
    if mensual.empty:
        return None
    row = mensual.iloc[0]
    return {
        "mes": pd.Timestamp(mensual.index[0]).strftime("%b %Y"),
        "importe": float(row["importe"] or 0),
        "n": int(row["n"]),
    }


def ratio_relicitacion(df_pipeline: pd.DataFrame, df_adj: pd.DataFrame) -> float:
    """% de oportunidades del pipeline que vienen de un contrato ya adjudicado (re-licitación).

    Identifica qué proporción son contratos con ganador previo conocido
    (oportunidades de "arrebatar" clientes vs "virgen").
    """
    if df_pipeline.empty:
        return 0.0
    if df_adj.empty or "licitacion_id" not in df_adj.columns:
        return 0.0
    ids_con_adj = set(df_adj["licitacion_id"].dropna())
    if "id_externo" not in df_pipeline.columns:
        return 0.0
    ids_pipeline = df_pipeline["id_externo"].dropna()
    if ids_pipeline.empty:
        return 0.0
    return float(ids_pipeline.isin(ids_con_adj).sum() / len(ids_pipeline) * 100)


def kpi_sparkline_series(
    df: pd.DataFrame,
    metric: str = "count",
    freq: str = "W",
    periods: int = 12,
) -> list[float]:
    """Serie histórica agregada para usar como sparkline inline.

    Args:
        df: DataFrame con columna `fecha_publicacion` y (si metric='sum'/'mean') `importe`.
        metric: "count" | "sum" | "mean" — agregación a aplicar.
        freq: frecuencia pandas ("W"=semana, "M"=mes, "D"=día).
        periods: número de periodos a devolver (últimos N).

    Returns:
        Lista de floats listos para pasar a `kpi_card(sparkline=...)`.
    """
    if df.empty or "fecha_publicacion" not in df.columns:
        return []
    s = df.dropna(subset=["fecha_publicacion"]).copy()
    if s.empty:
        return []
    s["fecha_publicacion"] = pd.to_datetime(s["fecha_publicacion"], errors="coerce", utc=True)
    if s["fecha_publicacion"].dt.tz is not None:
        s["fecha_publicacion"] = s["fecha_publicacion"].dt.tz_localize(None)

    s = s.set_index("fecha_publicacion").sort_index()
    if metric == "count":
        agg = s.resample(freq).size()
    elif metric == "sum" and "importe" in s.columns:
        agg = s["importe"].resample(freq).sum(min_count=1).fillna(0)
    elif metric == "mean" and "importe" in s.columns:
        agg = s["importe"].resample(freq).mean().fillna(0)
    else:
        return []

    return [float(v) for v in agg.tail(periods).tolist()]


def is_anomaly(current: float, history: list[float] | pd.Series, sigma: float = 2.0) -> bool:
    """Detecta si `current` se desvía más de `sigma` desviaciones de la media histórica.

    Requiere al menos 3 puntos históricos válidos. Si la desviación típica es 0
    (historia constante), usa una tolerancia relativa del 10% sobre la media.
    """
    if history is None:
        return False
    h = [float(v) for v in list(history) if v is not None and v == v]
    if len(h) < 3:
        return False
    ser = pd.Series(h)
    mu = float(ser.mean())
    sd = float(ser.std(ddof=0))
    if sd == 0:
        # Tolerancia relativa cuando no hay variabilidad histórica
        return mu > 0 and abs(current - mu) > abs(mu) * 0.10
    z = abs(current - mu) / sd
    return z >= sigma


# ── KPIs comerciales SAP específicos ────────────────────────────────────────


def importe_medio_por_modulo(df: pd.DataFrame) -> pd.DataFrame:
    """Importe medio y nº de licitaciones por módulo SAP detectado.

    Requiere que `df.modulos` sea una lista/iterable (ya lo es tras data_loader).
    """
    if df.empty or "modulos" not in df.columns:
        return pd.DataFrame(columns=["modulo", "n", "importe_medio", "importe_total"])
    mod_df = df.explode("modulos").dropna(subset=["modulos"])
    if mod_df.empty:
        return pd.DataFrame(columns=["modulo", "n", "importe_medio", "importe_total"])
    g = (
        mod_df.groupby("modulos")
        .agg(
            n=("id_externo", "count"),
            importe_medio=("importe", "mean"),
            importe_total=("importe", "sum"),
        )
        .reset_index()
        .rename(columns={"modulos": "modulo"})
        .sort_values("importe_medio", ascending=False)
    )
    return g


def top_modulo_yoy(df: pd.DataFrame) -> dict[str, str | float | int] | None:
    """Módulo SAP con mayor crecimiento YoY en nº de licitaciones.

    Returns: {modulo, crecimiento_pct, n_act, n_prev} o None si no hay datos suficientes.
    """
    if df.empty or "modulos" not in df.columns or "fecha_publicacion" not in df.columns:
        return None
    hoy = pd.Timestamp.now("UTC")
    d = df.copy()
    d["fecha_publicacion"] = pd.to_datetime(d["fecha_publicacion"], errors="coerce", utc=True)
    actual = d[d["fecha_publicacion"] >= (hoy - pd.Timedelta(days=365))]
    previo = d[
        (d["fecha_publicacion"] < (hoy - pd.Timedelta(days=365)))
        & (d["fecha_publicacion"] >= (hoy - pd.Timedelta(days=730)))
    ]

    act_counts = actual.explode("modulos").dropna(subset=["modulos"]).groupby("modulos").size()
    prev_counts = previo.explode("modulos").dropna(subset=["modulos"]).groupby("modulos").size()

    if act_counts.empty:
        return None

    # Solo módulos con al menos 3 en el periodo actual, para evitar ruido
    act_counts = act_counts[act_counts >= 3]
    if act_counts.empty:
        return None

    growth = {}
    for mod in act_counts.index:
        n_act = int(act_counts.get(mod, 0))
        n_prev = int(prev_counts.get(mod, 0))
        if n_prev == 0:
            # Módulo totalmente nuevo: crecimiento "infinito" representado como 999
            growth[mod] = (999.0, n_act, n_prev)
        else:
            pct = (n_act - n_prev) / n_prev * 100
            growth[mod] = (pct, n_act, n_prev)

    if not growth:
        return None
    top_mod = max(growth.items(), key=lambda kv: kv[1][0])
    mod_name, (pct, n_act, n_prev) = top_mod
    return {
        "modulo": str(mod_name),
        "crecimiento_pct": float(pct),
        "n_act": int(n_act),
        "n_prev": int(n_prev),
    }


def pct_multi_modulo(df: pd.DataFrame) -> float:
    """% de licitaciones con >=2 módulos SAP detectados (proyectos integrales)."""
    if df.empty or "modulos" not in df.columns:
        return 0.0
    # Vectorizado: longitud de cada lista (0 si no es lista).
    lengths = df["modulos"].map(lambda m: len(m) if isinstance(m, list) else 0)
    con_modulos = lengths[lengths > 0]
    if con_modulos.empty:
        return 0.0
    multi = (con_modulos >= 2).sum()
    return float(multi / len(con_modulos) * 100)


def _build_searchable_text(df: pd.DataFrame) -> pd.Series:
    """Concatena titulo + descripcion en una Series de strings en minusculas.

    Helper privado para evitar que mypy se confunda con la concatenacion de Series
    cuando `descripcion` no existe en el DataFrame.
    """
    titulo = df["titulo"].fillna("").astype(str) if "titulo" in df.columns else ""
    desc = df["descripcion"].fillna("").astype(str) if "descripcion" in df.columns else ""

    if isinstance(titulo, str) and isinstance(desc, str):
        return pd.Series([""] * len(df), index=df.index)

    parts: list[pd.Series] = []
    if not isinstance(titulo, str):
        parts.append(titulo)
    if not isinstance(desc, str):
        parts.append(desc)

    combined = parts[0]
    for p in parts[1:]:
        combined = combined.str.cat(p, sep=" ")
    return combined.str.lower()


def _keywords_mask(text: pd.Series, keywords: list[str]) -> pd.Series:
    """Boolean mask: True where *text* contains any of *keywords* (vectorized)."""
    import re as _re

    pattern = "|".join(_re.escape(k.lower()) for k in keywords)
    return text.str.contains(pattern, na=False, regex=True)


def ticket_medio_por_plataforma(df: pd.DataFrame) -> dict[str, dict[str, int | float]]:
    """Importe medio de licitaciones que mencionan S/4HANA vs ECC.

    Returns: {s4hana: {n, ticket_medio}, ecc: {n, ticket_medio}}.
    """
    from dashboard.kpi_config import ECC_KEYWORDS, S4HANA_KEYWORDS

    result = {"s4hana": {"n": 0, "ticket_medio": 0.0}, "ecc": {"n": 0, "ticket_medio": 0.0}}
    if df.empty:
        return result

    text = _build_searchable_text(df)
    s4_mask = _keywords_mask(text, S4HANA_KEYWORDS)
    ecc_mask = _keywords_mask(text, ECC_KEYWORDS)

    s4_df = df[s4_mask].dropna(subset=["importe"])
    ecc_df = df[ecc_mask].dropna(subset=["importe"])

    if not s4_df.empty:
        result["s4hana"] = {
            "n": len(s4_df),
            "ticket_medio": float(s4_df["importe"].mean()),
        }
    if not ecc_df.empty:
        result["ecc"] = {
            "n": len(ecc_df),
            "ticket_medio": float(ecc_df["importe"].mean()),
        }
    return result


def portfolio_match(df: pd.DataFrame, keywords: list[str] | None = None) -> float:
    """% de licitaciones cuyo título/descripción contiene al menos una keyword del portfolio."""
    if df.empty:
        return 0.0
    if keywords is None:
        from dashboard.kpi_config import SAP_SERVICES_PORTFOLIO

        keywords = SAP_SERVICES_PORTFOLIO
    if not keywords:
        return 0.0
    text = _build_searchable_text(df)
    mask = _keywords_mask(text, keywords)
    return float(mask.sum() / len(df) * 100)


# ── KPIs "para hoy" — accionables ───────────────────────────────────────────


def calientes_hoy(
    df: pd.DataFrame,
    df_adj: pd.DataFrame | None = None,
    watchlist_ids: set[str] | None = None,
) -> pd.DataFrame:
    """Licitaciones 'calientes' = en plazo + importe > P75 + riesgo ≤1 flag.

    Si `watchlist_ids` está presente, además se exige match con la watchlist.
    Devuelve DataFrame con columnas del original + 'riesgo_score'.
    """
    if df.empty:
        return pd.DataFrame()
    d = df.copy()

    # Filtrar por estado "en plazo" o equivalente
    en_plazo_states = {"PUB", "EV"}
    if "estado" in d.columns:
        d = d[d["estado"].isin(en_plazo_states)]

    if d.empty:
        return pd.DataFrame()

    # Umbral P75 del importe
    p75 = d["importe"].quantile(0.75) if d["importe"].notna().any() else 0
    d = d[d["importe"].fillna(0) >= p75]

    if d.empty:
        return pd.DataFrame()

    # Filtrar por watchlist si procede
    if watchlist_ids:
        d = d[d["id_externo"].isin(watchlist_ids)]
        if d.empty:
            return pd.DataFrame()

    # Añadir riesgo score si hay adjudicaciones históricas
    if df_adj is not None and not df_adj.empty:
        rf = risk_flags(d, df_adj)
        d = d.merge(rf, on="id_externo", how="left")
        d["riesgo_score"] = d["riesgo_score"].fillna(0).astype(int)
        d = d[d["riesgo_score"] <= 1]

    return d


def vencen_en(df: pd.DataFrame, horas: int = 48) -> int:
    """Nº de licitaciones cuyo plazo de presentación vence en las próximas N horas."""
    if df.empty or "fecha_fin_plazo" not in df.columns:
        return 0
    hoy = pd.Timestamp.now("UTC")
    limite = hoy + pd.Timedelta(hours=horas)
    fp = pd.to_datetime(df["fecha_fin_plazo"], errors="coerce", utc=True)
    mask = (fp >= hoy) & (fp <= limite)
    return int(mask.sum())


def velocity_funnel(df: pd.DataFrame, df_adj: pd.DataFrame | None = None) -> dict[str, float]:
    """Días medianos que tarda una licitación en cada transición.

    - pub_a_adj: mediana días publicación → adjudicación (de df_adj si existe).
    - pub_a_fin_plazo: mediana días publicación → fin de plazo de presentación.
    """
    out: dict[str, float] = {}
    if not df.empty and "fecha_fin_plazo" in df.columns:
        fp = pd.to_datetime(df["fecha_publicacion"], errors="coerce", utc=True)
        ff = pd.to_datetime(df["fecha_fin_plazo"], errors="coerce", utc=True)
        diff = (ff - fp).dt.days
        valid = diff[diff > 0]
        if not valid.empty:
            out["pub_a_fin_plazo"] = float(valid.median())

    if df_adj is not None and not df_adj.empty and "fecha_adjudicacion" in df_adj.columns:
        adj_merged = df_adj.merge(
            df[["id_externo", "fecha_publicacion"]].rename(columns={"id_externo": "licitacion_id"}),
            on="licitacion_id",
            how="left",
        )
        lt = lead_time_medio(adj_merged)
        if lt is not None:
            out["pub_a_adj"] = float(lt)
    return out


def tasa_conversion_organo(df: pd.DataFrame, top_n: int = 5) -> pd.DataFrame:
    """% de licitaciones de cada órgano que acaban en estado ADJ.

    Útil para identificar órganos que "realmente compran" (alta conversión)
    vs los que publican y anulan.
    """
    if df.empty or "organo_contratacion" not in df.columns or "estado" not in df.columns:
        return pd.DataFrame(columns=["organo", "total", "adjudicadas", "tasa"])
    g = df.groupby("organo_contratacion")
    stats = g.agg(
        total=("id_externo", "count"),
        adjudicadas=("estado", lambda s: (s == "ADJ").sum()),
    ).reset_index()
    # Filtrar órganos con al menos 5 licitaciones para que el ratio sea significativo
    stats = stats[stats["total"] >= 5]
    if stats.empty:
        return pd.DataFrame(columns=["organo", "total", "adjudicadas", "tasa"])
    stats["tasa"] = stats["adjudicadas"] / stats["total"] * 100
    stats = stats.rename(columns={"organo_contratacion": "organo"})
    return stats.sort_values("tasa", ascending=False).head(top_n)


# ── Calidad del dato ────────────────────────────────────────────────────────


def calidad_dato(df: pd.DataFrame) -> dict[str, float]:
    """Métricas de completitud del dataset.

    Returns:
        dict con claves: pct_cpv_valido, pct_importe, pct_fecha_pub, pct_titulo.
    """
    if df.empty:
        return {"pct_cpv_valido": 0.0, "pct_importe": 0.0, "pct_fecha_pub": 0.0, "pct_titulo": 0.0}
    n = len(df)
    pct_cpv = 0.0
    if "cpv" in df.columns:
        pct_cpv = float(df["cpv"].astype(str).str.match(r"^\d{8,}$", na=False).sum() / n * 100)
    pct_importe = float(df["importe"].notna().sum() / n * 100) if "importe" in df.columns else 0.0
    pct_fp = (
        float(df["fecha_publicacion"].notna().sum() / n * 100)
        if "fecha_publicacion" in df.columns
        else 0.0
    )
    pct_titulo = (
        float((df["titulo"].notna() & (df["titulo"].astype(str).str.len() > 10)).sum() / n * 100)
        if "titulo" in df.columns
        else 0.0
    )
    return {
        "pct_cpv_valido": pct_cpv,
        "pct_importe": pct_importe,
        "pct_fecha_pub": pct_fp,
        "pct_titulo": pct_titulo,
    }


# risk_flags and score_oportunidad extracted to _scoring.py (P3 split)
from dashboard.stats._scoring import risk_flags, score_oportunidad  # noqa: E402, F811


# ────────────────────────────────────────────────────────────────────────────
# KPIs por órgano
# ────────────────────────────────────────────────────────────────────────────
def kpis_organo(
    df: pd.DataFrame,
    df_adj: pd.DataFrame | None = None,
    organo: str | None = None,
) -> dict[str, float | str | int | None]:
    """KPIs agregados de un órgano contratante.

    Si `organo` se pasa, filtra `df` por `organo_contratacion == organo` antes
    de calcular. Si `organo` es None, usa todo el `df` recibido (asume que ya
    viene filtrado).

    Args:
        df: Licitaciones (con columnas: id_externo, importe, estado, organo_contratacion).
        df_adj: Adjudicaciones para top adjudicatario y lead time (opcional).
        organo: Nombre exacto del órgano. None = no filtrar.

    Returns:
        dict con: n_lics, importe_total, importe_medio, pct_adj, lead_time_dias,
        top_adjudicatario (str | None), top_adj_importe (float).
    """
    out: dict[str, float | str | int | None] = {
        "n_lics": 0,
        "importe_total": 0.0,
        "importe_medio": 0.0,
        "pct_adj": 0.0,
        "lead_time_dias": None,
        "top_adjudicatario": None,
        "top_adj_importe": 0.0,
    }
    if df.empty:
        return out

    sub = df[df["organo_contratacion"] == organo] if organo is not None else df
    if sub.empty:
        return out

    n = len(sub)
    out["n_lics"] = n
    if "importe" in sub.columns:
        imp_total = float(sub["importe"].sum(skipna=True))
        out["importe_total"] = imp_total
        # Media solo sobre licitaciones con importe declarado
        notna_imp = sub["importe"].notna().sum()
        out["importe_medio"] = float(imp_total / notna_imp) if notna_imp else 0.0

    if "estado" in sub.columns:
        out["pct_adj"] = float((sub["estado"] == "ADJ").sum() / n * 100)

    # Lead time + top adjudicatario requieren df_adj
    if df_adj is not None and not df_adj.empty and "licitacion_id" in df_adj.columns:
        sub_adj = df_adj[df_adj["licitacion_id"].isin(sub["id_externo"])]
        if not sub_adj.empty:
            lt = lead_time_medio(sub_adj)
            out["lead_time_dias"] = lt
            if "nombre_canonico" in sub_adj.columns:
                top = (
                    sub_adj.groupby("nombre_canonico")["importe_adjudicado"]
                    .sum()
                    .sort_values(ascending=False)
                )
                if not top.empty and top.iloc[0] > 0:
                    out["top_adjudicatario"] = str(top.index[0])
                    out["top_adj_importe"] = float(top.iloc[0])

    return out


# ── Comparador de periodos ──────────────────────────────────────────────


def compare_periods(
    df: pd.DataFrame,
    range_a: tuple[pd.Timestamp, pd.Timestamp],
    range_b: tuple[pd.Timestamp, pd.Timestamp],
) -> dict[str, dict[str, float]]:
    """Compara métricas clave entre dos rangos de fechas.

    Returns dict con claves: total, importe_total, importe_medio, organos.
    Cada una contiene: {a, b, delta_pct}.
    """
    col = "fecha_publicacion"
    df_a = df[(df[col] >= range_a[0]) & (df[col] <= range_a[1])]
    df_b = df[(df[col] >= range_b[0]) & (df[col] <= range_b[1])]

    k_a = kpis(df_a)
    k_b = kpis(df_b)

    result: dict[str, dict[str, float]] = {}
    for key in ("total", "importe_total", "importe_medio", "organos"):
        va = float(k_a[key])
        vb = float(k_b[key])
        pct = ((vb - va) / va * 100) if va else 0.0
        result[key] = {"a": va, "b": vb, "delta_pct": pct}
    return result
