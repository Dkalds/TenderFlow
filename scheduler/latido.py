"""Latido externo del healthcheck: la señal de que el vigilante sigue vivo.

El healthcheck avisa por correo cuando algo va mal. Lo que no puede avisar es
de su propia ausencia: si el plano de cron deja de ejecutarlo (un workflow
desactivado, un cutover a medias, el hilo de cron del worker muerto) o si el
SMTP deja de entregar, el silencio se lee como «todo bien». Entre el
2026-09-05 y el 2026-09-18 la ingesta diaria estuvo en rojo sesenta pasadas
seguidas sin que nadie actuara.

Un *dead-man's switch* le da la vuelta: un servicio externo (healthchecks.io,
Better Stack, Cronitor) espera una petición cada pocas horas y es él quien
avisa, por su propio canal, cuando deja de llegar. Este módulo hace esa
petición al final de cada healthcheck con alertas.

Es opt-in por ``HEALTHCHECK_HEARTBEAT_URL``: sin la variable no hace nada. Con
un estado ``critical`` tampoco late: un crítico sostenido acaba disparando el
interruptor por un canal que no depende del correo.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import requests

from observability import get_logger
from shared.outbound_http import pinned_https_request

log = get_logger(__name__)

_TIMEOUT_SEGUNDOS = 10.0
_INTENTOS = 2
_USER_AGENT = "tenderflow-healthcheck"


def enviar_latido(result: dict[str, Any]) -> bool:
    """Hace la petición de latido si procede. True si el servicio la aceptó.

    Nunca lanza: un latido que falla no puede tumbar el chequeo que lo emite.
    """
    import config

    url = config.settings.HEALTHCHECK_HEARTBEAT_URL.get_secret_value().strip()
    if not url:
        return False
    if result.get("status") == "critical":
        log.info("latido_omitido", motivo="estado critical")
        return False

    # La URL lleva el identificador del check y vale como credencial: a los
    # logs solo va el host.
    host = urlsplit(url).hostname or ""
    for intento in range(1, _INTENTOS + 1):
        try:
            with pinned_https_request(
                "GET",
                url,
                headers={"User-Agent": _USER_AGENT},
                timeout_seconds=_TIMEOUT_SEGUNDOS,
                allowed_hosts=frozenset({host}),
            ) as respuesta:
                respuesta.raise_for_status()
        except (requests.RequestException, ValueError, OSError) as exc:
            log.warning("latido_fallido", host=host, intento=intento, error=type(exc).__name__)
        else:
            log.info("latido_enviado", host=host, estado=result.get("status"))
            return True
    return False


__all__ = ["enviar_latido"]
