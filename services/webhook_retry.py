"""Reintento y re-entrega de webhooks (C2.4).

``db/webhooks.py::_record_delivery`` contaba fallos y **desactivaba el webhook**
al llegar al umbral. Sin backoff, sin reintento y sin re-entrega: cero
coincidencias de ``retry`` ni ``backoff`` en el módulo.

El resultado práctico: un endpoint que devuelve 503 durante un despliegue de
tres minutos pierde los eventos de esos tres minutos y, si coinciden tres, se
queda además desactivado. Al cliente le dejan de llegar avisos y nadie le dice
por qué.

Aquí vive el **criterio** (cuándo toca el siguiente intento, cuándo se da por
perdido, cuándo se desactiva el webhook). El SQL está en
``db/repositories/webhooks.py`` y el transporte HTTP sigue en ``db/webhooks.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from observability.logging import get_logger

log = get_logger(__name__)

#: Intentos totales, incluido el primero.
#:
#: Seis, y no más, porque el sexto cae ya a seis horas del evento: pasado ese
#: punto el aviso ha perdido su valor —un plazo que vencía hoy venció— y seguir
#: reintentando solo añade tráfico contra un endpoint que probablemente no
#: vuelve.
MAX_INTENTOS = 6

#: Espera del primer reintento.
ESPERA_INICIAL = timedelta(minutes=1)

#: Techo de la espera. El plan lo fija en seis horas.
ESPERA_MAXIMA = timedelta(hours=6)


def espera_para(intento: int) -> timedelta | None:
    """Cuánto esperar antes del intento *intento* (1-indexado).

    Backoff exponencial desde un minuto, con techo de seis horas:

    ===========  ==========
    Intento      Espera
    ===========  ==========
    1            —  (inmediato)
    2            1 min
    3            2 min
    4            4 min
    5            8 min
    6            16 min
    ===========  ==========

    Devuelve ``None`` cuando ya no quedan intentos, que es lo que distingue
    «espera cero» de «no reintentar». Confundirlas haría un bucle.

    El techo de seis horas no llega a aplicarse con `MAX_INTENTOS = 6`; existe
    porque subir ese número es una decisión de operación razonable y el techo
    tiene que estar puesto **antes**, no después de descubrir que el sexto
    reintento cae a dos días.
    """
    if intento <= 1:
        return timedelta(0)
    if intento > MAX_INTENTOS:
        return None
    espera: timedelta = ESPERA_INICIAL * (2 ** (intento - 2))
    return espera if espera < ESPERA_MAXIMA else ESPERA_MAXIMA


@dataclass(frozen=True, slots=True)
class Decision:
    """Qué hacer tras un intento de entrega."""

    estado: str
    #: Cuándo toca el siguiente intento. `None` si no hay más.
    proximo_intento: datetime | None
    #: Si el webhook debe desactivarse. **Solo tras agotar los reintentos.**
    desactivar: bool


def decidir(*, exito: bool, intentos_hechos: int, ahora: datetime | None = None) -> Decision:
    """Decide el destino de una entrega tras un intento.

    La regla que cambia respecto a lo anterior: **el webhook solo se desactiva
    cuando la entrega agota sus reintentos**, no al primer fallo contado. Un
    endpoint que falla tres veces y responde 200 a la cuarta termina en
    ``delivered`` y deja el contador de fallos del webhook en cero — que es
    exactamente lo que ocurre durante un despliegue del receptor.
    """
    momento = ahora or datetime.now(UTC)

    if exito:
        return Decision(estado="delivered", proximo_intento=None, desactivar=False)

    siguiente = intentos_hechos + 1
    espera = espera_para(siguiente)
    if espera is None:
        log.warning("webhook_delivery_agotada", intentos=intentos_hechos)
        return Decision(estado="failed", proximo_intento=None, desactivar=True)

    return Decision(
        estado="pending",
        proximo_intento=momento + espera,
        desactivar=False,
    )
