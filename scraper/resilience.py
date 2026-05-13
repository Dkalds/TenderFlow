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

from config import settings
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


class _AdaptiveBackoffListener(pybreaker.CircuitBreakerListener):
    """Ajusta ``reset_timeout`` con backoff exponencial entre aperturas consecutivas.

    Cada vez que el circuito se abre, el timeout se dobla respecto al anterior
    (hasta ``max_timeout``). Al cerrarse exitosamente, se resetea al ``base_timeout``.
    Sustituye a ``_BreakerLogger`` — también registra los cambios de estado.
    """

    def __init__(self, base_timeout: int, max_timeout: int) -> None:
        self._base_timeout = base_timeout
        self._max_timeout = max_timeout
        self._consecutive_opens = 0

    def state_change(
        self,
        cb: pybreaker.CircuitBreaker,
        old_state: object,
        new_state: object,
    ) -> None:
        new_name = str(getattr(new_state, "name", new_state))
        old_name = str(getattr(old_state, "name", old_state))

        if new_name == "open":
            self._consecutive_opens += 1
            new_timeout = min(
                self._base_timeout * (2 ** (self._consecutive_opens - 1)),
                self._max_timeout,
            )
            cb.reset_timeout = new_timeout
            log.warning(
                "placsp_breaker_state_change",
                old_state=old_name,
                new_state=new_name,
                fail_counter=cb.fail_counter,
                consecutive_opens=self._consecutive_opens,
                next_reset_timeout_s=new_timeout,
            )
        elif new_name == "closed":
            self._consecutive_opens = 0
            cb.reset_timeout = self._base_timeout
            log.info(
                "placsp_breaker_state_change",
                old_state=old_name,
                new_state=new_name,
                fail_counter=cb.fail_counter,
                reset_timeout_s=self._base_timeout,
            )
        else:
            log.info(
                "placsp_breaker_state_change",
                old_state=old_name,
                new_state=new_name,
                fail_counter=cb.fail_counter,
            )


placsp_breaker = pybreaker.CircuitBreaker(
    fail_max=5,
    reset_timeout=60 * 5,
    exclude=[ValueError],
    listeners=[
        _AdaptiveBackoffListener(
            base_timeout=settings.BREAKER_BASE_TIMEOUT,
            max_timeout=settings.BREAKER_MAX_TIMEOUT,
        )
    ],
    name="placsp",
)
