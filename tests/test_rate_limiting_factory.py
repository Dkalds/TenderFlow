"""Tests para services/rate_limiting.py — la factory de backends.

El módulo no tenía ningún test que lo mencionara (auditoría 2026-08-07) pese a
decidir qué backend de rate limiting usa toda la API. Cubre la selección por
``RATE_LIMIT_BACKEND``, el singleton y su reset, y el fallback a BD cuando se
pide Redis pero no está disponible — el camino que evita quedarse sin rate
limiting por una caída de Redis.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _reset_singleton():
    """La factory cachea el limiter; cada test parte de cero."""
    from services.rate_limiting import reset_rate_limiter

    reset_rate_limiter()
    yield
    reset_rate_limiter()


def test_default_backend_is_the_database():
    """Sin configurar nada, el limiter va a BD (no se queda sin límite)."""
    from services.rate_limiting import DbRateLimiter, get_rate_limiter

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("RATE_LIMIT_BACKEND", None)
        assert isinstance(get_rate_limiter(), DbRateLimiter)


def test_sqlite_sigue_siendo_alias_valido_del_backend_de_bd():
    """``sqlite`` es el valor histórico y no puede romper un despliegue vivo.

    El motor es Postgres desde ADR-021, pero la variable pudo quedar fijada con
    el valor viejo; tratarlo como desconocido dejaría la API sin rate limiting.
    """
    from services.rate_limiting import DbRateLimiter, get_rate_limiter

    with patch.dict(os.environ, {"RATE_LIMIT_BACKEND": "sqlite"}):
        assert isinstance(get_rate_limiter(), DbRateLimiter)


def test_redis_backend_selected_when_available():
    from services.rate_limiting import RedisRateLimiter, get_rate_limiter

    with (
        patch.dict(os.environ, {"RATE_LIMIT_BACKEND": "redis"}),
        patch("services.rate_limit_redis.has_redis", return_value=True),
    ):
        assert isinstance(get_rate_limiter(), RedisRateLimiter)


def test_redis_requested_but_unavailable_falls_back_to_db():
    """Pedir Redis y no tenerlo degrada a BD, nunca a "sin límite"."""
    from services.rate_limiting import DbRateLimiter, get_rate_limiter

    with (
        patch.dict(os.environ, {"RATE_LIMIT_BACKEND": "redis"}),
        patch("services.rate_limit_redis.has_redis", return_value=False),
    ):
        assert isinstance(get_rate_limiter(), DbRateLimiter)


def test_get_rate_limiter_is_a_singleton():
    from services.rate_limiting import get_rate_limiter

    assert get_rate_limiter() is get_rate_limiter()


def test_reset_rate_limiter_allows_switching_backend():
    """Sin el reset, cambiar de backend en runtime no tendría efecto."""
    from services.rate_limiting import (
        DbRateLimiter,
        RedisRateLimiter,
        get_rate_limiter,
        reset_rate_limiter,
    )

    with patch.dict(os.environ, {"RATE_LIMIT_BACKEND": "sqlite"}):
        assert isinstance(get_rate_limiter(), DbRateLimiter)

    reset_rate_limiter()
    with (
        patch.dict(os.environ, {"RATE_LIMIT_BACKEND": "redis"}),
        patch("services.rate_limit_redis.has_redis", return_value=True),
    ):
        assert isinstance(get_rate_limiter(), RedisRateLimiter)


def test_redis_limiter_falls_back_to_db_when_check_returns_none():
    """Si Redis no responde a la comprobación, se resuelve contra la BD.

    ``check_rate_limit_redis`` devuelve ``None`` para señalar "no pude
    decidir": dejar pasar la request sin más sería abrir el rate limiting.
    """
    from services.rate_limiting import RedisRateLimiter

    with (
        patch("services.rate_limit_redis.check_rate_limit_redis", return_value=None),
        patch("db.rate_limits.check_rate_limit_db", return_value=False) as db_check,
    ):
        assert RedisRateLimiter().check("k", max_calls=1, window_seconds=60) is False
    db_check.assert_called_once()
