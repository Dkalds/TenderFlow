"""Date helpers shared across services and analytics."""

from __future__ import annotations

import re

import pandas as pd

from observability.logging import get_logger

_log = get_logger(__name__)

# Regex para detectar fechas DD/MM/YYYY o DD-MM-YYYY (formato español)
_DATE_DMY_RE = re.compile(r"^(\d{2})[/\-](\d{2})[/\-](\d{4})$")


def to_iso_date(raw: str | None) -> str | None:
    """Normaliza una fecha a ISO 8601 (YYYY-MM-DD).

    Idempotente: una fecha ISO entra y sale sin cambio (primeros 10 chars).
    Convierte DD/MM/YYYY y DD-MM-YYYY al formato canónico.
    Formatos no reconocidos se devuelven tal cual (el CHECK de la BD los atrapará).
    """
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    # Ya es ISO (YYYY-MM-DD o YYYY-MM-DDTHH:MM:SS) → devolver los primeros 10 chars
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        return raw[:10]
    # DD/MM/YYYY o DD-MM-YYYY → convertir
    m = _DATE_DMY_RE.match(raw)
    if m:
        day, month, year = m.groups()
        return f"{year}-{month}-{day}"
    # Formato no reconocido — devolver como está y loguear
    _log.debug("date_unrecognized_format", raw=raw)
    return raw


def month_start(series: pd.Series) -> pd.Series:
    """Return timezone-naive month starts without pandas timezone warnings."""
    values = pd.to_datetime(series, errors="coerce", utc=True)
    if getattr(values.dt, "tz", None) is not None:
        values = values.dt.tz_localize(None)
    return values.dt.to_period("M").dt.to_timestamp()  # type: ignore[return-value]


def month_period(series: pd.Series) -> pd.Series:
    """Return monthly Period values without dropping timezone implicitly."""
    values = pd.to_datetime(series, errors="coerce", utc=True)
    if getattr(values.dt, "tz", None) is not None:
        values = values.dt.tz_localize(None)
    return values.dt.to_period("M")


def quarter_start(series: pd.Series) -> pd.Series:
    """Return timezone-naive quarter starts without pandas timezone warnings."""
    values = pd.to_datetime(series, errors="coerce", utc=True)
    if getattr(values.dt, "tz", None) is not None:
        values = values.dt.tz_localize(None)
    return values.dt.to_period("Q").dt.to_timestamp()  # type: ignore[return-value]
