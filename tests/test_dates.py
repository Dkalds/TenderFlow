"""Tests para shared.dates."""

from __future__ import annotations

import warnings

import pandas as pd


def test_month_start_handles_aware_datetimes_without_warning():
    from shared.dates import month_start

    series = pd.Series(pd.to_datetime(["2026-01-15T10:00:00+00:00"], utc=True))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = month_start(series)

    assert result.iloc[0] == pd.Timestamp("2026-01-01")
    assert not any("timezone" in str(w.message).lower() for w in caught)


def test_quarter_start_handles_aware_datetimes_without_warning():
    from shared.dates import quarter_start

    series = pd.Series(pd.to_datetime(["2026-05-15T10:00:00+00:00"], utc=True))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = quarter_start(series)

    assert result.iloc[0] == pd.Timestamp("2026-04-01")
    assert not any("timezone" in str(w.message).lower() for w in caught)


def test_month_period_returns_period_dtype():
    from shared.dates import month_period

    series = pd.Series(pd.to_datetime(["2026-03-15T10:00:00+00:00"], utc=True))
    result = month_period(series)
    assert str(result.iloc[0]) == "2026-03"


def test_month_period_handles_naive_datetimes():
    from shared.dates import month_period

    series = pd.Series(pd.to_datetime(["2026-06-20"]))
    result = month_period(series)
    assert str(result.iloc[0]) == "2026-06"


def test_month_start_naive_datetimes():
    from shared.dates import month_start

    series = pd.Series(pd.to_datetime(["2026-08-25"]))
    result = month_start(series)
    assert result.iloc[0] == pd.Timestamp("2026-08-01")
