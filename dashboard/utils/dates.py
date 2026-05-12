"""Date helpers shared by dashboard aggregations."""

from __future__ import annotations

import pandas as pd


def month_start(series: pd.Series) -> pd.Series:
    """Return timezone-naive month starts without pandas timezone warnings."""
    values = pd.to_datetime(series, errors="coerce", utc=True)
    if getattr(values.dt, "tz", None) is not None:
        values = values.dt.tz_localize(None)
    return values.dt.to_period("M").dt.to_timestamp()


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
    return values.dt.to_period("Q").dt.to_timestamp()
