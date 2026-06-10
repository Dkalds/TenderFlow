"""Scoring de oportunidades y flags de riesgo — extraído de _base.py (P3 split)."""

from __future__ import annotations

import pandas as pd

from dashboard.stats._base import _build_searchable_text, lead_time_medio
from observability.logging import get_logger

log = get_logger(__name__)


def risk_flags(df_lics: pd.DataFrame, df_adj: pd.DataFrame) -> pd.DataFrame:
    """Calcula flags de riesgo para cada licitación (vectorizado).

    Flags posibles:
    - "🔴 Monopolio"        — órgano adjudica ≥80% al mismo proveedor en ese CPV (2 dígitos)
    - "🟡 Baja competencia" — mediana de ofertas recibidas < 2 en ese CPV
    - "🟠 Alta anulación"   — tasa de anulación del órgano > 25%
    - "🔵 Presupuesto bajo" — importe < percentil 10 del CPV

    Returns:
        DataFrame con columnas: id_externo, riesgo_flags (str), riesgo_score (int).
    """
    if df_lics.empty:
        return pd.DataFrame(columns=["id_externo", "riesgo_flags", "riesgo_score"])

    df = df_lics.copy()
    df["_cpv2"] = df["cpv"].astype(str).str[:2]

    # ── Flag: Alta anulación por órgano
    organ_stats = (
        df.groupby("organo_contratacion")
        .agg(total=("id_externo", "count"), anuladas=("estado", lambda s: (s == "ANUL").sum()))
        .reset_index()
    )
    organ_stats["_tasa_anulacion"] = organ_stats["anuladas"] / organ_stats["total"] * 100
    df = df.merge(
        organ_stats[["organo_contratacion", "_tasa_anulacion"]],
        on="organo_contratacion",
        how="left",
    )
    df["_alta_anulacion"] = df["_tasa_anulacion"].fillna(0) > 25

    # ── Flag: Presupuesto bajo (< P10 del CPV a 2 dígitos)
    p10_cpv = df.groupby("_cpv2")["importe"].quantile(0.1).rename("_p10_importe").reset_index()
    df = df.merge(p10_cpv, on="_cpv2", how="left")
    df["_presupuesto_bajo"] = (
        df["importe"].notna() & df["_p10_importe"].notna() & (df["importe"] < df["_p10_importe"])
    )

    # ── Flags basados en adjudicaciones históricas
    if not df_adj.empty and "licitacion_id" in df_adj.columns:
        _adj_cols = ["licitacion_id", "empresa_key", "n_ofertas_recibidas"]
        adj_slim = df_adj[[c for c in _adj_cols if c in df_adj.columns]].copy()
        adj = adj_slim.merge(
            df[["id_externo", "_cpv2", "organo_contratacion"]],
            left_on="licitacion_id",
            right_on="id_externo",
            how="left",
        ).dropna(subset=["organo_contratacion", "_cpv2"])

        emp_counts = (
            adj.groupby(["organo_contratacion", "_cpv2", "empresa_key"])
            .size()
            .rename("_emp_n")
            .reset_index()
        )
        grp_totals = (
            adj.groupby(["organo_contratacion", "_cpv2"]).size().rename("_grp_n").reset_index()
        )
        cuota_df = emp_counts.merge(grp_totals, on=["organo_contratacion", "_cpv2"])
        cuota_df["_cuota"] = cuota_df["_emp_n"] / cuota_df["_grp_n"]
        max_cuota = (
            cuota_df.groupby(["organo_contratacion", "_cpv2"])["_cuota"]
            .max()
            .rename("_max_cuota")
            .reset_index()
        )
        df = df.merge(max_cuota, on=["organo_contratacion", "_cpv2"], how="left")
        df["_monopolio"] = df["_max_cuota"].fillna(0) >= 0.80

        med_ofertas = (
            adj.groupby("_cpv2")["n_ofertas_recibidas"]
            .median()
            .rename("_med_ofertas")
            .reset_index()
        )
        df = df.merge(med_ofertas, on="_cpv2", how="left")
        df["_baja_competencia"] = df["_med_ofertas"].fillna(99) < 2
    else:
        df["_monopolio"] = False
        df["_baja_competencia"] = False

    flag_map = {
        "_monopolio": "🔴 Monopolio",
        "_baja_competencia": "🟡 Baja competencia",
        "_alta_anulacion": "🟠 Alta anulación",
        "_presupuesto_bajo": "🔵 Presupuesto bajo",
    }
    flag_cols = list(flag_map.keys())
    df["riesgo_score"] = df[flag_cols].sum(axis=1).astype(int)
    df["riesgo_flags"] = df[flag_cols].apply(
        lambda row: " · ".join(label for col, label in flag_map.items() if row[col]),
        axis=1,
    )

    return df[["id_externo", "riesgo_flags", "riesgo_score"]]


def score_oportunidad(
    df: pd.DataFrame,
    df_adj: pd.DataFrame | None = None,
    weights: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Calcula un score 0-100 por licitación combinando señales comerciales SAP."""
    from dashboard.kpi_config import (
        S4HANA_KEYWORDS,
        SAP_SERVICES_PORTFOLIO,
        SCORING_BANDS,
        SCORING_WEIGHTS,
    )

    if df.empty:
        return pd.DataFrame(columns=["id_externo", "score", "banda", "desglose"])

    w = dict(SCORING_WEIGHTS)
    if weights:
        w.update(weights)

    out = pd.DataFrame({"id_externo": df["id_externo"].values}, index=df.index)
    texto = _build_searchable_text(df)

    # 1) Importe
    if "importe" in df.columns:
        imp = pd.to_numeric(df["importe"], errors="coerce")
    else:
        imp = pd.Series(0.0, index=df.index)
    if imp.notna().any():
        p10 = float(imp.quantile(0.1))
        p90 = float(imp.quantile(0.9))
        rng = max(p90 - p10, 1.0)
        imp_norm = ((imp.fillna(0).clip(p10, p90) - p10) / rng).clip(0, 1)
    else:
        imp_norm = pd.Series(0.0, index=df.index)
    out["_imp"] = imp_norm * w["importe"]

    # 2) Plazo
    if "fecha_fin_plazo" in df.columns:
        hoy = pd.Timestamp.now(tz="UTC")
        ff = pd.to_datetime(df["fecha_fin_plazo"], errors="coerce", utc=True)
        dias = (ff - hoy).dt.days.astype("Float64")

        def _plazo_score(d: float) -> float:
            if pd.isna(d) or d < 0:
                return 0.0
            if d < 7:
                return float(d) / 7.0
            if d <= 90:
                return 1.0
            return max(0.0, 1.0 - (float(d) - 90.0) / 275.0)

        plazo_norm = dias.apply(_plazo_score).fillna(0).astype(float)
    else:
        plazo_norm = pd.Series(0.0, index=df.index)
    out["_plz"] = plazo_norm * w["plazo"]

    # 3) Módulos SAP
    if "modulos" in df.columns:
        n_mods = df["modulos"].map(lambda x: len(x) if isinstance(x, list) else 0)
    elif "modulos_str" in df.columns:
        ms = df["modulos_str"].fillna("").astype(str).str.strip()
        n_mods = ms.where(ms == "", ms.str.count(",") + 1).where(ms != "", 0).astype(int)  # type: ignore[arg-type]
    else:
        n_mods = pd.Series(0, index=df.index)
    out["_mod"] = (n_mods.clip(0, 5) / 5.0) * w["modulos_sap"]

    # 4) Portfolio match
    import re as _re

    _port_pat = "|".join(_re.escape(k.lower()) for k in SAP_SERVICES_PORTFOLIO)
    port_match = (
        texto.str.contains(_port_pat, regex=True, na=False).astype(float)
        if _port_pat
        else pd.Series(0.0, index=df.index)
    )
    out["_port"] = port_match * w["portfolio_match"]

    # 5) S/4HANA boost
    _s4_pat = "|".join(_re.escape(k.lower()) for k in S4HANA_KEYWORDS)
    s4_match = (
        texto.str.contains(_s4_pat, regex=True, na=False).astype(float)
        if _s4_pat
        else pd.Series(0.0, index=df.index)
    )
    out["_s4"] = s4_match * w["s4hana_boost"]

    # 6) Competencia
    if df_adj is not None and not df_adj.empty and "cpv" in df.columns:
        cpv2 = df["cpv"].astype(str).str[:2]
        adj_tmp = df_adj.copy()
        if "licitacion_id" in adj_tmp.columns:
            adj_tmp = adj_tmp.merge(
                df[["id_externo", "cpv"]].rename(columns={"id_externo": "licitacion_id"}),
                on="licitacion_id",
                how="left",
            )
            if "cpv" in adj_tmp.columns:
                adj_tmp["_cpv2"] = adj_tmp["cpv"].astype(str).str[:2]
                med_ofertas = adj_tmp.groupby("_cpv2")["n_ofertas_recibidas"].median().to_dict()
                comp_score = cpv2.map(lambda c: 1.0 if med_ofertas.get(c, 99) < 3 else 0.0)
            else:
                comp_score = pd.Series(0.0, index=df.index)
        else:
            comp_score = pd.Series(0.0, index=df.index)
    else:
        comp_score = pd.Series(0.0, index=df.index)
    out["_comp"] = comp_score.astype(float) * w["competencia"]

    # 7) Riesgo
    if df_adj is not None and not df_adj.empty:
        try:
            rf = risk_flags(df, df_adj)
            rf_map = rf.set_index("id_externo")["riesgo_score"].to_dict()
            riesgo_n = df["id_externo"].map(lambda i: rf_map.get(i, 0)).astype(float)
            riesgo_norm = 1.0 - (riesgo_n / 2.0).clip(0, 1) * 2.0
        except Exception as e:
            log.debug("score_risk_flags_failed", error=str(e))
            riesgo_norm = pd.Series(1.0, index=df.index)
    else:
        riesgo_norm = pd.Series(1.0, index=df.index)
    out["_risk"] = riesgo_norm * w["riesgo"]

    # Score total
    score_cols = ["_imp", "_plz", "_mod", "_port", "_s4", "_comp", "_risk"]
    out["score_raw"] = out[score_cols].sum(axis=1).clip(0, 100)
    out["score"] = out["score_raw"].round(0).astype(int)

    def _banda(s: int) -> str:
        for threshold, label in SCORING_BANDS.values():
            if s >= threshold:
                return label
        return "⚪ Descarte"

    out["banda"] = out["score"].apply(_banda)

    def _desglose(row: pd.Series) -> dict[str, int]:
        return {
            "importe": round(row["_imp"]),
            "plazo": round(row["_plz"]),
            "modulos_sap": round(row["_mod"]),
            "portfolio_match": round(row["_port"]),
            "s4hana_boost": round(row["_s4"]),
            "competencia": round(row["_comp"]),
            "riesgo": round(row["_risk"]),
        }

    out["desglose"] = out.apply(_desglose, axis=1)

    return out[["id_externo", "score", "banda", "desglose"]].reset_index(drop=True)
