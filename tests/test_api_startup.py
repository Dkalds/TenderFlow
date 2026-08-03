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


def test_lifespan_starts_without_prewarm_and_full_table_loaders_stay_retired() -> None:
    """El arranque no materializa datasets no acotados — y ya no puede.

    Los loaders full-table (``load_stats_base_df``/``load_raw_adjudicaciones``
    y los enriquecidos sin consumidores) se retiraron al completar ADR-023;
    este tripwire impide que vuelvan por la puerta de atrás.
    """
    import services.adjudicaciones as adj_svc
    import services.licitaciones as lic_svc
    from api.app import app, lifespan

    async def start_and_stop() -> None:
        async with lifespan(app):
            assert isinstance(app.state.pending_background_tasks, set)

    with patch("api.app.init_db"):
        asyncio.run(start_and_stop())

    for retired in ("load_stats_base_df", "load_stats_dataframe", "load_dataframe", "load_raw"):
        assert not hasattr(lic_svc, retired), retired
    for retired in ("load_raw_adjudicaciones", "load_adjudicaciones"):
        assert not hasattr(adj_svc, retired), retired
