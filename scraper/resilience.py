"""Capas de resiliencia para llamadas de red del scraper.

- ``http_retry``: decorador tenacity con backoff exponencial + jitter, que
  reintenta solo en errores transitorios (timeouts, 5xx, 429, conn errors).
- ``placsp_breaker``: circuit breaker que se abre tras 5 fallos consecutivos,
  evitando saturar la plataforma cuando está caída. ``ted_breaker`` y
  ``pscp_breaker`` son sus gemelos para los documentos de esas plataformas;
  ``breaker_para_host`` elige el que toca.

El breaker ignora ``ValueError`` (validación de tamaño o URL) porque no son
fallos del servidor — un payload malicioso no debería abrir el circuito.
"""

from __future__ import annotations

import logging
import re

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
        codigo = status_de(exc)
        if codigo is None:
            # Sin ``response`` y sin código en el mensaje no hay con qué decidir.
            return True
        # Un 4xx o una redirección dan lo mismo al cuarto intento que al
        # primero; 408 y 429 son los dos 4xx que piden justamente esperar.
        return bool(500 <= codigo < 600 or codigo in (408, 429))
    return False


def status_de(exc: requests.HTTPError) -> int | None:
    """Código HTTP de un ``HTTPError``, venga de donde venga.

    ``PinnedHttpsResponse.raise_for_status`` (shared/outbound_http.py) construye
    el error **sin** ``response=``, así que ``exc.response`` es ``None`` en toda
    la ruta de descarga de documentos y leer ``exc.response.status_code`` a
    secas no detecta nada: ni la causa de un 500 al etiquetarlo, ni que un 404
    no merece reintento. Se cae entonces al texto del mensaje, cuyo formato fija
    esa misma función; ``test_resilience`` y ``test_document_fetcher`` ejercitan
    el ``raise_for_status`` real para que un cambio de redacción rompa los tests
    en vez de dejar la clasificación muda.
    """
    respuesta = getattr(exc, "response", None)
    codigo = getattr(respuesta, "status_code", None)
    if isinstance(codigo, int):
        return codigo
    match = re.search(r"\b(\d{3})\b", str(exc))
    return int(match.group(1)) if match else None


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

        # D1: exportar estado a Prometheus (0=closed, 1=half-open, 2=open)
        try:
            from observability.runtime_metrics import (
                scraper_circuit_state,
                scraper_circuit_transitions_total,
            )

            mapping = {"closed": 0, "half-open": 1, "open": 2}
            scraper_circuit_state.labels(source=cb.name).set(mapping.get(new_name, 0))
            scraper_circuit_transitions_total.labels(from_state=old_name, to_state=new_name).inc()
        except Exception:
            pass

        if new_name == "open":
            self._consecutive_opens += 1
            new_timeout = min(
                self._base_timeout * (2 ** (self._consecutive_opens - 1)),
                self._max_timeout,
            )
            cb.reset_timeout = new_timeout
            log.warning(
                "placsp_breaker_state_change",
                breaker=cb.name,
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
                breaker=cb.name,
                old_state=old_name,
                new_state=new_name,
                fail_counter=cb.fail_counter,
                reset_timeout_s=self._base_timeout,
            )
        else:
            log.info(
                "placsp_breaker_state_change",
                breaker=cb.name,
                old_state=old_name,
                new_state=new_name,
                fail_counter=cb.fail_counter,
            )


def _nuevo_breaker(nombre: str) -> pybreaker.CircuitBreaker:
    return pybreaker.CircuitBreaker(
        fail_max=5,
        reset_timeout=settings.BREAKER_BASE_TIMEOUT,
        exclude=[ValueError],
        listeners=[
            _AdaptiveBackoffListener(
                base_timeout=settings.BREAKER_BASE_TIMEOUT,
                max_timeout=settings.BREAKER_MAX_TIMEOUT,
            )
        ],
        name=nombre,
    )


placsp_breaker = _nuevo_breaker("placsp")

#: Un circuito por plataforma de la que se descargan documentos. Con uno solo,
#: cinco fallos seguidos de TED o de la plataforma catalana abrían el de PLACSP
#: y paraban también la descarga de sus pliegos, que es el grueso del lote.
ted_breaker = _nuevo_breaker("ted")
pscp_breaker = _nuevo_breaker("pscp")

_BREAKERS_POR_HOST: tuple[tuple[str, pybreaker.CircuitBreaker], ...] = (
    ("ted.europa.eu", ted_breaker),
    ("contractaciopublica.cat", pscp_breaker),
)


def breaker_para_host(host: str | None) -> pybreaker.CircuitBreaker:
    """El circuito de la plataforma que sirve *host*; PLACSP para el resto.

    PLACSP es el defecto porque es lo que era el único circuito hasta ahora: un
    host que no esté en la tabla se comporta exactamente como antes.
    """
    host_l = (host or "").lower()
    for dominio, breaker in _BREAKERS_POR_HOST:
        if host_l == dominio or host_l.endswith("." + dominio):
            return breaker
    return placsp_breaker
