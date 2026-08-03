"""Caché en memoria, consciente de la señal de invalidación de ingesta.

Envuelve cargas de datos costosas de la capa de servicios. Sirve el valor
cacheado mientras (a) no haya expirado el TTL y (b) no exista una señal de
invalidación de caché más reciente que la última carga (ver
:mod:`shared.cache_signal`, que el scraper actualiza al final de cada
ingesta exitosa).

Pensado para cargas sin argumentos que devuelven estructuras de **solo
lectura** y ACOTADAS (hoy: las señales agregadas de scoring). Las cargas
full-table de licitaciones/adjudicaciones que motivaron esta caché — y el
cortacircuitos ``render_api_full_table_loads_blocked`` que las bloqueaba en
Render — se retiraron al completar ADR-023: la analítica agrega en Postgres.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Generic, TypeVar

from shared.cache_signal import get_signal_timestamp

_T = TypeVar("_T")

# TTL por defecto: cota superior de obsolescencia aunque la señal compartida
# no se escriba. La invalidación principal es por ingesta real.
_DEFAULT_TTL = 600.0


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
        # El valor se lee a un local antes de comprobar la frescura: un refresco
        # concurrente pone ``_value`` a None mientras construye el reemplazo, y
        # sin el local un lector podría comprobar la frescura y leer el None de
        # esa ventana como si fuera el dato. Con el local, lo peor que pasa es
        # caer al camino con lock y esperar al valor nuevo.
        cached = self._value
        if cached is not None and self._is_fresh():
            return cached
        with self._lock:
            cached = self._value
            if cached is not None and self._is_fresh():
                return cached
            # Soltar TODA referencia al valor anterior ANTES de llamar al
            # loader: el atributo y también el local de este frame, que si no
            # mantiene vivo el objeto durante toda la construcción del nuevo.
            # Estas cachés guardan cargas full-table (DataFrame de licitaciones,
            # lista de adjudicaciones⋈licitaciones); con la instancia vieja viva
            # mientras se construye la nueva, ambas coexisten durante todo el
            # loader() y cada refresco pica al doble del tamaño de la caché. Con
            # TTL de 60 s ese pico se repite cada minuto bajo tráfico.
            cached = None
            self._valid = False
            self._value = None
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
