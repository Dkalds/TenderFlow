"""Tests para shared.types."""

from __future__ import annotations


class TestSharedTypes:
    def test_import(self) -> None:
        from shared.types import JsonDict

        val = getattr(JsonDict, "__value__", JsonDict)
        assert val is dict or hasattr(val, "__origin__")

    def test_json_dict_is_regular_dict(self) -> None:
        from shared.types import JsonDict

        d: JsonDict = {"key": "value", "nested": {"a": 1}}
        assert d["nested"]["a"] == 1  # type: ignore[index]
