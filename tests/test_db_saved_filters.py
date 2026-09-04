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
    def test_save_filter_always_persists_the_organization(self, mock_now, mock_connect):
        """El INSERT graba la organización; ya no hay rama que la omita.

        Este test llamaba a ``save_filter`` sin ``organization_id`` y esperaba
        cuatro parámetros: era la rama de fail-open que documenta
        ``api/tenancy.py``, la que escribía una fila con ``organization_id``
        nulo. Esa fila no se «guardaba sin ámbito» de forma inocua: quedaba
        invisible para siempre a la lectura, que sí filtra por organización.
        El argumento pasó a ser obligatorio, así que lo que queda por proteger
        es que la columna viaje en el INSERT -- se comprueba sobre el SQL
        emitido, no solo contando parámetros, para que siga valiendo si cambia
        el formato del literal.
        """
        from db.saved_filters import save_filter

        mock_conn = MagicMock()
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        save_filter("user1", "my_filter", '{"q":"test"}', 3)
        mock_conn.execute.assert_called_once()
        sql = " ".join(mock_conn.execute.call_args[0][0].split())
        assert "organization_id" in sql
        assert mock_conn.execute.call_args[0][1] == (
            "user1",
            "my_filter",
            '{"q":"test"}',
            "2024-01-01T00:00:00Z",
            3,
            "private",
        )


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

        result = list_saved_filters("user1", 3)
        assert result == [{"id": 1, "name": "f1", "filters_json": "{}", "created_at": "2024-01-01"}]

    @patch("db.saved_filters.connect")
    def test_list_always_scopes_by_organization_and_user(self, mock_connect):
        """La lectura acota por organización Y por visibilidad/dueño.

        Sustituye a la comprobación implícita que hacía el test de arriba
        cuando ``organization_id`` era opcional: llamarlo con un solo argumento
        ejercitaba la rama sin filtro de organización, la que devolvía los
        filtros de un ``user_key`` fuese cual fuese su organización. Esa rama
        ya no existe; lo que hay que seguir vigilando es que la única query que
        queda lleve los dos predicados, porque de ellos depende el aislamiento
        (ver ``tests/test_user_key_sql_isolation.py``).
        """
        from db.saved_filters import list_saved_filters

        mock_cursor = MagicMock()
        mock_cursor.description = [("id",)]
        mock_cursor.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.execute.return_value = mock_cursor
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        list_saved_filters("user1", 3)
        sql = " ".join(mock_conn.execute.call_args[0][0].split())
        assert "organization_id = %s" in sql
        assert "user_key = %s" in sql
        assert mock_conn.execute.call_args[0][1] == (3, "user1")


class TestDeleteSavedFilter:
    @patch("db.saved_filters.connect")
    def test_delete_always_scopes_by_organization(self, mock_connect):
        """No queda ninguna rama de borrado sin ``organization_id``.

        Este test ejercitaba la rama sin organización y esperaba los
        parámetros ``(42, "user1")``: un DELETE por id acotado solo al dueño,
        que cruzaba organizaciones sin decirlo. Era el fail-open de
        ``api/tenancy.py`` en su versión más cara -- un borrado. Se sustituye
        por la comprobación de que la única query que sobrevive acota por
        organización y por dueño a la vez.
        """
        from db.saved_filters import delete_saved_filter

        mock_conn = MagicMock()
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_conn.execute.return_value.rowcount = 1

        assert delete_saved_filter(42, user_key="user1", organization_id=3) is True
        mock_conn.execute.assert_called_once()
        sql = " ".join(mock_conn.execute.call_args[0][0].split())
        assert "organization_id = %s" in sql
        assert "user_key = %s" in sql
        assert mock_conn.execute.call_args[0][1] == (42, 3, "user1")

    @patch("db.saved_filters.connect")
    def test_delete_reports_a_miss_instead_of_faking_success(self, mock_connect):
        """Si el predicado no casa con nada, se dice que no.

        La ruta HTTP traduce este ``False`` en un 404: sin él, borrar el filtro
        de otra organización devolvería 200 y el usuario creería que hizo algo.
        Vale sin Postgres, a diferencia de ``TestDeleteSavedFilterOwnership``.
        """
        from db.saved_filters import delete_saved_filter

        mock_conn = MagicMock()
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_conn.execute.return_value.rowcount = 0

        assert delete_saved_filter(42, user_key="user1", organization_id=3) is False

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
    def _organizacion(nombre: str = "Equipo de vistas") -> int:
        """Crea una organización de verdad y devuelve su id.

        `saved_filters.organization_id` es FK contra `organizations`, así que un
        id inventado revienta el INSERT con ForeignKeyViolation antes de llegar a
        comprobar nada de la propiedad del borrado, que es lo que estos tests
        miran.
        """
        from db.repositories.organizations import OrganizationRepository
        from db.users import create_user

        owner = create_user(
            email=f"{nombre.lower().replace(' ', '-')}@example.test",
            password_hash="test-hash",  # pragma: allowlist secret -- literal de test
            display_name=nombre,
        )
        return int(OrganizationRepository().create_organization(nombre, owner)["id"])

    @staticmethod
    def _seed(owner: str, other: str, org_id: int) -> None:
        from db.saved_filters import save_filter

        save_filter(owner, "vista compartida", '{"q":"sap"}', org_id, "organization")
        save_filter(other, "vista del compañero", '{"q":"erp"}', org_id, "organization")

    def test_colleague_cannot_delete_a_shared_view(self, api_db):
        from db.saved_filters import delete_saved_filter, list_saved_filters

        org = self._organizacion()
        self._seed("owner-key", "other-key", org)
        compartida = next(
            row for row in list_saved_filters("owner-key", org) if row["name"] == "vista compartida"
        )

        # El compañero la VE (es de visibilidad organización)...
        visibles = {row["id"] for row in list_saved_filters("other-key", org)}
        assert compartida["id"] in visibles

        # ...pero no la borra, y se le dice que no en vez de fingir que sí.
        assert (
            delete_saved_filter(compartida["id"], user_key="other-key", organization_id=org)
            is False
        )
        assert compartida["id"] in {row["id"] for row in list_saved_filters("owner-key", org)}

    def test_owner_still_deletes_its_own_view(self, api_db):
        from db.saved_filters import delete_saved_filter, list_saved_filters

        org = self._organizacion()
        self._seed("owner-key", "other-key", org)
        compartida = next(
            row for row in list_saved_filters("owner-key", org) if row["name"] == "vista compartida"
        )

        assert (
            delete_saved_filter(compartida["id"], user_key="owner-key", organization_id=org) is True
        )
        assert compartida["id"] not in {row["id"] for row in list_saved_filters("owner-key", org)}

    def test_delete_across_organizations_still_denied(self, api_db):
        """La regresión que NO se quería introducir: el predicado de
        organización sigue siendo condición necesaria además del dueño."""
        from db.saved_filters import delete_saved_filter, list_saved_filters

        org = self._organizacion()
        self._seed("owner-key", "other-key", org)
        compartida = next(
            row for row in list_saved_filters("owner-key", org) if row["name"] == "vista compartida"
        )

        assert (
            delete_saved_filter(compartida["id"], user_key="owner-key", organization_id=99) is False
        )
