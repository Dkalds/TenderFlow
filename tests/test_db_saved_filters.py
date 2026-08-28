"""Tests para db/saved_filters.py — serialización de filtros y CRUD."""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


class TestFiltersToJson:
    def test_basic_serialization(self):
        from db.saved_filters import filters_to_json

        fs = SimpleNamespace(
            q="test",
            estados=["A"],
            ccaas=["Madrid"],
            organos=["X"],
            tipos_proy=["T"],
            tecnologias=["Python"],
            importe_min=1000,
            rango=None,
        )
        result = json.loads(filters_to_json(fs))
        assert result["q"] == "test"
        assert result["rango"] is None

    def test_with_rango(self):
        from db.saved_filters import filters_to_json

        fs = SimpleNamespace(
            q="",
            estados=[],
            ccaas=[],
            organos=[],
            tipos_proy=[],
            tecnologias=[],
            importe_min=0,
            rango=(date(2024, 1, 1), date(2024, 12, 31)),
        )
        result = json.loads(filters_to_json(fs))
        assert result["rango"] == ["2024-01-01", "2024-12-31"]

    def test_with_nav_section_and_detalle_cols(self):
        from db.saved_filters import filters_to_json

        fs = SimpleNamespace(
            q="",
            estados=[],
            ccaas=[],
            organos=[],
            tipos_proy=[],
            tecnologias=[],
            importe_min=0,
            rango=None,
        )
        result = json.loads(filters_to_json(fs, nav_section="sec", detalle_cols=["a", "b"]))
        assert result["nav_section"] == "sec"
        assert result["detalle_cols"] == ["a", "b"]

    def test_no_optional_fields_when_falsy(self):
        from db.saved_filters import filters_to_json

        fs = SimpleNamespace(
            q="",
            estados=[],
            ccaas=[],
            organos=[],
            tipos_proy=[],
            tecnologias=[],
            importe_min=0,
            rango=None,
        )
        result = json.loads(filters_to_json(fs))
        assert "nav_section" not in result
        assert "detalle_cols" not in result


class TestJsonToSessionState:
    def test_full_roundtrip(self):
        from db.saved_filters import json_to_session_state

        d = {
            "q": "search",
            "estados": ["A"],
            "ccaas": ["Madrid"],
            "organos": ["Org"],
            "tipos_proy": ["T"],
            "tecnologias": ["Py"],
            "importe_min": 500,
            "rango": ["2024-01-01", "2024-06-30"],
            "nav_section": "sec",
            "detalle_cols": ["c1"],
        }
        ss = json_to_session_state(json.dumps(d))
        assert ss["fs_q"] == "search"
        assert ss["fs_estados"] == ["A"]
        assert ss["fs_ccaas"] == ["Madrid"]
        assert ss["fs_organos"] == ["Org"]
        assert ss["fs_tipos"] == ["T"]
        assert ss["fs_tecnologias"] == ["Py"]
        assert ss["fs_imp_min"] == 500
        assert ss["fs_rango"] == (date(2024, 1, 1), date(2024, 6, 30))
        assert ss["nav_section"] == "sec"
        assert ss["detalle_cols"] == ["c1"]

    def test_empty_json(self):
        from db.saved_filters import json_to_session_state

        ss = json_to_session_state("{}")
        assert ss == {}

    def test_partial_fields(self):
        from db.saved_filters import json_to_session_state

        ss = json_to_session_state(json.dumps({"q": "hello"}))
        assert ss == {"fs_q": "hello"}

    def test_rango_wrong_length_ignored(self):
        from db.saved_filters import json_to_session_state

        ss = json_to_session_state(json.dumps({"rango": ["2024-01-01"]}))
        assert "fs_rango" not in ss


class TestSaveFilter:
    @patch("db.saved_filters.connect")
    @patch("db.saved_filters.now_utc_iso", return_value="2024-01-01T00:00:00Z")
    def test_save_filter_calls_execute(self, mock_now, mock_connect):
        from db.saved_filters import save_filter

        mock_conn = MagicMock()
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        save_filter("user1", "my_filter", '{"q":"test"}')
        mock_conn.execute.assert_called_once()
        args = mock_conn.execute.call_args
        assert args[0][1] == ("user1", "my_filter", '{"q":"test"}', "2024-01-01T00:00:00Z")


class TestListSavedFilters:
    @patch("db.saved_filters.connect")
    def test_list_returns_dicts(self, mock_connect):
        from db.saved_filters import list_saved_filters

        mock_cursor = MagicMock()
        mock_cursor.description = [("id",), ("name",), ("filters_json",), ("created_at",)]
        mock_cursor.fetchall.return_value = [(1, "f1", "{}", "2024-01-01")]
        mock_conn = MagicMock()
        mock_conn.execute.return_value = mock_cursor
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        result = list_saved_filters("user1")
        assert result == [{"id": 1, "name": "f1", "filters_json": "{}", "created_at": "2024-01-01"}]


class TestDeleteSavedFilter:
    @patch("db.saved_filters.connect")
    def test_delete_calls_execute(self, mock_connect):
        from db.saved_filters import delete_saved_filter

        mock_conn = MagicMock()
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_conn.execute.return_value.rowcount = 1

        assert delete_saved_filter(42, user_key="user1") is True
        mock_conn.execute.assert_called_once()
        assert mock_conn.execute.call_args[0][1] == (42, "user1")

    @patch("db.saved_filters.connect")
    def test_org_branch_keeps_the_owner_predicate(self, mock_connect):
        """El borrado en organización exige dueño, no solo pertenencia.

        La rama tenía ``AND (visibility = 'organization' OR user_key = %s)``:
        el ``OR`` dejaba que cualquier miembro borrase la vista compartida de
        un compañero. Se comprueba sobre el SQL emitido —no contando
        parámetros— para que la asercion siga valiendo si cambia el formato.
        """
        from db.saved_filters import delete_saved_filter

        mock_conn = MagicMock()
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.rowcount = 1

        assert delete_saved_filter(7, user_key="user1", organization_id=3) is True
        sql = " ".join(mock_conn.execute.call_args[0][0].split())
        assert "user_key = %s" in sql
        assert " OR " not in sql.upper()
        assert mock_conn.execute.call_args[0][1] == (7, 3, "user1")


class TestDeleteSavedFilterOwnership:
    """Dos usuarios de la MISMA organización: compartir no es ceder el borrado.

    Contra la base real (no mocks): ``list_saved_filters`` sigue mostrando la
    vista compartida a los dos, pero solo su dueño puede destruirla.
    """

    @staticmethod
    def _seed(owner: str, other: str, org_id: int) -> None:
        from db.saved_filters import save_filter

        save_filter(owner, "vista compartida", '{"q":"sap"}', org_id, "organization")
        save_filter(other, "vista del compañero", '{"q":"erp"}', org_id, "organization")

    def test_colleague_cannot_delete_a_shared_view(self, api_db):
        from db.saved_filters import delete_saved_filter, list_saved_filters

        self._seed("owner-key", "other-key", 42)
        compartida = next(
            row for row in list_saved_filters("owner-key", 42) if row["name"] == "vista compartida"
        )

        # El compañero la VE (es de visibilidad organización)...
        visibles = {row["id"] for row in list_saved_filters("other-key", 42)}
        assert compartida["id"] in visibles

        # ...pero no la borra, y se le dice que no en vez de fingir que sí.
        assert (
            delete_saved_filter(compartida["id"], user_key="other-key", organization_id=42) is False
        )
        assert compartida["id"] in {row["id"] for row in list_saved_filters("owner-key", 42)}

    def test_owner_still_deletes_its_own_view(self, api_db):
        from db.saved_filters import delete_saved_filter, list_saved_filters

        self._seed("owner-key", "other-key", 42)
        compartida = next(
            row for row in list_saved_filters("owner-key", 42) if row["name"] == "vista compartida"
        )

        assert (
            delete_saved_filter(compartida["id"], user_key="owner-key", organization_id=42) is True
        )
        assert compartida["id"] not in {row["id"] for row in list_saved_filters("owner-key", 42)}

    def test_delete_across_organizations_still_denied(self, api_db):
        """La regresión que NO se quería introducir: el predicado de
        organización sigue siendo condición necesaria además del dueño."""
        from db.saved_filters import delete_saved_filter, list_saved_filters

        self._seed("owner-key", "other-key", 42)
        compartida = next(
            row for row in list_saved_filters("owner-key", 42) if row["name"] == "vista compartida"
        )

        assert (
            delete_saved_filter(compartida["id"], user_key="owner-key", organization_id=99) is False
        )
