"""Tests for API startup / lifespan DB initialization."""

from __future__ import annotations

import asyncio
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


def test_lifespan_does_not_prewarm_full_table_analytics() -> None:
    """API startup must not materialize the unbounded analytics datasets."""
    from api.app import app, lifespan

    async def start_and_stop() -> None:
        async with lifespan(app):
            assert isinstance(app.state.pending_background_tasks, set)

    with (
        patch("api.app.init_db"),
        patch("services.licitaciones.load_stats_base_df") as load_stats,
        patch("services.adjudicaciones.load_raw_adjudicaciones") as load_adjudicaciones,
    ):
        asyncio.run(start_and_stop())

    load_stats.assert_not_called()
    load_adjudicaciones.assert_not_called()
