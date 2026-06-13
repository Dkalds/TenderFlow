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

    def get(self, loader: Callable[[], _T]) -> _T:
        """Devuelve el valor cacheado si sigue fresco; si no, llama a ``loader``."""
        now = time.time()
        sig = get_signal_timestamp()
        fresh = (
            self._valid
            and (now - self._loaded_at) < self._ttl
            and sig <= self._signal_ts
        )
        if fresh:
            return cast("_T", self._value)
        value = loader()
        self._value = value
        self._loaded_at = now
        self._signal_ts = sig
        self._valid = True
        return value

    def clear(self) -> None:
        """Invalida la caché (tras una ingesta o en tests)."""
        self._value = None
        self._loaded_at = 0.0
        self._signal_ts = -1.0
        self._valid = False
