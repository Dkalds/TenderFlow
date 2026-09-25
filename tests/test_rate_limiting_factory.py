"""Tests para services/rate_limiting.py — la factory de backends.

El módulo no tenía ningún test que lo mencionara (auditoría 2026-08-07) pese a
decidir qué backend de rate limiting usa toda la API. Cubre la selección por
``RATE_LIMIT_BACKEND`` (``auto`` por defecto desde 2026-09), el singleton y su
reset, y el fallback a BD cuando se pide Redis pero no está disponible — el
camino que evita quedarse sin rate limiting por una caída de Redis.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_singleton():
    """La factory cachea el limiter; cada test parte de cero."""
    from services.rate_limit_redis import reset_client
    from services.rate_limiting import reset_rate_limiter

    reset_rate_limiter()
    reset_client()
    yield
    reset_rate_limiter()
    reset_client()


def _sin_backend_explicito():
    """Entorno sin ``RATE_LIMIT_BACKEND``: rige el default."""
    entorno = patch.dict(os.environ, {}, clear=False)
    entorno.start()
    os.environ.pop("RATE_LIMIT_BACKEND", None)
    return entorno


def test_default_sin_redis_configurado_va_a_la_base_de_datos():
    """Sin ``REDIS_URL``, el ``auto`` por defecto va a BD (no se queda sin límite)."""
    from services.rate_limiting import DbRateLimiter, get_rate_limiter

    entorno = _sin_backend_explicito()
    try:
        with patch("services.rate_limit_redis.has_redis", return_value=False):
            assert isinstance(get_rate_limiter(), DbRateLimiter)
    finally:
        entorno.stop()


def test_default_con_redis_configurado_elige_redis():
    """Producción tiene ``REDIS_URL`` y hasta 2026-09 contaba igualmente en BD:
    ~5 viajes a Postgres por petición solo para el rate limit."""
    from services.rate_limiting import RedisRateLimiter, get_rate_limiter

    entorno = _sin_backend_explicito()
    try:
        with patch("services.rate_limit_redis.has_redis", return_value=True):
            assert isinstance(get_rate_limiter(), RedisRateLimiter)
    finally:
        entorno.stop()


def test_auto_explicito_se_comporta_como_el_default():
    from services.rate_limiting import (
        DbRateLimiter,
        RedisRateLimiter,
        get_rate_limiter,
        reset_rate_limiter,
    )

    with patch.dict(os.environ, {"RATE_LIMIT_BACKEND": "auto"}):
        with patch("services.rate_limit_redis.has_redis", return_value=True):
            assert isinstance(get_rate_limiter(), RedisRateLimiter)
        reset_rate_limiter()
        with patch("services.rate_limit_redis.has_redis", return_value=False):
            assert isinstance(get_rate_limiter(), DbRateLimiter)


def test_db_explicito_ignora_redis_aunque_este_configurado():
    """``db`` es el interruptor para volver al comportamiento anterior sin desplegar."""
    from services.rate_limiting import DbRateLimiter, get_rate_limiter

    with (
        patch.dict(os.environ, {"RATE_LIMIT_BACKEND": "db"}),
        patch("services.rate_limit_redis.has_redis", return_value=True),
    ):
        assert isinstance(get_rate_limiter(), DbRateLimiter)


def test_sqlite_sigue_siendo_alias_valido_del_backend_de_bd():
    """``sqlite`` es el valor histórico y no puede romper un despliegue vivo.

    El motor es Postgres desde ADR-021, pero la variable pudo quedar fijada con
    el valor viejo; tratarlo como desconocido dejaría la API sin rate limiting.
    """
    from services.rate_limiting import DbRateLimiter, get_rate_limiter

    with (
        patch.dict(os.environ, {"RATE_LIMIT_BACKEND": "sqlite"}),
        patch("services.rate_limit_redis.has_redis", return_value=True),
    ):
        assert isinstance(get_rate_limiter(), DbRateLimiter)


def test_valor_desconocido_se_trata_como_auto():
    from services.rate_limiting import RedisRateLimiter, get_rate_limiter

    with (
        patch.dict(os.environ, {"RATE_LIMIT_BACKEND": "memcached"}),
        patch("services.rate_limit_redis.has_redis", return_value=True),
    ):
        assert isinstance(get_rate_limiter(), RedisRateLimiter)


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


def test_auto_con_redis_configurado_pero_caido_resuelve_en_bd_sin_reintentar_cada_vez():
    """``auto`` con ``REDIS_URL`` apuntando a un Redis que no responde.

    Es el caso de un Redis caído en el arranque: el limiter sigue siendo el de
    Redis —cuando vuelva, se usará—, pero cada comprobación la decide la BD y
    la conexión no se reintenta hasta que pasa el enfriamiento.
    """
    from services.rate_limiting import RedisRateLimiter, get_rate_limiter

    redis_mod = MagicMock()
    redis_mod.Redis.from_url.return_value.ping.side_effect = ConnectionError("refused")

    entorno = _sin_backend_explicito()
    try:
        with (
            patch.dict(os.environ, {"REDIS_URL": "redis://cache:6379/0"}),
            patch("services.rate_limit_redis._REDIS_AVAILABLE", True),
            patch("services.rate_limit_redis.redis", redis_mod),
            patch("db.rate_limits.check_rate_limit_db", return_value=True) as db_check,
        ):
            limiter = get_rate_limiter()
            assert isinstance(limiter, RedisRateLimiter)
            assert limiter.check("k", max_calls=10, window_seconds=60) is True
            assert limiter.check("k", max_calls=10, window_seconds=60) is True
    finally:
        entorno.stop()

    assert db_check.call_count == 2
    assert redis_mod.Redis.from_url.call_count == 1


def test_un_error_de_bd_deniega():
    """Fail-closed ante la BD: se conserva tal cual con el nuevo default."""
    from services.rate_limiting import DbRateLimiter

    roto = MagicMock()
    roto.__enter__.side_effect = RuntimeError("pool agotado")
    with patch("db.rate_limits._connect", return_value=roto):
        assert DbRateLimiter().check("k", max_calls=10, window_seconds=60) is False
