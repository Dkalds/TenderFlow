"""Rastro contable de los errores que un camino best-effort captura y no propaga.

Un ``except Exception`` que deja una línea de log y sigue es correcto donde el
fallo no puede tumbar a quien llama (persistir la salud de una fuente, avisar
de un paso roto, devolver una conexión al pool). Lo que no es correcto es que
ese fallo, repetido en cada pasada, no deje ninguna serie que pueda alertar:
un ``log.warning`` en un runner efímero de Actions se pierde con el runner.

:class:`ContadorDeErrores` da a cada módulo caliente un contador
``<modulo>_errores_total{paso}`` y lo complementa con un evento en
``ops_events``. Las dos mitades cubren los dos planos:

- El contador de Prometheus se vigila en ``observability/alert_rules.yml``
  donde el proceso es scrapeable (la API: ``db/connection.py`` y
  ``llm/client.py`` corren ahí).
- El evento ``error_capturado:<modulo>:<paso>`` llega a la base por el flush de
  ``ops_events`` y lo lee ``scheduler/healthcheck.py`` cada 6 h, que es la única
  vía que ve los procesos efímeros (scraper, cierre de la pasada, pliegos).
  :func:`errores_repetidos` es el umbral común de los dos lados.

El log lo sigue escribiendo el llamador, con su propio logger y su contexto: el
contador no lo sustituye, lo hace alertable.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import TYPE_CHECKING

from observability.ops_events import record_event

if TYPE_CHECKING:
    from observability.runtime_metrics import _CounterMetric

#: Prefijo del ``event_type`` en ``ops_events``. Lleva módulo y paso en el
#: propio tipo para que el ``GROUP BY event_type`` que el healthcheck ya hace
#: los cuente por separado sin SQL nuevo.
PREFIJO_EVENTO = "error_capturado:"

#: A partir de cuántos errores del mismo paso, en la ventana de cada lado (1 h
#: en Prometheus, 6 h en el healthcheck), el fallo deja de ser un accidente.
#: ``tests/test_observabilidad_errores.py`` comprueba que las reglas de
#: ``alert_rules.yml`` usan este mismo número.
UMBRAL_REPETIDO = 5

#: Eventos por (módulo, paso) y proceso como máximo. Un bucle de diez mil
#: documentos que fallan igual no necesita diez mil filas en ``ops_events``:
#: basta con pasar holgadamente el umbral. El contador de Prometheus y el log sí
#: cuentan todos.
_TOPE_EVENTOS_POR_PASO = 4 * UMBRAL_REPETIDO

_lock = threading.Lock()
_eventos_emitidos: dict[str, int] = {}


class ContadorDeErrores:
    """Cuenta los errores capturados de un módulo, por paso.

    Uso, dentro del ``except`` y junto al log que ya existía::

        _contar_error = ContadorDeErrores("db_connection", db_connection_errores_total)
        ...
        except Exception:
            _contar_error("ping")
            log.warning("db_ping_failed", exc_info=True)

    ``paso`` debe ser un literal: es una etiqueta de Prometheus y su
    cardinalidad tiene que estar acotada por el código, no por los datos.
    """

    def __init__(self, modulo: str, contador: _CounterMetric) -> None:
        self.modulo = modulo
        self._contador = contador

    def __call__(self, paso: str) -> None:
        self._contador.labels(paso=paso).inc()
        tipo = f"{PREFIJO_EVENTO}{self.modulo}:{paso}"
        with _lock:
            emitidos = _eventos_emitidos.get(tipo, 0)
            if emitidos >= _TOPE_EVENTOS_POR_PASO:
                return
            _eventos_emitidos[tipo] = emitidos + 1
        record_event(tipo, value=1.0)


def errores_repetidos(conteos: Mapping[str, int]) -> dict[str, int]:
    """Los ``módulo:paso`` que llegan al umbral, de un conteo por ``event_type``.

    ``conteos`` es lo que el healthcheck ya agrega de ``ops_events``
    (``{event_type: n}``); se queda con los errores capturados y devuelve
    ``{"módulo:paso": n}`` para los que pasan :data:`UMBRAL_REPETIDO`.
    """
    return {
        tipo.removeprefix(PREFIJO_EVENTO): n
        for tipo, n in sorted(conteos.items())
        if tipo.startswith(PREFIJO_EVENTO) and n >= UMBRAL_REPETIDO
    }


def _reiniciar_para_tests() -> None:
    """Olvida el tope por paso (solo tests)."""
    with _lock:
        _eventos_emitidos.clear()
