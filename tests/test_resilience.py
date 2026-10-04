"""Tests para scraper.resilience: retries y circuit breaker."""

from __future__ import annotations

import pybreaker
import pytest
import requests

from config import settings
from scraper.resilience import _is_transient, http_retry, placsp_breaker


class _FakeResp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def test_is_transient_connection_error():
    assert _is_transient(requests.ConnectionError("network down"))
    assert _is_transient(requests.Timeout("slow"))


def test_is_transient_http_5xx():
    err = requests.HTTPError()
    err.response = _FakeResp(503)
    assert _is_transient(err)


def test_is_transient_http_429():
    err = requests.HTTPError()
    err.response = _FakeResp(429)
    assert _is_transient(err)


def test_is_transient_http_4xx_not_retried():
    err = requests.HTTPError()
    err.response = _FakeResp(404)
    assert not _is_transient(err)


def test_is_transient_random_error_not_retried():
    assert not _is_transient(ValueError("payload too big"))


def test_http_retry_reraises_after_exhaustion():
    calls = {"n": 0}

    @http_retry
    def _boom():
        calls["n"] += 1
        raise requests.ConnectionError("down")

    with pytest.raises(requests.ConnectionError):
        _boom()
    # 4 intentos configurados en http_retry
    assert calls["n"] == 4


def test_http_retry_stops_on_non_transient():
    calls = {"n": 0}

    @http_retry
    def _boom():
        calls["n"] += 1
        raise ValueError("not transient")

    with pytest.raises(ValueError):
        _boom()
    assert calls["n"] == 1


def test_breaker_opens_after_consecutive_failures():
    # pybreaker abre el circuito cuando ``fail_counter >= fail_max`` y, en esa
    # misma llamada, lanza ``CircuitBreakerError`` en lugar de la original.
    local = pybreaker.CircuitBreaker(
        fail_max=3, reset_timeout=60, exclude=[ValueError], name="test_cb"
    )

    @local
    def always_fail():
        raise requests.ConnectionError("bad")

    with pytest.raises(requests.ConnectionError):
        always_fail()
    with pytest.raises(requests.ConnectionError):
        always_fail()
    # En la tercera llamada se alcanza fail_max=3 → el circuito se abre y el
    # error original se sustituye por ``CircuitBreakerError``.
    with pytest.raises(pybreaker.CircuitBreakerError):
        always_fail()
    # Llamadas posteriores también son cortocircuitadas.
    with pytest.raises(pybreaker.CircuitBreakerError):
        always_fail()


def test_recurso_no_servido_no_se_reintenta():
    """Es un ``HTTPError`` sin ``response``, que a secas se toma por transitorio.

    Así llegan los errores del transporte de documentos (``PinnedHttpsResponse``
    no pasa ``response=``), y por eso el 500 con el que PLACSP contesta por un
    documento concreto se pedía cuatro veces: 417 reintentos en los 33 lotes de
    ``pliegos.yml`` del 2026-09-04 al 2026-10-04, ninguno con otro resultado.
    """
    from scraper.resilience import RecursoNoServidoError

    exc = RecursoNoServidoError("Pinned HTTPS response status 500")

    assert isinstance(exc, requests.HTTPError)
    assert not _is_transient(exc)


def test_recurso_no_servido_no_cuenta_para_el_circuito():
    """El servidor contestó: lo roto es el recurso pedido, no la plataforma."""
    from scraper.resilience import RecursoNoServidoError, _nuevo_breaker

    circuito = _nuevo_breaker("test_recurso_no_servido")

    @circuito
    def pedir() -> None:
        raise RecursoNoServidoError("Pinned HTTPS response status 500")

    for _ in range(circuito.fail_max + 1):
        with pytest.raises(RecursoNoServidoError):
            pedir()

    assert circuito.current_state == "closed"
    assert circuito.fail_counter == 0


def test_placsp_breaker_exported():
    assert placsp_breaker.name == "placsp"
    assert placsp_breaker.fail_max == 5


def test_placsp_breaker_initial_timeout_matches_setting():
    """Verify reset_timeout is aligned with BREAKER_BASE_TIMEOUT, not a stale literal."""
    assert placsp_breaker.reset_timeout == settings.BREAKER_BASE_TIMEOUT


def test_adaptive_backoff_doubles_on_consecutive_opens():
    """Verify adaptive backoff doubles timeout on each open, resets on close."""
    from scraper.resilience import _AdaptiveBackoffListener

    listener = _AdaptiveBackoffListener(base_timeout=60, max_timeout=480)
    cb = pybreaker.CircuitBreaker(
        fail_max=2,
        reset_timeout=60,
        listeners=[listener],
        name="test_adaptive",
    )

    class _FakeState:
        def __init__(self, name: str) -> None:
            self.name = name

    # First open: timeout = 60 * 2^0 = 60
    listener.state_change(cb, _FakeState("closed"), _FakeState("open"))
    assert cb.reset_timeout == 60

    # Second open: timeout = 60 * 2^1 = 120
    listener.state_change(cb, _FakeState("half-open"), _FakeState("open"))
    assert cb.reset_timeout == 120

    # Close resets
    listener.state_change(cb, _FakeState("half-open"), _FakeState("closed"))
    assert cb.reset_timeout == 60
