"""Tests para db.users (CRUD OAuth + local, list_users, deactivate_user)."""

from __future__ import annotations

import importlib


def test_get_or_create_oauth_user(tmp_db):
    import db.users as users_mod

    importlib.reload(users_mod)

    uid1 = users_mod.get_or_create_oauth_user(
        email="alice@example.com",
        oauth_provider="google",
        oauth_sub="sub_alice_123",
        display_name="Alice",
    )
    assert uid1 > 0

    # Mismo sub → mismo id
    uid2 = users_mod.get_or_create_oauth_user(
        email="alice@example.com",
        oauth_provider="google",
        oauth_sub="sub_alice_123",
        display_name="Alice",
    )
    assert uid1 == uid2


class TestListUsers:
    def test_vacio_sin_usuarios(self, tmp_db):
        from db.users import list_users

        users = list_users()
        assert isinstance(users, list)

    def test_lista_usuario_registrado(self, tmp_db):
        from db.users import get_or_create_oauth_user, list_users

        _ = get_or_create_oauth_user(
            email="bob@example.com",
            oauth_provider="google",
            oauth_sub="sub_bob",
            display_name="Bob",
        )

        users = list_users()
        emails = [u["email"] for u in users]
        assert "bob@example.com" in emails

    def test_incluye_columna_last_access(self, tmp_db):
        from db.users import get_or_create_oauth_user, list_users

        get_or_create_oauth_user(
            email="carol@example.com",
            oauth_provider="google",
            oauth_sub="sub_carol",
        )
        users = list_users()
        found = next((u for u in users if u["email"] == "carol@example.com"), None)
        assert found is not None
        assert "last_access" in found

    def test_respeta_limit(self, tmp_db):
        from db.users import get_or_create_oauth_user, list_users

        for i in range(5):
            get_or_create_oauth_user(
                email=f"limit_user{i}@example.com",
                oauth_provider="google",
                oauth_sub=f"sub_limit_{i}",
            )

        users = list_users(limit=2)
        assert len(users) <= 2


class TestDeactivateUser:
    def test_soft_delete_oculta_usuario(self, tmp_db):
        from db.users import deactivate_user, get_or_create_oauth_user, get_user_by_id

        uid = get_or_create_oauth_user(
            email="todelete@example.com",
            oauth_provider="google",
            oauth_sub="sub_del",
        )

        deactivate_user(uid)
        # Sin include_deactivated, aparece como None
        assert get_user_by_id(uid) is None
        # Con include_deactivated, sigue existiendo
        user = get_user_by_id(uid, include_deactivated=True)
        assert user is not None
        assert user["deactivated_at"] is not None

    def test_conserva_access_log(self, tmp_db):
        db_mod, _ = tmp_db
        from db.users import deactivate_user, get_or_create_oauth_user, log_access

        uid = get_or_create_oauth_user(
            email="todelete2@example.com",
            oauth_provider="google",
            oauth_sub="sub_del2",
        )
        log_access(auth_method="google", user_id=uid, email="todelete2@example.com")
        deactivate_user(uid)

        # access_log se conserva tras soft-delete
        with db_mod.connect() as c:
            cur = c.execute("SELECT COUNT(*) FROM access_log WHERE user_id = ?", (uid,))
            assert cur.fetchone()[0] == 1

    def test_idempotente_usuario_inexistente(self, tmp_db):
        from db.users import deactivate_user

        deactivate_user(9999)  # no debe lanzar excepción


class TestAnonymizeUser:
    def test_nullifica_pii(self, tmp_db):
        db_mod, _ = tmp_db
        from db.users import (
            anonymize_user,
            get_or_create_oauth_user,
            get_user_by_id,
            log_access,
        )

        uid = get_or_create_oauth_user(
            email="anon@example.com",
            oauth_provider="google",
            oauth_sub="sub_anon",
            display_name="Anon User",
        )
        log_access(auth_method="google", user_id=uid, email="anon@example.com")

        anonymize_user(uid)

        user = get_user_by_id(uid, include_deactivated=True)
        assert user is not None
        assert user["email"] is None
        assert user["display_name"] is None
        assert user["oauth_sub"] is None
        assert user["deactivated_at"] is not None

        # access_log email anonimizado pero registro conservado
        with db_mod.connect() as c:
            row = c.execute(
                "SELECT email, auth_method FROM access_log WHERE user_id = ?", (uid,)
            ).fetchone()
            assert row[0] is None  # email anonimizado
            assert row[1] == "google"  # auth_method conservado

    def test_conserva_esqueleto_audit(self, tmp_db):
        db_mod, _ = tmp_db
        from db.users import anonymize_user, get_or_create_oauth_user, log_access

        uid = get_or_create_oauth_user(
            email="audit@example.com",
            oauth_provider="google",
            oauth_sub="sub_audit",
        )
        log_access(auth_method="google", user_id=uid, email="audit@example.com")
        anonymize_user(uid)

        with db_mod.connect() as c:
            row = c.execute(
                "SELECT user_id, logged_in_at FROM access_log WHERE user_id = ?", (uid,)
            ).fetchone()
            assert row[0] == uid
            assert row[1] is not None


class TestSetAdmin:
    def test_dar_y_quitar_admin(self, tmp_db):
        from db.users import get_or_create_oauth_user, is_admin, set_admin

        uid = get_or_create_oauth_user(
            email="admin_test@example.com",
            oauth_provider="google",
            oauth_sub="sub_admin_test",
        )

        assert not is_admin(uid)
        set_admin(uid, True)
        assert is_admin(uid)
        set_admin(uid, False)
        assert not is_admin(uid)


def test_different_users_get_different_ids(tmp_db):
    import db.users as users_mod

    importlib.reload(users_mod)

    uid1 = users_mod.get_or_create_oauth_user(
        email="a@test.com",
        oauth_provider="google",
        oauth_sub="sub_a",
    )
    uid2 = users_mod.get_or_create_oauth_user(
        email="b@test.com",
        oauth_provider="google",
        oauth_sub="sub_b",
    )
    assert uid1 != uid2


def test_get_user_by_id(tmp_db):
    import db.users as users_mod

    importlib.reload(users_mod)

    uid = users_mod.get_or_create_oauth_user(
        email="test@example.com",
        oauth_provider="google",
        oauth_sub="sub_test",
        display_name="Test User",
    )
    user = users_mod.get_user_by_id(uid)
    assert user is not None
    assert user["email"] == "test@example.com"
    assert user["display_name"] == "Test User"
    assert user["oauth_provider"] == "google"


def test_get_user_by_id_not_found(tmp_db):
    import db.users as users_mod

    importlib.reload(users_mod)

    assert users_mod.get_user_by_id(9999) is None


def test_get_user_by_email(tmp_db):
    import db.users as users_mod

    importlib.reload(users_mod)

    users_mod.get_or_create_oauth_user(
        email="findme@example.com",
        oauth_provider="google",
        oauth_sub="sub_findme",
    )
    user = users_mod.get_user_by_email("findme@example.com")
    assert user is not None
    assert user["oauth_sub"] == "sub_findme"


def test_get_user_by_email_not_found(tmp_db):
    import db.users as users_mod

    importlib.reload(users_mod)

    assert users_mod.get_user_by_email("nope@example.com") is None


def test_existing_email_links_oauth(tmp_db):
    """Si un email ya existe sin OAuth, vincular el nuevo OAuth sub."""
    import db.users as users_mod

    importlib.reload(users_mod)

    from db.database import connect, now_utc_iso

    # Crear usuario sin OAuth directamente
    with connect() as c:
        c.execute(
            "INSERT INTO users (email, created_at) VALUES (?, ?)",
            ("preexisting@example.com", now_utc_iso()),
        )
        pre_id = c.execute(
            "SELECT id FROM users WHERE email = ?", ("preexisting@example.com",)
        ).fetchone()[0]

    # Ahora vincular OAuth
    uid = users_mod.get_or_create_oauth_user(
        email="preexisting@example.com",
        oauth_provider="google",
        oauth_sub="sub_preexisting",
        display_name="Pre User",
    )
    assert uid == pre_id

    # Verificar que se vinculó
    user = users_mod.get_user_by_id(uid)
    assert user["oauth_provider"] == "google"
    assert user["oauth_sub"] == "sub_preexisting"


def test_watchlist_with_user_id(tmp_db):
    """Las entradas de watchlist se pueden vincular a un user_id."""
    import db.users as users_mod
    import db.watchlist as wl_mod

    importlib.reload(users_mod)
    importlib.reload(wl_mod)

    uid = users_mod.get_or_create_oauth_user(
        email="wl@example.com",
        oauth_provider="google",
        oauth_sub="sub_wl",
    )
    entry = wl_mod.WatchlistEntry(
        user_key="hash_wl",
        cpv_prefix="72",
        keyword="sap",
        user_id=uid,
    )
    wl_mod.add_entry(entry)

    # Buscar por user_key
    items = wl_mod.list_entries("hash_wl")
    assert len(items) == 1
    assert items[0]["user_id"] == uid

    # Buscar por user_id
    items2 = wl_mod.list_entries("different_key", user_id=uid)
    assert len(items2) == 1
    assert items2[0]["cpv_prefix"] == "72"


def test_log_access_oauth(tmp_db):
    """log_access registra un inicio de sesión OAuth."""
    import db.users as users_mod

    importlib.reload(users_mod)

    uid = users_mod.get_or_create_oauth_user(
        email="log@example.com",
        oauth_provider="google",
        oauth_sub="sub_log",
    )
    users_mod.log_access(auth_method="oauth", user_id=uid, email="log@example.com")

    from db.database import connect

    with connect() as c:
        rows = c.execute("SELECT * FROM access_log WHERE user_id = ?", (uid,)).fetchall()
    assert len(rows) == 1
    cols = [d[0] for d in c.execute("SELECT * FROM access_log LIMIT 0").description]
    row = dict(zip(cols, rows[0], strict=False))
    assert row["auth_method"] == "oauth"
    assert row["email"] == "log@example.com"
    assert row["logged_in_at"] is not None


def test_log_access_password(tmp_db):
    """log_access registra un inicio de sesión por password."""
    import db.users as users_mod

    importlib.reload(users_mod)

    users_mod.log_access(auth_method="password")

    from db.database import connect

    with connect() as c:
        rows = c.execute("SELECT * FROM access_log").fetchall()
    assert len(rows) == 1
    cols = [d[0] for d in c.execute("SELECT * FROM access_log LIMIT 0").description]
    row = dict(zip(cols, rows[0], strict=False))
    assert row["auth_method"] == "password"
    assert row["user_id"] is None
    assert row["email"] is None


def test_multiple_accesses_logged(tmp_db):
    """Múltiples accesos generan múltiples entradas."""
    import db.users as users_mod

    importlib.reload(users_mod)

    for _ in range(3):
        users_mod.log_access(auth_method="password")

    from db.database import connect

    with connect() as c:
        count = c.execute("SELECT COUNT(*) FROM access_log").fetchone()[0]
    assert count == 3
