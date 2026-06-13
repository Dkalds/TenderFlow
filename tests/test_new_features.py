"""Tests para shared.types."""

from __future__ import annotations


class TestSharedTypes:
    def test_import(self) -> None:
        from shared.types import (
            DlqRow,
            JsonDict,
            KpiSnapshot,
            LicitacionRow,
            NotificationRow,
            UserRow,
            WatchlistRow,
        )

        val = getattr(JsonDict, "__value__", JsonDict)
        assert val is dict or hasattr(val, "__origin__")
        assert issubclass(UserRow, dict)
        assert issubclass(WatchlistRow, dict)
        assert issubclass(LicitacionRow, dict)
        assert issubclass(NotificationRow, dict)
        assert issubclass(DlqRow, dict)
        assert issubclass(KpiSnapshot, dict)

    def test_user_row_is_dict_compatible(self) -> None:
        from shared.types import UserRow

        row: UserRow = UserRow({"id": 1, "email": "test@example.com", "is_admin": False})
        assert row["id"] == 1
        assert row["email"] == "test@example.com"

    def test_json_dict_is_regular_dict(self) -> None:
        from shared.types import JsonDict

        d: JsonDict = {"key": "value", "nested": {"a": 1}}
        assert d["nested"]["a"] == 1  # type: ignore[index]
