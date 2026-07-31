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


# ─── to_iso_datetime (fecha_limite: EndDate + EndTime de CODICE) ────────────


class TestToIsoDatetime:
    def test_assumes_europe_madrid_in_summer_cest(self):
        """CODICE publica la hora sin offset — en verano España está en CEST
        (UTC+2), así que 23:59 local es 21:59 UTC, no 23:59 UTC."""
        from shared.dates import to_iso_datetime

        assert to_iso_datetime("2026-07-15", "23:59:00") == "2026-07-15T21:59:00+00:00"

    def test_assumes_europe_madrid_in_winter_cet(self):
        """En invierno España está en CET (UTC+1): mismo caso, offset distinto
        — si el código usara un offset fijo en vez de zoneinfo, este test
        fallaría en una de las dos estaciones."""
        from shared.dates import to_iso_datetime

        assert to_iso_datetime("2026-01-15", "23:59:00") == "2026-01-15T22:59:00+00:00"

    def test_respects_explicit_offset_in_time(self):
        from shared.dates import to_iso_datetime

        assert to_iso_datetime("2026-07-15", "23:59:00+02:00") == "2026-07-15T21:59:00+00:00"

    def test_respects_z_suffix_in_time(self):
        from shared.dates import to_iso_datetime

        assert to_iso_datetime("2026-07-15", "23:59:00Z") == "2026-07-15T23:59:00+00:00"

    def test_returns_date_only_when_time_missing(self):
        from shared.dates import to_iso_datetime

        assert to_iso_datetime("2026-07-15", None) == "2026-07-15"
        assert to_iso_datetime("2026-07-15") == "2026-07-15"

    def test_returns_none_when_date_missing(self):
        from shared.dates import to_iso_datetime

        assert to_iso_datetime(None, "23:59:00") is None
        assert to_iso_datetime("", "23:59:00") is None

    def test_falls_back_to_date_when_time_unparseable(self):
        from shared.dates import to_iso_datetime

        assert to_iso_datetime("2026-07-15", "no-es-una-hora") == "2026-07-15"

    def test_dmy_date_is_normalized_before_combining(self):
        """to_iso_datetime reutiliza to_iso_date: una fecha DD/MM/YYYY se
        normaliza a ISO antes de combinarse con la hora."""
        from shared.dates import to_iso_datetime

        assert to_iso_datetime("15/07/2026", "23:59:00") == "2026-07-15T21:59:00+00:00"
