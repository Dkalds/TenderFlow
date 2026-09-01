"""Allowlist OAuth dinámica: composición y fail-closed."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from api.routes.auth import _oauth_access_allowed


def test_static_grant_skips_database():
    with (
        patch("api.routes.auth.oauth_email_allowed", return_value=True),
        patch("db.access_grants.is_access_granted") as dynamic,
    ):
        assert asyncio.run(_oauth_access_allowed("allowed@example.test")) is True
    dynamic.assert_not_called()


def test_dynamic_grant_allows_email():
    with (
        patch("api.routes.auth.oauth_email_allowed", return_value=False),
        patch("db.access_grants.is_access_granted", return_value=True),
    ):
        assert asyncio.run(_oauth_access_allowed("allowed@example.test")) is True


def test_dynamic_allowlist_failure_is_closed():
    with (
        patch("api.routes.auth.oauth_email_allowed", return_value=False),
        patch(
            "db.access_grants.is_access_granted",
            side_effect=RuntimeError("database unavailable"),
        ),
    ):
        assert asyncio.run(_oauth_access_allowed("unknown@example.test")) is False


def test_dynamic_grant_is_normalized_idempotent_and_revocable(tmp_db):
    from db.access_grants import grant_access, is_access_granted, revoke_access

    first = grant_access("email", " Allowed@Example.Test ", granted_by=None)
    second = grant_access("email", "allowed@example.test", granted_by=None)

    assert second["id"] == first["id"]
    assert is_access_granted("ALLOWED@example.test") is True

    revoked = revoke_access(first["id"])
    assert revoked is not None
    assert revoked["active"] is False
    assert is_access_granted("allowed@example.test") is False
