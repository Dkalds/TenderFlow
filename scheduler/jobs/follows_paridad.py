"""Mide la paridad de ``follows`` en cada pasada y deja el número en ``ops_events``.

Por qué es un paso de la pipeline y no solo un script
-----------------------------------------------------
ADR-031 §B pone una condición antes de mover una sola lectura a ``follows``:
reproducir, para cada usuario, favoritos + empresas + descartes desde la tabla
unificada con **cero diferencias**, medido **contra producción**.

Esa medición existía desde el primer día (``scripts/check_follows_paridad.py``)
y no la ejecutaba nadie. Figuraba en el plan como «acción humana: ejecutar el
script contra producción», que es una forma educada de decir que la migración
esperaba a que alguien se acordara. Un número que hay que ir a buscar no es un
número que exista.

Como paso de la pasada, la condición de ADR-031 se cumple sola: cada día queda
un registro de cuántas filas faltan, y el humano pasa de «ejecutar el script» a
«mirar si lleva N días en cero». Eso es lo único que hace este job — **no
repara, no escribe en `follows`, no mueve ninguna lectura**. Retirar los
endpoints antiguos sigue siendo una decisión con RFC (ADR-031 §B punto 3).

Cadencia diaria, no cada cuatro horas: compara tres tablas enteras y el número
no se mueve en horas. ``_run_periodic`` se encarga.

Advisory a propósito: que la paridad esté rota no rompe la pasada de ingesta,
y ningún cliente nota nada. Lo que sí hace es dejarlo en el log como aviso y en
``ops_events`` como serie, que es donde se mira antes de decidir.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from observability.logging import get_logger

log = get_logger(__name__)

#: Tipo del evento en ``ops_events``. El ``value`` es ``faltan`` agregado: es
#: el único que bloquea la migración (ver la cabecera del script de paridad).
TIPO_EVENTO = "follows_paridad_faltan"


@dataclass(slots=True)
class Resumen:
    """Lo que la pasada deja dicho. Los tres pares agregados."""

    pares: int = 0
    filas_origen: int = 0
    filas_follows: int = 0
    faltan: int = 0
    sobran: int = 0
    usuarios_con_diferencias: int = 0

    @property
    def ok(self) -> bool:
        """La condición de ADR-031 §B: ni una fila de origen sin reflejar."""
        return self.faltan == 0


def ejecutar() -> Resumen:
    """Una medición. **No lanza**: ver la cabecera (es advisory)."""
    from observability.ops_events import record_event
    from scripts.check_follows_paridad import medir

    resumen = Resumen()
    try:
        # `detalle=0`: los ejemplos son `user_key` y `target_id` de personas
        # reales, y esto va a un registro que se consulta sin más ceremonia. El
        # que quiera los ejemplos corre el script a mano y los ve en su pantalla.
        diferencias = medir(detalle=0)
    except Exception:
        log.warning("follows_paridad_medicion_fallida", exc_info=True)
        return resumen

    resumen.pares = len(diferencias)
    for d in diferencias:
        resumen.filas_origen += d.filas_origen
        resumen.filas_follows += d.filas_follows
        resumen.faltan += d.faltan
        resumen.sobran += d.sobran
        resumen.usuarios_con_diferencias += d.usuarios_con_diferencias

    detalle = json.dumps(
        {
            d.tabla: {"faltan": d.faltan, "sobran": d.sobran, "origen": d.filas_origen}
            for d in diferencias
        },
        ensure_ascii=False,
    )
    record_event(TIPO_EVENTO, value=float(resumen.faltan), detail=detalle)

    if resumen.ok:
        log.info(
            "follows_paridad_ok",
            filas_origen=resumen.filas_origen,
            filas_follows=resumen.filas_follows,
            sobran=resumen.sobran,
        )
    else:
        # Aviso y no error: la pasada no está rota. Lo que está roto es la
        # condición para migrar, y quien la mira es una persona, no el exit code.
        log.warning(
            "follows_paridad_bloquea",
            faltan=resumen.faltan,
            usuarios=resumen.usuarios_con_diferencias,
            detalle=detalle,
        )
    return resumen


def run() -> None:
    """Punto de entrada del paso canónico."""
    ejecutar()
