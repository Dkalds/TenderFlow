"""Property tests for shared.dates.to_iso_date."""

from __future__ import annotations

import re

from hypothesis import assume, given
from hypothesis import strategies as st

from shared.dates import to_iso_date

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@given(st.dates())
def test_iso_roundtrip(d):
    """ISO string input → same ISO string output (idempotent)."""
    iso = d.isoformat()
    assert to_iso_date(iso) == iso


@given(
    st.integers(min_value=1, max_value=28),
    st.integers(min_value=1, max_value=12),
    st.integers(min_value=1900, max_value=2100),
)
def test_dmy_converts_to_iso(day, month, year):
    """DD/MM/YYYY → YYYY-MM-DD."""
    dmy = f"{day:02d}/{month:02d}/{year}"
    result = to_iso_date(dmy)
    assert result == f"{year}-{month:02d}-{day:02d}"


@given(st.dates())
def test_idempotent(d):
    """Applying to_iso_date twice gives same result."""
    iso = d.isoformat()
    first = to_iso_date(iso)
    second = to_iso_date(first)
    assert first == second


def test_none_returns_none():
    assert to_iso_date(None) is None


@given(st.text(min_size=1, max_size=20))
def test_invalid_format_passthrough(s):
    """Non-date strings pass through unchanged (stripped) or None for blank."""
    assume(not _ISO_RE.match(s.strip()))
    assume("/" not in s)  # Avoid triggering DMY parsing
    result = to_iso_date(s)
    # to_iso_date strips whitespace; blank strings return None
    stripped = s.strip()
    if not stripped:
        assert result is None
    else:
        assert result == stripped
