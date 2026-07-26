"""Safety transforms for files opened by spreadsheet applications.

CSV and XLSX are active formats in practice: values beginning with formula
prefixes are evaluated by Excel and compatible clients.  User- and upstream-
controlled strings are therefore neutralised before any export writer sees
them.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_FORMULA_PREFIXES = frozenset({"=", "+", "-", "@"})
_LEADING_IGNORABLES = " \t\r\n\u00a0\u200b"


def sanitize_spreadsheet_value(value: object) -> object:
    """Return *value* safe for CSV/XLSX without altering non-string values.

    A leading apostrophe is Excel's standard literal marker and is not shown to
    users in normal spreadsheet views.  We inspect after whitespace because
    several spreadsheet engines trim it before deciding whether a cell is a
    formula.
    """
    if not isinstance(value, str):
        return value
    stripped = value.lstrip(_LEADING_IGNORABLES)
    if stripped and stripped[0] in _FORMULA_PREFIXES:
        return "'" + value
    return value


def sanitize_spreadsheet_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Copy a record while neutralising every potentially active string cell."""
    return {key: sanitize_spreadsheet_value(value) for key, value in record.items()}
