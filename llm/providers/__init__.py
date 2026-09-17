"""Proveedores LLM disponibles.

Además, lo que comparten los providers: el error de credencial rechazada y las
utilidades para respetar la señal de parada del consumidor
(``stream_llm_response(stop=...)`` en ``llm/client.py``).
"""

from __future__ import annotations

import threading
import time

# Códigos con los que un proveedor dice «esta credencial no vale». No son
# transitorios —reintentar no los arregla— ni tampoco una respuesta vacía.
AUTH_HTTP_CODES: frozenset[int] = frozenset({401, 403})


class LLMAuthError(RuntimeError):
    """El proveedor rechazó la API key (HTTP 401/403).

    Los providers se tragan el resto de fallos y devuelven un stream vacío, que
    los consumidores ya saben degradar. Una credencial rechazada no es un fallo
    más: se repite idéntica en cada llamada que use esa key, y convertida en
    «respuesta vacía» esconde la causa. El scrape diario estuvo en rojo del
    2026-09-05 al 2026-09-10 con `NVIDIA_API_KEY` devolviendo 401 en todas las
    llamadas, mientras la alerta repetía «El LLM devolvió una respuesta vacía»
    doscientas veces por corrida.
    """

    def __init__(self, *, model: str, status_code: int) -> None:
        self.model = model
        self.status_code = status_code
        super().__init__(
            f"El proveedor rechazó la API key (HTTP {status_code}) para {model}: "
            "la credencial no es válida y hay que rotarla"
        )


def stop_requested(stop: threading.Event | None) -> bool:
    """True si el consumidor pidió parar. Sin señal (jobs sin timeout), nunca."""
    return stop is not None and stop.is_set()


def backoff_wait(seconds: float, stop: threading.Event | None) -> None:
    """Espera de backoff entre intentos, cortada en cuanto llega la parada.

    Sin ``stop`` es un ``time.sleep`` corriente. Con ella, el backoff no retrasa
    el final del hilo: quien llama vuelve a comprobar ``stop`` al principio del
    intento siguiente y sale sin abrir otra petición.
    """
    if stop is None:
        time.sleep(seconds)
    else:
        stop.wait(seconds)
