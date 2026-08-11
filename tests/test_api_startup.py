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


def test_lifespan_sizes_the_threadpool_and_restores_it_on_shutdown() -> None:
    """El limiter de anyio es estado de proceso, no de la app.

    El arranque lo dimensiona (``API_THREADPOOL_TOKENS``) y el apagado debe
    devolverlo a su valor previo: la fixture ``client`` de la suite NO entra en
    el ciclo de vida, así que un test que sí lo haga dejaría el threadpool
    encogido para todo lo que corriese después en el mismo proceso.
    """
    import anyio

    from api.app import app, lifespan
    from config.settings import settings

    # El limiter es un RunVar del event loop, así que todo el ciclo (antes,
    # durante y después) tiene que observarse dentro del mismo loop.
    async def start_and_stop() -> tuple[float, float, float]:
        limiter = anyio.to_thread.current_default_thread_limiter()
        antes = float(limiter.total_tokens)
        async with lifespan(app):
            durante = float(limiter.total_tokens)
        return antes, durante, float(limiter.total_tokens)

    with patch("api.app.init_db"):
        antes, durante, despues = asyncio.run(start_and_stop())

    assert durante == float(settings.API_THREADPOOL_TOKENS)
    assert despues == antes, "el apagado no restauró el limiter global"


def test_threadpool_is_sized_for_io_not_for_pandas() -> None:
    """Regresión del techo de concurrencia.

    El limiter estuvo fijado en 4 para todo el trabajo síncrono por un incidente
    de CPU con pandas; con un pool de conexiones mayor que eso, el techo real de
    la API eran 4 peticiones concurrentes. Lo que debe estar acotado es el carril
    CPU-bound, no el general.
    """
    from config.settings import settings

    assert settings.API_THREADPOOL_TOKENS >= 8, (
        "El threadpool general no debe volver a dimensionarse como si todo su "
        "trabajo fuera CPU-bound; para eso está API_CPU_BOUND_TOKENS."
    )
    assert settings.API_CPU_BOUND_TOKENS <= 4
    assert settings.API_THREADPOOL_TOKENS > settings.API_CPU_BOUND_TOKENS
