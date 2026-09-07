"""Reenvío de las entregas de webhook pendientes (C2.4).

`services/webhook_retry.py` decide **cuándo** toca el siguiente intento y
`db/webhooks.py::reenviar` sabe **cómo** repetirlo sin cambiar el cuerpo ni el
identificador. Sin este job las dos cosas serían una capacidad sin puerta: la
entrega quedaría `pending` con su `proximo_intento` puesto y nadie la miraría
nunca — el mismo defecto que el hecho 3 del plan describe para los similares.

**Cadencia y su límite.** El job se declara en el plano `pipeline`, así que en
producción corre con la pasada canónica (cada cuatro horas). El backoff empieza
en un minuto, de modo que el primer reintento *efectivo* no llega antes de la
siguiente pasada: hoy el reintento recupera al receptor que estuvo caído horas,
no al que estuvo caído noventa segundos. Ganar esa resolución pide un workflow
programado propio —cada cinco minutos— y crear un workflow es un gate de
AGENTS.md §6 que este plan no pre-autoriza; queda escrito aquí para que quien lo
autorice sepa qué compra. En el plano `loop` (docker-compose) el intervalo del
registro sí manda y la resolución es la del backoff.
"""

from __future__ import annotations

from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

#: Tope de entregas por pasada.
#:
#: Un receptor caído un día acumula tantas entregas como eventos hubo. Drenarlas
#: todas de una vez convierte el job en una tormenta de peticiones contra un
#: endpoint que probablemente sigue caído; las que no entren mantienen su
#: `proximo_intento` vencido y salen en la pasada siguiente, en orden.
MAX_POR_PASADA = 200


def run(*, limit: int = MAX_POR_PASADA) -> dict[str, Any]:
    """Reenvía las entregas cuyo `proximo_intento` ya venció.

    Returns:
        Contadores de la pasada: `pendientes` vistas, `entregadas`, `fallidas`.
    """
    from db.database import now_utc_iso
    from db.repositories.webhooks import pendientes_de_reintento
    from db.webhooks import reenviar

    ahora = now_utc_iso()
    try:
        pendientes = pendientes_de_reintento(ahora=ahora, limit=limit)
    except Exception:
        # La tabla puede no tener aún las columnas de v118 (entorno sin migrar).
        # El job es advisory: no puede tumbar la pasada por eso.
        log.warning("webhook_reintentos_query_failed", exc_info=True)
        return {"pendientes": 0, "entregadas": 0, "fallidas": 0}

    entregadas = 0
    for entrega in pendientes:
        if reenviar(entrega):
            entregadas += 1

    resultado = {
        "pendientes": len(pendientes),
        "entregadas": entregadas,
        "fallidas": len(pendientes) - entregadas,
    }
    if pendientes:
        log.info("webhook_reintentos_completado", **resultado)
    return resultado
