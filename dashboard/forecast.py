"""Estimación de fechas de fin y ventana de re-licitación."""

from __future__ import annotations

import pandas as pd

# Conversión de unidades CODICE a meses
UNIT_TO_MONTHS = {
    "ANN": 12.0,
    "MON": 1.0,
    "DAY": 1.0 / 30.4375,
    "WEK": 7.0 / 30.4375,
    "HUR": 1.0 / 730.0,
}


def to_months(valor: float | None, unidad: str | None) -> float | None:
    if valor is None or pd.isna(valor) or not unidad:
        return None
    try:
        valor_f = float(valor)
    except (TypeError, ValueError):
        return None
    if valor_f <= 0:
        return None
    factor = UNIT_TO_MONTHS.get(str(unidad).upper())
    if factor is None:
        return None
    return valor_f * factor


def estimate_end_date(
    start: pd.Timestamp | None,
    duracion_meses: float | None,
    fecha_fin_explicit: pd.Timestamp | None = None,
) -> pd.Timestamp | None:
    """Devuelve la fecha de fin estimada. Prefiere fecha_fin explícita."""
    if fecha_fin_explicit is not None and pd.notna(fecha_fin_explicit):
        return fecha_fin_explicit
    if start is None or pd.isna(start):
        return None
    if duracion_meses is None or pd.isna(duracion_meses) or duracion_meses <= 0:
        return None
    return start + pd.DateOffset(months=round(float(duracion_meses)))


def build_forecast_df(
    licitaciones: pd.DataFrame,
    adjudicaciones: pd.DataFrame,
    meses_anticipacion: int = 6,
    solo_mantenimiento: bool = True,
) -> pd.DataFrame:
    """Construye un dataframe con las previsiones de re-licitación.

    Lógica:
      - Por defecto solo proyectos de tipo 'Mantenimiento' (más predecibles).
        Con solo_mantenimiento=False analiza todos los tipos.
      - fecha_inicio = fecha_adjudicacion (de la primera adj asociada),
        o fecha_publicacion como fallback.
      - duracion_meses = parseado desde duracion_valor + unidad.
      - fecha_fin_estimada = inicio + duración (o fecha_fin explícita).
      - ventana_relicit_inicio = fin - meses_anticipacion.
    """
    if licitaciones.empty:
        return pd.DataFrame()

    df = licitaciones.copy()
    if solo_mantenimiento:
        df = df[df["tipo_proyecto"] == "Mantenimiento"]
    if df.empty:
        return df

    df["duracion_meses"] = df.apply(  # type: ignore[call-overload]
        lambda r: to_months(r.get("duracion_valor"), r.get("duracion_unidad")),
        axis=1,
    )

    # Sacar datos de adjudicación agregados por licitación
    if not adjudicaciones.empty:
        adj_agg = (
            adjudicaciones.groupby("licitacion_id")
            .agg(
                fecha_adj_calc=("fecha_adjudicacion", "min"),
                importe_adjudicado_total=("importe_adjudicado", "sum"),
                n_ofertas=("n_ofertas_recibidas", "max"),
                adjudicatarios=("nombre", lambda s: ", ".join(s.dropna().unique()[:3])),
            )
            .reset_index()
            .rename(columns={"licitacion_id": "id_externo"})
        )
        df = df.merge(adj_agg, on="id_externo", how="left")
    else:
        df["fecha_adj_calc"] = pd.NaT
        df["importe_adjudicado_total"] = None
        df["n_ofertas"] = None
        df["adjudicatarios"] = None

    df["fecha_inicio_dt"] = pd.to_datetime(df["fecha_inicio"], errors="coerce")
    df["fecha_fin_explicit_dt"] = pd.to_datetime(df["fecha_fin"], errors="coerce")

    # Inicio efectivo: prioridad → fecha_inicio explícita > adjudicación >
    # fecha_publicacion
    fpub = pd.to_datetime(df["fecha_publicacion"], errors="coerce", utc=True)
    if fpub.dt.tz is not None:
        fpub = fpub.dt.tz_localize(None)
    df["inicio_efectivo"] = df["fecha_inicio_dt"].fillna(df["fecha_adj_calc"]).fillna(fpub)

    # Fin estimado
    df["fecha_fin_estimada"] = df.apply(  # type: ignore[call-overload]
        lambda r: estimate_end_date(
            r["inicio_efectivo"], r["duracion_meses"], r["fecha_fin_explicit_dt"]
        ),
        axis=1,
    )

    # Ventana de re-licitación
    df["relicit_inicio"] = df["fecha_fin_estimada"] - pd.DateOffset(months=meses_anticipacion)
    df["relicit_fin"] = df["fecha_fin_estimada"]

    # Solo nos interesan los que terminan en el futuro
    hoy = pd.Timestamp.now("UTC").tz_localize(None)
    df["dias_hasta_fin"] = (df["fecha_fin_estimada"] - hoy).dt.days
    df["meses_hasta_fin"] = df["dias_hasta_fin"] / 30.4375

    # % baja del adjudicatario vs importe de licitación
    importe_lic = pd.to_numeric(df["importe"], errors="coerce")
    importe_adj = pd.to_numeric(df["importe_adjudicado_total"], errors="coerce")
    df["baja_pct"] = ((1 - importe_adj / importe_lic) * 100).where(
        (importe_lic > 0) & importe_adj.notna()
    )

    df["estado_forecast"] = pd.cut(
        df["dias_hasta_fin"],
        bins=[-99999, 0, 90, 180, 365, 99999],
        labels=["Ya vencido", "<3 meses", "3-6 meses", "6-12 meses", ">12 meses"],
    )
    return df.sort_values("fecha_fin_estimada")
