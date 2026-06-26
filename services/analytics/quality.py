"""Data quality analytics — completeness metrics, scrape freshness."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pandas as pd
from pydantic import BaseModel, Field

from observability.logging import get_logger
from services.licitaciones import load_stats_dataframe

log = get_logger(__name__)

# Una fecha bien formada empieza por YYYY-MM-DD (ISO-8601). Cualquier otra cosa
# no-nula (p. ej. DD/MM/YYYY legacy) es un fallo de FORMATO, no de completitud.
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class ColumnCompleteness(BaseModel):
    """Completeness for a single column."""

    columna: str
    pct: float


class QualityResult(BaseModel):
    """Data quality metrics."""

    total_records: int = 0
    pct_cpv: float = 0.0
    pct_importe: float = 0.0
    pct_fecha: float = 0.0
    pct_titulo: float = 0.0
    last_scrape_hours_ago: float | None = None
    dlq_count: int = 0
    completitud_columnas: list[ColumnCompleteness] = Field(default_factory=list)
    cobertura_nif: float = 0.0
    cobertura_modulo_sap: float = 0.0
    # Consistencia de FORMATO de fecha (no completitud): de las fechas de
    # publicación presentes, % en ISO-8601 y nº con formato inválido (DD/MM/YYYY…).
    pct_fecha_iso: float = 0.0
    fechas_no_iso: int = 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _pct_filled(df: pd.DataFrame, col: str) -> float:
    """Percentage of non-null, non-empty values in a column."""
    if col not in df.columns or df.empty:
        return 0.0
    filled = df[col].dropna()
    if filled.dtype == object:
        filled = filled[filled.astype(str).str.strip() != ""]
    return float(len(filled) / len(df) * 100)


def _iso_date_stats(df: pd.DataFrame, col: str) -> tuple[float, int]:
    """(% en ISO-8601, nº no-ISO) sobre los valores NO nulos de ``col``.

    Mide formato, no presencia: una fecha presente pero ``DD/MM/YYYY`` cuenta
    como completa en :func:`_pct_filled` pero como no-ISO aquí.
    """
    if col not in df.columns or df.empty:
        return 0.0, 0
    present = df[col].dropna()
    present = present[present.astype(str).str.strip() != ""]
    n = len(present)
    if n == 0:
        return 0.0, 0
    iso = present.astype(str).str.match(_ISO_DATE_RE)
    n_iso = int(iso.sum())
    return float(n_iso / n * 100), int(n - n_iso)


def _last_scrape_hours() -> float | None:
    """Get hours since last extraction run, if available."""
    try:
        from services.extraction_runs import load_runs

        runs = load_runs(limit=1)
        if not runs:
            return None
        last = runs[0]
        ended = last.get("ended_at") or last.get("started_at")
        if not ended:
            return None
        if isinstance(ended, str):
            ts = pd.to_datetime(ended, utc=True)
        else:
            ts = pd.Timestamp(ended, tz="UTC")
        delta = datetime.now(UTC) - ts.to_pydatetime()
        return round(delta.total_seconds() / 3600, 2)
    except Exception:
        log.debug("quality_last_scrape_unavailable")
        return None


def _dlq_count() -> int:
    """Número real de fallos abiertos en la DLQ (best-effort).

    Antes era un stub que devolvía 0: el panel mostraba siempre 0 fallos aunque
    la cola tuviera registros perdidos. Ahora consulta ``failed_extractions``.
    """
    try:
        from db.dlq import count_unresolved

        return count_unresolved()
    except Exception:
        log.debug("quality_dlq_count_unavailable")
        return 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_quality() -> QualityResult:
    """Compute data quality metrics."""
    log.info("analytics_quality_start")
    rows = load_stats_dataframe()
    df = pd.DataFrame(rows)

    if df.empty:
        log.info("analytics_quality_done", total=0)
        return QualityResult(dlq_count=_dlq_count())

    pct_fecha_iso, fechas_no_iso = _iso_date_stats(df, "fecha_publicacion")
    result = QualityResult(
        total_records=len(df),
        pct_cpv=_pct_filled(df, "cpv"),
        pct_importe=_pct_filled(df, "importe"),
        pct_fecha=_pct_filled(df, "fecha_publicacion"),
        pct_titulo=_pct_filled(df, "titulo"),
        pct_fecha_iso=pct_fecha_iso,
        fechas_no_iso=fechas_no_iso,
        last_scrape_hours_ago=_last_scrape_hours(),
        dlq_count=_dlq_count(),
        completitud_columnas=[
            ColumnCompleteness(columna=col, pct=_pct_filled(df, col))
            for col in [
                "id_externo",
                "titulo",
                "organo_contratacion",
                "importe",
                "estado",
                "fecha_publicacion",
                "ccaa",
                "cpv",
                "url",
                "tecnologia",
                "tipo_contrato",
                "provincia",
            ]
        ],
        cobertura_nif=_pct_filled(df, "nif") if "nif" in df.columns else 0.0,
        cobertura_modulo_sap=_pct_filled(df, "modulo_sap") if "modulo_sap" in df.columns else 0.0,
    )
    log.info("analytics_quality_done", total=result.total_records)
    return result
