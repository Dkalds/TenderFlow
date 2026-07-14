"""Caché en memoria, consciente de la señal de invalidación de ingesta.

Envuelve cargas de datos costosas (lecturas de tabla completa) de la capa de
servicios. Sirve el valor cacheado mientras (a) no haya expirado el TTL y
(b) no exista una señal de invalidación de caché más reciente que la última
carga (ver :mod:`shared.cache_signal`, que el scraper actualiza al final de
cada ingesta exitosa).

Pensado para cargas sin argumentos que devuelven estructuras de **solo
lectura**: los consumidores construyen ``pandas.DataFrame`` nuevos a partir del
valor, por lo que compartir la misma lista entre llamadas es seguro.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Generic, TypeVar, cast

from shared.cache_signal import get_signal_timestamp

_T = TypeVar("_T")

# TTL por defecto: cota superior de obsolescencia aunque la señal de ingesta
# no se escriba (defensivo). La invalidación principal es por señal.
_DEFAULT_TTL = 60.0


class SignalAwareCache(Generic[_T]):
    """Caché de un único valor con invalidación por TTL + señal de ingesta."""

    def __init__(self, ttl: float = _DEFAULT_TTL) -> None:
        self._ttl = ttl
        self._value: _T | None = None
        self._loaded_at = 0.0
        self._signal_ts = -1.0
        self._valid = False
        self._lock = threading.Lock()

    def get(self, loader: Callable[[], _T]) -> _T:
        """Devuelve el valor cacheado si sigue fresco; si no, llama a ``loader``.

        Serializado con un lock: sin esto, N requests concurrentes con caché
        fría (típico justo tras un reinicio) llaman a ``loader()`` en paralelo,
        cada una construyendo su propia copia de la carga full-table al mismo
        tiempo — el pico de memoria se multiplica por N en vez de servirse una
        sola vez. Ver postmortem OOM Render 2026-07-14.
        """
        if self._is_fresh():
            return cast("_T", self._value)
        with self._lock:
            if self._is_fresh():
                return cast("_T", self._value)
            value = loader()
            self._value = value
            self._loaded_at = time.time()
            self._signal_ts = get_signal_timestamp()
            self._valid = True
            return value

    def _is_fresh(self) -> bool:
        return (
            self._valid
            and (time.time() - self._loaded_at) < self._ttl
            and get_signal_timestamp() <= self._signal_ts
        )

    def clear(self) -> None:
        """Invalida la caché (tras una ingesta o en tests)."""
        with self._lock:
            self._value = None
            self._loaded_at = 0.0
            self._signal_ts = -1.0
            self._valid = False
