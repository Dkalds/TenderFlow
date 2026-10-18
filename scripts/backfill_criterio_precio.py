"""Backfill de ``es_precio`` y ``peso_precio_pct`` con la regla nueva del precio.

``_es_criterio_precio`` decidía por texto en CODICE, y la etiqueta genérica
«…mera aplicación de fórmulas, diferentes al precio» marcaba como precio el
criterio que no lo era (FOGASA 20/2026: ``peso_precio_pct`` 18 en vez de 42).
La regla nueva (``scraper.codice_parser.criterio_es_precio``) usa el código
``OBJ``/``1`` y descarta las menciones negadas; este script la aplica a las
filas ya guardadas en vez de esperar a que cada anuncio se re-ingiera.

Medido en producción el 2026-10-17, antes del primer pase: 322 licitaciones con
algún ``es_precio`` distinto y 280 con ``peso_precio_pct`` distinto (163 suben,
117 bajan).

Recalcula desde ``licitacion_criterios_adjudicacion``, sin leer el feed: la
regla solo necesita tipo, subtipo, descripción, peso, padre y lote, y todo eso
está guardado. Lo que sí puede diferir de una re-ingesta: el parser lee el
texto de **todos** los ``Description``/``Name`` del criterio y la fila guarda
el primero. Un criterio cuyo precio solo se nombrase en el segundo saldría
distinto aquí; la siguiente re-ingesta lo deja como diga el parser.

Las garantías de escritura (bloqueo por lote, qué peso se pisa y cuál no) están
en ``db/criterios_precio.py`` (ADR-022): este script solo orquesta y pone la
regla.

**Orden de despliegue.** Correrlo *después* de desplegar el parser con la regla
nueva. Antes, cada ingesta volvería a escribir las marcas viejas en lo que
toque, y habría que repetir el pase.

**Fuera de alcance.** ``ml_proba`` usa ``peso_precio_pct`` como feature: las
licitaciones corregidas conservan la probabilidad calculada con el peso viejo
hasta el siguiente scoring.

Uso::

    python -m scripts.backfill_criterio_precio --verificar --detalle   # no escribe
    python -m scripts.backfill_criterio_precio                         # reescribe
    python -m scripts.backfill_criterio_precio --desde '20/2025' --max-lotes 5

Salida 0 si terminó (y, con ``--verificar``, si no queda nada por cambiar); 1 si
la verificación encontró cambios pendientes; 2 si un lote agotó los reintentos.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from collections.abc import Callable

from db.criterios_precio import (
    CriterioGuardado,
    CriteriosDeLicitacion,
    Lote,
    Recalculo,
    recalcular_lote,
)
from observability.logging import get_logger
from scraper.codice_parser import (
    ambito_codifica_precio,
    criterio_es_precio,
    peso_precio_de_criterios,
)

log = get_logger(__name__)

_REINTENTOS = 5


def recalcular(lic: CriteriosDeLicitacion) -> Recalculo:
    """Aplica la regla del parser a las filas guardadas de una licitación.

    Mismos ámbitos que el parser: el expediente y cada lote por separado, cada
    uno con sus subcriterios. ``peso_precio_pct`` sale, como en
    ``parse_peso_precio``, de los criterios raíz del expediente.
    """
    ambitos: dict[str | None, list[CriterioGuardado]] = defaultdict(list)
    for criterio in lic.criterios:
        ambitos[criterio.lote_numero].append(criterio)

    nuevas: dict[int, bool] = {}
    for criterios in ambitos.values():
        codifica = ambito_codifica_precio((c.tipo_codigo, c.subtipo_codigo) for c in criterios)
        for c in criterios:
            nuevas[c.id] = criterio_es_precio(
                c.tipo_codigo, c.subtipo_codigo, c.descripcion, ambito_codifica_precio=codifica
            )

    raiz = [c for c in ambitos.get(None, []) if c.padre_orden is None]
    return Recalculo(
        es_precio=nuevas,
        peso_antes=peso_precio_de_criterios((c.peso, c.es_precio) for c in raiz),
        peso_despues=peso_precio_de_criterios((c.peso, nuevas[c.id]) for c in raiz),
    )


def _con_reintentos(paso: Callable[[], Lote], desde: str) -> Lote | None:
    """Ejecuta un lote reintentando si choca con locks o con el timeout.

    Un ``lock_timeout`` es lo esperado cuando el lote coincide con una ingesta
    que tiene esas licitaciones bloqueadas: se espera y se reintenta.
    Cualquier otro error se propaga.
    """
    import psycopg

    for intento in range(1, _REINTENTOS + 1):
        try:
            return paso()
        except (psycopg.errors.LockNotAvailable, psycopg.errors.QueryCanceled) as exc:
            espera = min(30.0, 2.0**intento)
            log.warning(
                "criterio_precio_lote_reintento",
                desde=desde,
                intento=intento,
                espera_s=espera,
                error=type(exc).__name__,
            )
            time.sleep(espera)
    return None


def _peso(valor: float | None) -> str:
    return "NULL" if valor is None else f"{valor:g}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lote", type=int, default=500, help="licitaciones por lote (default 500)")
    parser.add_argument(
        "--pausa", type=float, default=0.1, help="segundos entre lotes (default 0.1)"
    )
    parser.add_argument("--desde", default="", help="licitacion_id exclusivo desde el que empezar")
    parser.add_argument("--max-lotes", type=int, default=0, help="0 = hasta el final")
    parser.add_argument(
        "--verificar", action="store_true", help="no escribe: cuenta lo que cambiaría"
    )
    parser.add_argument(
        "--detalle", action="store_true", help="una línea por licitación que cambia"
    )
    args = parser.parse_args(argv)
    if args.lote <= 0:
        parser.error("--lote tiene que ser positivo")

    escribir = not args.verificar
    desde: str = args.desde
    lotes = licitaciones = cambiadas = criterios = pesos = desalineadas = 0
    inicio = time.monotonic()

    while True:
        cursor = desde

        def paso(cursor: str = cursor) -> Lote:
            return recalcular_lote(cursor, args.lote, recalcular, escribir=escribir)

        lote = _con_reintentos(paso, desde)
        if lote is None:
            print(f"ABORTADO: el lote tras {desde!r} agotó {_REINTENTOS} reintentos.")
            print(f"Reanudar con: --desde {desde!r}")
            return 2
        if lote.hasta is None:
            break
        lotes += 1
        licitaciones += lote.licitaciones
        cambiadas += len(lote.cambios)
        criterios += lote.criterios_reescritos
        pesos += lote.pesos_reescritos
        desalineadas += lote.desalineadas
        if args.detalle:
            for cambio in lote.cambios:
                peso = f"peso {_peso(cambio.peso_antes)} → {_peso(cambio.peso_despues)}"
                if cambio.peso == "desalineada":
                    peso += " (desalineada: no se toca)"
                print(f"  {cambio.licitacion_id}: {cambio.criterios} criterios · {peso}")
        desde = lote.hasta
        # La última clave va siempre a la salida: es lo que permite reanudar
        # con `--desde` si la ventana se corta.
        print(
            f"lote {lotes}: hasta {desde!r} · {lote.licitaciones} licitaciones · "
            f"{len(lote.cambios)} con cambios",
            flush=True,
        )
        if args.max_lotes and lotes >= args.max_lotes:
            print(f"Parado por --max-lotes. Reanudar con: --desde {desde!r}")
            break
        if args.pausa > 0:
            time.sleep(args.pausa)

    duracion = time.monotonic() - inicio
    verbo = "cambiarían" if args.verificar else "reescritos"
    print()
    print(
        f"{lotes} lotes · {licitaciones} licitaciones · {cambiadas} con cambios · {duracion:.0f} s"
    )
    print(f"  es_precio {verbo}: {criterios} criterios")
    print(f"  peso_precio_pct {verbo}: {pesos} licitaciones")
    print(f"  desalineadas (peso no tocado): {desalineadas}")
    log.info(
        "criterio_precio_backfill_fin",
        verificar=args.verificar,
        licitaciones=licitaciones,
        cambiadas=cambiadas,
        criterios=criterios,
        pesos=pesos,
        desalineadas=desalineadas,
    )
    if args.verificar:
        return 1 if cambiadas else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
