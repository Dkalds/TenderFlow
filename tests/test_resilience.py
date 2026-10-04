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


def _http_error_del_transporte_fijado(status_code: int) -> requests.HTTPError:
    """El ``HTTPError`` que da el ``raise_for_status`` real del transporte fijado.

    ``PinnedHttpsResponse`` lo construye sin ``response=``: el estado solo va en
    el mensaje. Se usa el método de verdad, y no un error fabricado aquí, para
    que un cambio en su redacción rompa estos tests en vez de devolver la
    clasificación a «no sé qué estado es, reintento».
    """
    from shared.outbound_http import PinnedHttpsResponse

    respuesta = PinnedHttpsResponse.__new__(PinnedHttpsResponse)
    respuesta.status_code = status_code
    with pytest.raises(requests.HTTPError) as fallo:
        respuesta.raise_for_status()
    return fallo.value


@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 410])
def test_estado_del_transporte_fijado_que_repetir_no_cambia_no_se_reintenta(status):
    """Un 404, un 403 o una redirección dan lo mismo al cuarto intento que al primero.

    Sin ``response`` se tomaban todos por transitorios: cuatro peticiones y
    ~19 s de espera por cada documento, para acabar en el mismo error.
    """
    exc = _http_error_del_transporte_fijado(status)

    assert exc.response is None
    assert not _is_transient(exc)


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_estado_transitorio_del_transporte_fijado_se_reintenta(status):
    assert _is_transient(_http_error_del_transporte_fijado(status))


def test_http_error_sin_estado_legible_sigue_siendo_transitorio():
    """Sin ``response`` y sin código en el mensaje no hay con qué decidir: como antes."""
    assert _is_transient(requests.HTTPError("el servidor contestó algo ilegible"))


def test_status_de_prefiere_la_respuesta_y_cae_al_mensaje():
    from scraper.resilience import status_de

    con_respuesta = requests.HTTPError("503 Server Error")
    con_respuesta.response = _FakeResp(404)

    assert status_de(con_respuesta) == 404
    assert status_de(_http_error_del_transporte_fijado(410)) == 410
    assert status_de(requests.HTTPError("sin código")) is None


def test_http_retry_pide_una_sola_vez_un_404_del_transporte_fijado():
    calls = {"n": 0}

    @http_retry
    def _pedir():
        calls["n"] += 1
        raise _http_error_del_transporte_fijado(404)

    with pytest.raises(requests.HTTPError):
        _pedir()
    assert calls["n"] == 1


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
