"""Tests for API startup / lifespan DB initialization."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


def test_lifespan_raises_on_init_db_failure() -> None:
    """lifespan must propagate init_db() exceptions in all environments."""
    with patch("api.app.init_db", side_effect=RuntimeError("DB unavailable")):
        from api.app import app

        with pytest.raises(RuntimeError, match="DB unavailable"):
            with TestClient(app):
                pass  # pragma: no cover — should never reach here
