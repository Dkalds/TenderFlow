"""Servicio de adjudicaciones — acceso de lectura enriquecido.

Centraliza la lógica de carga de adjudicaciones. Delega en
``db/repositories/adjudicaciones.py`` para queries SQL.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from db.repositories.adjudicaciones import AdjudicacionRepository
from observability.logging import get_logger
from services._data_cache import SignalAwareCache

log = get_logger(__name__)

_repo = AdjudicacionRepository()

# Caché del caso sin filtros (el que usa la capa de analytics). Invalidada por
# TTL o por la señal de ingesta.
_raw_adj_cache: SignalAwareCache[list[dict[str, Any]]] = SignalAwareCache()


def load_adjudicaciones(
    *,
    limit: int | None = None,
    ccaa_filter: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Carga adjudicaciones enriquecidas."""
    from services.normalization import normalize_company, normalize_nif
    from shared.geo import nuts_to_ccaa

    rows = load_raw_adjudicaciones(limit=limit, ccaa_filter=ccaa_filter)
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["fecha_adjudicacion"] = pd.to_datetime(df["fecha_adjudicacion"], errors="coerce")
    df["fecha_publicacion"] = pd.to_datetime(
        df["fecha_publicacion"], errors="coerce", format="mixed", utc=True,
    )
    for col in (
        "importe_adjudicado", "importe_pagable", "oferta_minima",
        "oferta_maxima", "importe_licitacion",
    ):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["baja_pct"] = ((1 - df["importe_adjudicado"] / df["importe_licitacion"]) * 100).where(
        (df["importe_licitacion"] > 0) & df["importe_adjudicado"].notna()
    )

    _fp = df["fecha_publicacion"]
    if hasattr(_fp.dt, "tz") and _fp.dt.tz is not None:
        _fp = _fp.dt.tz_localize(None)
    df["lead_time_dias"] = (df["fecha_adjudicacion"] - _fp).dt.days
    df.loc[df["lead_time_dias"] <= 0, "lead_time_dias"] = pd.NA

    # Backfill CCAA from NUTS code
    if "ccaa" in df.columns and "nuts_code" in df.columns:
        try:
            mask = df["ccaa"].isna() & df["nuts_code"].notna()
            df.loc[mask, "ccaa"] = df.loc[mask, "nuts_code"].apply(nuts_to_ccaa)
        except Exception:
            pass

    df["es_ute"] = df["nombre"].str.contains(
        r"\bU\.?T\.?E\.?\b", case=False, na=False, regex=True,
    )

    try:
        df["nombre_norm"] = df["nombre"].apply(
            lambda x: normalize_company(x) if pd.notna(x) else None,
        )
    except Exception:
        df["nombre_norm"] = None
    try:
        df["nif_norm"] = df["nif"].apply(
            lambda x: normalize_nif(x) if pd.notna(x) else None,
        )
    except Exception:
        df["nif_norm"] = None

    df["empresa_key"] = df["nif_norm"].where(
        df["nif_norm"].notna() & (df["nif_norm"] != ""), df["nombre_norm"],
    )

    return df


def load_raw_adjudicaciones(
    *,
    limit: int | None = None,
    ccaa_filter: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Carga adjudicaciones raw con datos de la licitación asociada.

    El caso sin filtros (usado por la capa de analytics) se cachea en memoria
    con invalidación por TTL + señal de ingesta. Usar :func:`clear_raw_adj_cache`
    para forzar recarga.
    """
    if limit is None and ccaa_filter is None:
        return _raw_adj_cache.get(_repo.load_raw_with_licitaciones)
    return _repo.load_raw_with_licitaciones(limit=limit, ccaa_filter=ccaa_filter)


def clear_raw_adj_cache() -> None:
    """Invalida la caché de :func:`load_raw_adjudicaciones` (caso sin filtros)."""
    _raw_adj_cache.clear()


def load_licitadores(
    ccaa_filter: tuple[str, ...] | None = None,
    limit: int = 10000,
) -> list[dict[str, Any]]:
    """Carga adjudicaciones con datos para el ranking de licitadores."""
    return _repo.load_licitadores(ccaa_filter=ccaa_filter, limit=limit)
