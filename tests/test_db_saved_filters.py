"""Tests para db/saved_filters.py — CRUD acotado por organización y dueño."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


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

        Desde v129 el upsert intenta primero un ``UPDATE`` por identidad dual
        y sólo inserta si no tocó ninguna fila: aquí se simula ese caso
        (``rowcount = 0``) y se comprueban las dos sentencias. Desde v181 la
        mitad legacy de esa identidad la calcula la base
        (``clave_legada_de_usuario``) y la vista nueva nace sin clave.
        """
        from db.saved_filters import save_filter

        mock_conn = MagicMock()
        mock_conn.execute.return_value.rowcount = 0
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        save_filter("my_filter", '{"q":"test"}', 3, user_id=11)
        assert mock_conn.execute.call_count == 2
        update_sql = " ".join(mock_conn.execute.call_args_list[0][0][0].split())
        assert update_sql.startswith("UPDATE saved_filters")
        assert "organization_id = %s" in update_sql
        assert "f.user_key = clave_legada_de_usuario(%s)" in update_sql
        insert_sql = " ".join(mock_conn.execute.call_args_list[1][0][0].split())
        assert "INSERT INTO saved_filters" in insert_sql
        assert "organization_id" in insert_sql
        assert "user_key" not in insert_sql
        assert "ON CONFLICT (user_id, name) WHERE user_id IS NOT NULL" in insert_sql
        assert mock_conn.execute.call_args_list[1][0][1] == (
            11,
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

        result = list_saved_filters(3, user_id=11)
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

        list_saved_filters(3, user_id=11)
        sql = " ".join(mock_conn.execute.call_args[0][0].split())
        assert "organization_id = %s" in sql
        assert "user_id IS NULL AND user_key = clave_legada_de_usuario(%s)" in sql
        # v181: la identidad viaja como el par ``(user_id, user_id)``; la clave
        # legada la calcula la base y ningún llamador la conoce.
        assert mock_conn.execute.call_args[0][1] == (3, 11, 11)


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

        assert delete_saved_filter(42, organization_id=3, user_id=11) is True
        mock_conn.execute.assert_called_once()
        sql = " ".join(mock_conn.execute.call_args[0][0].split())
        assert "organization_id = %s" in sql
        assert "user_key = clave_legada_de_usuario(%s)" in sql
        assert mock_conn.execute.call_args[0][1] == (42, 3, 11, 11)

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

        assert delete_saved_filter(42, organization_id=3, user_id=11) is False

    @patch("db.saved_filters.connect")
    def test_org_branch_keeps_the_owner_predicate(self, mock_connect):
        """El borrado en organización exige dueño, no solo pertenencia.

        La rama tenía ``AND (visibility = 'organization' OR user_key = %s)``:
        el ``OR`` dejaba que cualquier miembro borrase la vista compartida de
        un compañero. Se comprueba sobre el SQL emitido —no contando
        parámetros— para que la asercion siga valiendo si cambia el formato.

        El predicado de identidad lleva su propio ``OR`` (id o clave legada),
        así que lo que se vigila es que ``visibility`` no entre en el borrado:
        la pertenencia al equipo no es alternativa a ser el dueño.
        """
        from db.saved_filters import delete_saved_filter

        mock_conn = MagicMock()
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.rowcount = 1

        assert delete_saved_filter(7, organization_id=3, user_id=11) is True
        sql = " ".join(mock_conn.execute.call_args[0][0].split())
        assert "user_id = %s" in sql
        assert "visibility" not in sql.lower()
        assert mock_conn.execute.call_args[0][1] == (7, 3, 11, 11)


class TestDeleteSavedFilterOwnership:
    """Dos usuarios de la MISMA organización: compartir no es ceder el borrado.

    Contra la base real (no mocks): ``list_saved_filters`` sigue mostrando la
    vista compartida a los dos, pero solo su dueño puede destruirla.
    """

    @staticmethod
    def _usuario(email: str) -> int:
        from db.users import create_user

        return int(
            create_user(
                email=email,
                password_hash="test-hash",  # pragma: allowlist secret -- literal de test
                display_name=email,
            )
        )

    @classmethod
    def _escenario(cls) -> tuple[int, int, int]:
        """Organización real con dos usuarios y una vista compartida de cada uno.

        `saved_filters.organization_id` es FK contra `organizations`, así que un
        id inventado revienta el INSERT con ForeignKeyViolation antes de llegar a
        comprobar nada de la propiedad del borrado, que es lo que estos tests
        miran. Devuelve ``(org, dueño, compañero)``.
        """
        from db.repositories.organizations import OrganizationRepository
        from db.saved_filters import save_filter

        owner = cls._usuario("owner-vistas@example.test")
        other = cls._usuario("other-vistas@example.test")
        org = int(OrganizationRepository().create_organization("Equipo de vistas", owner)["id"])
        save_filter("vista compartida", '{"q":"sap"}', org, "organization", user_id=owner)
        save_filter("vista del compañero", '{"q":"erp"}', org, "organization", user_id=other)
        return org, owner, other

    @staticmethod
    def _compartida(org: int, owner: int) -> dict[str, object]:
        from db.saved_filters import list_saved_filters

        return next(
            row
            for row in list_saved_filters(org, user_id=owner)
            if row["name"] == "vista compartida"
        )

    def test_colleague_cannot_delete_a_shared_view(self, api_db):
        from db.saved_filters import delete_saved_filter, list_saved_filters

        org, owner, other = self._escenario()
        compartida = self._compartida(org, owner)

        # El compañero la VE (es de visibilidad organización)...
        visibles = {row["id"] for row in list_saved_filters(org, user_id=other)}
        assert compartida["id"] in visibles

        # ...pero no la borra, y se le dice que no en vez de fingir que sí.
        assert (
            delete_saved_filter(int(compartida["id"]), organization_id=org, user_id=other) is False
        )
        assert compartida["id"] in {row["id"] for row in list_saved_filters(org, user_id=owner)}

    def test_owner_still_deletes_its_own_view(self, api_db):
        from db.saved_filters import delete_saved_filter, list_saved_filters

        org, owner, _ = self._escenario()
        compartida = self._compartida(org, owner)

        assert (
            delete_saved_filter(int(compartida["id"]), organization_id=org, user_id=owner) is True
        )
        assert compartida["id"] not in {row["id"] for row in list_saved_filters(org, user_id=owner)}

    def test_delete_across_organizations_still_denied(self, api_db):
        """La regresión que NO se quería introducir: el predicado de
        organización sigue siendo condición necesaria además del dueño."""
        from db.saved_filters import delete_saved_filter

        org, owner, _ = self._escenario()
        compartida = self._compartida(org, owner)

        assert (
            delete_saved_filter(int(compartida["id"]), organization_id=99, user_id=owner) is False
        )
