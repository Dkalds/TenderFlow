"""Date helpers shared across services and analytics."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from observability.logging import get_logger

_log = get_logger(__name__)

# Regex para detectar fechas DD/MM/YYYY o DD-MM-YYYY (formato español)
_DATE_DMY_RE = re.compile(r"^(\d{2})[/\-](\d{2})[/\-](\d{4})$")

# Detecta si una hora CODICE (cbc:EndTime) ya trae offset explícito (Z o ±HH:MM/±HHMM).
_TIME_OFFSET_RE = re.compile(r"(Z|[+-]\d{2}:?\d{2})$")

_MADRID_TZ = ZoneInfo("Europe/Madrid")


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


def to_iso_datetime(raw_date: str | None, raw_time: str | None = None) -> str | None:
    """Combina ``EndDate``/``EndTime`` de CODICE en un datetime ISO 8601 UTC.

    CODICE publica la hora del plazo de presentación en hora local de España
    salvo que el propio valor lleve offset explícito. Sin normalizar a UTC,
    un plazo a las 23:59 CEST (verano, UTC+2) se guardaría como si venciera
    2h más tarde — suficiente para que un recordatorio T-1 avise después de
    que el plazo real ya haya pasado.

    Si falta ``raw_time`` o no es parseable, devuelve solo la fecha (mismo
    comportamiento que ``to_iso_date``) en vez de asumir una hora que la
    fuente no publicó.
    """
    date_part = to_iso_date(raw_date)
    if not date_part:
        return None
    time_part = (raw_time or "").strip()
    if not time_part:
        return date_part
    try:
        if _TIME_OFFSET_RE.search(time_part):
            dt = datetime.fromisoformat(f"{date_part}T{time_part.replace('Z', '+00:00')}")
            dt = dt.astimezone(UTC)
        else:
            dt = datetime.fromisoformat(f"{date_part}T{time_part}").replace(tzinfo=_MADRID_TZ)
            dt = dt.astimezone(UTC)
    except ValueError:
        _log.debug("tender_deadline_time_unparseable", raw_date=raw_date, raw_time=raw_time)
        return date_part
    return dt.isoformat()


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
