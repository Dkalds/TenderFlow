"""Tests para services/admin.py — list_users, list_api_keys, revoke_api_key."""

from __future__ import annotations


def test_list_users_returns_list(tmp_db):
    """list_users devuelve una lista (vacía o con items)."""
    from services.admin import list_users

    result = list_users()
    assert isinstance(result, list)


def test_list_api_keys_empty_initially(tmp_db):
    """Antes de crear keys, list_api_keys devuelve lista vacía."""
    from services.admin import list_api_keys

    result = list_api_keys()
    assert isinstance(result, list)
    assert len(result) == 0


def test_list_api_keys_shows_created_key(tmp_db):
    """Una vez creada una key, aparece en list_api_keys."""
    from api.auth import create_api_key
    from services.admin import list_api_keys

    create_api_key("admin-test-key", scopes="read")
    keys = list_api_keys()
    assert len(keys) >= 1
    names = [k["name"] for k in keys]
    assert "admin-test-key" in names


def test_revoke_api_key_marks_as_inactive(tmp_db):
    """revoke_api_key desactiva la key y ya no aparece activa en list_api_keys."""
    from api.auth import create_api_key
    from services.admin import list_api_keys, revoke_api_key

    token = create_api_key("to-revoke", scopes="*")
    # Antes de revocar — debe estar activa
    keys_before = list_api_keys()
    active_before = [k for k in keys_before if k["name"] == "to-revoke" and k.get("is_active")]
    assert len(active_before) == 1

    # Revocar por key_id (services.admin.revoke_api_key recibe key_id: int)
    revoke_api_key(active_before[0]["id"])

    # Después — no debe aparecer como activa
    keys_after = list_api_keys()
    active_after = [k for k in keys_after if k["name"] == "to-revoke" and k.get("is_active")]
    assert len(active_after) == 0


def test_revoke_api_key_nonexistent(tmp_db):
    """Revocar un key_id inexistente no lanza excepción."""
    from services.admin import revoke_api_key

    # No debe lanzar, simplemente no hace nada
    revoke_api_key(99999)


def test_list_users_limit_respected(tmp_db):
    """El parámetro limit se respeta."""
    from services.admin import list_users

    result = list_users(limit=1)
    assert isinstance(result, list)
    assert len(result) <= 1
