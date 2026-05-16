"""Tests para shared/types.py y nuevos helpers de dashboard.

Cubre:
  - shared.types: importación y uso básico de TypedDicts / aliases
  - dashboard.components.tables.paginate_df: lógica de paginación pura
"""

from __future__ import annotations

import pandas as pd
import pytest

# ── shared.types ─────────────────────────────────────────────────────────


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

        # Todos son dict-subclasses o TypeAlias — simplemente deben importarse
        assert JsonDict is dict or hasattr(JsonDict, "__origin__")
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


# ── dashboard.components.tables.paginate_df ──────────────────────────────


class TestPaginateDf:
    """Tests de la función paginate_df (sin Streamlit — mocked)."""

    def _make_df(self, n: int) -> pd.DataFrame:
        return pd.DataFrame({"id": range(n), "valor": range(n)})

    def test_small_df_returns_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Si df tiene ≤ page_size filas, devuelve el df completo sin controles."""
        import streamlit as st

        monkeypatch.setattr(st, "session_state", {}, raising=False)
        monkeypatch.setattr(
            "dashboard.components.tables.st.columns",
            lambda *a, **kw: [_FakeCol(), _FakeCol(), _FakeCol()],
        )

        from dashboard.components.tables import paginate_df

        df = self._make_df(30)
        result = paginate_df(df, page_size=50, key="pg_test_small")
        assert len(result) == 30

    def test_large_df_returns_page_size_rows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Si df > page_size, devuelve exactamente page_size filas en página 0."""
        import streamlit as st

        session: dict = {}
        monkeypatch.setattr(st, "session_state", session, raising=False)

        # Stub out rendering helpers
        def fake_columns(*args: object, **kwargs: object) -> list[_FakeCol]:
            return [_FakeCol(), _FakeCol(), _FakeCol()]

        def fake_button(label: str, **kwargs: object) -> bool:
            return False

        def fake_caption(text: str) -> None:
            pass

        def fake_rerun() -> None:
            pass

        monkeypatch.setattr("dashboard.components.tables.st.columns", fake_columns)
        monkeypatch.setattr("dashboard.components.tables.st.button", fake_button)
        monkeypatch.setattr("dashboard.components.tables.st.caption", fake_caption)
        monkeypatch.setattr("dashboard.components.tables.st.rerun", fake_rerun)

        from dashboard.components.tables import paginate_df

        df = self._make_df(200)
        result = paginate_df(df, page_size=50, key="pg_test_large")
        assert len(result) == 50
        assert list(result["id"]) == list(range(50))

    def test_page_1_returns_correct_slice(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Página 1 devuelve filas 50-99."""
        import streamlit as st

        session: dict = {"pg_test_p1": 1}  # Ya en página 1
        monkeypatch.setattr(st, "session_state", session, raising=False)

        def fake_columns(*args: object, **kwargs: object) -> list[_FakeCol]:
            return [_FakeCol(), _FakeCol(), _FakeCol()]

        def fake_button(label: str, **kwargs: object) -> bool:
            return False

        monkeypatch.setattr("dashboard.components.tables.st.columns", fake_columns)
        monkeypatch.setattr("dashboard.components.tables.st.button", fake_button)
        monkeypatch.setattr("dashboard.components.tables.st.caption", lambda *a, **kw: None)
        monkeypatch.setattr("dashboard.components.tables.st.rerun", lambda: None)

        from dashboard.components.tables import paginate_df

        df = self._make_df(200)
        result = paginate_df(df, page_size=50, key="pg_test_p1")
        assert list(result["id"]) == list(range(50, 100))

    def test_last_page_returns_remainder(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Última página devuelve sólo las filas restantes."""
        import streamlit as st

        session: dict = {"pg_test_last": 3}  # página 3 de 4 (0-indexed) → filas 150-174
        monkeypatch.setattr(st, "session_state", session, raising=False)

        def fake_columns(*args: object, **kwargs: object) -> list[_FakeCol]:
            return [_FakeCol(), _FakeCol(), _FakeCol()]

        monkeypatch.setattr("dashboard.components.tables.st.columns", fake_columns)
        monkeypatch.setattr("dashboard.components.tables.st.button", lambda *a, **kw: False)
        monkeypatch.setattr("dashboard.components.tables.st.caption", lambda *a, **kw: None)
        monkeypatch.setattr("dashboard.components.tables.st.rerun", lambda: None)

        from dashboard.components.tables import paginate_df

        df = self._make_df(175)  # 175 rows, page_size=50 → 4 pages (50+50+50+25)
        result = paginate_df(df, page_size=50, key="pg_test_last")
        assert len(result) == 25
        assert list(result["id"]) == list(range(150, 175))


# ── Helper ────────────────────────────────────────────────────────────────


class _FakeCol:
    """Context manager stub for st.columns() entries."""

    def __enter__(self) -> _FakeCol:
        return self

    def __exit__(self, *args: object) -> None:
        pass
