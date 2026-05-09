"""Capas de resiliencia para llamadas de red del scraper.

- ``http_retry``: decorador tenacity con backoff exponencial + jitter, que
  reintenta solo en errores transitorios (timeouts, 5xx, 429, conn errors).
- ``placsp_breaker``: circuit breaker que se abre tras 5 fallos consecutivos,
  evitando saturar la plataforma cuando está caída.

El breaker ignora ``ValueError`` (validación de tamaño o URL) porque no son
fallos del servidor — un payload malicioso no debería abrir el circuito.
"""

from __future__ import annotations

import logging

import pybreaker
import requests
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from observability.logging import get_logger

log = get_logger(__name__)

# tenacity's before_sleep_log requires a stdlib logger
_stdlib_log = logging.getLogger(__name__)


def _is_transient(exc: BaseException) -> bool:
    """Reintenta solo en errores transitorios de red y 5xx/429."""
    if isinstance(exc, requests.ConnectionError | requests.Timeout):
        return True
    if isinstance(exc, requests.HTTPError):
        resp = getattr(exc, "response", None)
        if resp is None:
            return True
        return bool(500 <= resp.status_code < 600 or resp.status_code in (408, 429))
    return False


http_retry = retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential_jitter(initial=2, max=30, jitter=2),
    retry=retry_if_exception(_is_transient),
    before_sleep=before_sleep_log(_stdlib_log, logging.WARNING),
    reraise=True,
)


class _BreakerLogger(pybreaker.CircuitBreakerListener):
    def state_change(
        self,
        cb: pybreaker.CircuitBreaker,
        old_state: object,
        new_state: object,
    ) -> None:
        log.warning(
            "placsp_breaker_state_change",
            old_state=str(getattr(old_state, "name", old_state)),
            new_state=str(getattr(new_state, "name", new_state)),
            fail_counter=cb.fail_counter,
        )


placsp_breaker = pybreaker.CircuitBreaker(
    fail_max=5,
    reset_timeout=60 * 5,
    exclude=[ValueError],
    listeners=[_BreakerLogger()],
    name="placsp",
)
