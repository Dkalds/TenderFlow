"""Unit tests for get_stored_hash exception handling and timing attack fix.

Issue #48: get_stored_hash must not silently swallow exceptions.
The caller in api/auth.py must return 503 on DB errors and maintain
constant-time comparison when stored_hash is None.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest


class TestGetStoredHashPropagatesErrors:
    """services.auth.get_stored_hash must re-raise DB exceptions."""

    def test_db_error_propagates(self) -> None:
        from services.auth import get_stored_hash

        with patch("db.repositories.api_keys.connect_read") as mock_conn:
            mock_conn.return_value.__enter__ = MagicMock(side_effect=RuntimeError("DB down"))
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            with pytest.raises(RuntimeError, match="DB down"):
                get_stored_hash(999)

    def test_returns_none_when_no_row(self) -> None:
        from services.auth import get_stored_hash

        with patch("db.repositories.api_keys.connect_read") as mock_conn:
            ctx = MagicMock()
            ctx.execute.return_value.fetchone.return_value = None
            mock_conn.return_value.__enter__ = MagicMock(return_value=ctx)
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            assert get_stored_hash(1) is None

    def test_returns_hash_when_found(self) -> None:
        from services.auth import get_stored_hash

        with patch("db.repositories.api_keys.connect_read") as mock_conn:
            ctx = MagicMock()
            ctx.execute.return_value.fetchone.return_value = ("abc123",)
            mock_conn.return_value.__enter__ = MagicMock(return_value=ctx)
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            assert get_stored_hash(1) == "abc123"


class TestApiAuthHandlesDbError:
    """api/auth.py require_api_key must return 503 on DB error from get_stored_hash."""

    def test_db_error_returns_503(self) -> None:
        from fastapi import HTTPException

        from api.auth import require_api_key
        from services.auth import ApiKeyRecord

        mock_record = ApiKeyRecord(key_id=1, expires_at=None, scopes="*")

        with (
            patch("api.auth.hash_api_key", return_value="fakehash"),
            patch("api.auth.auth_service.lookup_active_key", return_value=mock_record),
            patch(
                "api.auth.auth_service.get_stored_hash",
                side_effect=RuntimeError("DB down"),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(require_api_key(api_key_raw="test-key"))
            assert exc_info.value.status_code == 503

    def test_none_hash_still_returns_401(self) -> None:
        from fastapi import HTTPException

        from api.auth import require_api_key
        from services.auth import ApiKeyRecord

        mock_record = ApiKeyRecord(key_id=1, expires_at=None, scopes="*")

        with (
            patch("api.auth.hash_api_key", return_value="fakehash"),
            patch("api.auth.auth_service.lookup_active_key", return_value=mock_record),
            patch("api.auth.auth_service.get_stored_hash", return_value=None),
        ):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(require_api_key(api_key_raw="test-key"))
            assert exc_info.value.status_code == 401
