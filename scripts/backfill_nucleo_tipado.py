"""Backfill por lotes de las columnas sombra del núcleo tipado (T2, ``v133``).

Rellena ``fecha_publicacion_ts``, ``fecha_limite_ts``, ``importe_num`` y
``duracion_valor_num`` a partir de sus columnas viejas, recorriendo
``licitaciones`` por ``id_externo`` en lotes de una transacción cada uno. Es
idempotente y reanudable: sólo reescribe las filas cuya sombra **diverge** de
su columna vieja, y ``--desde`` retoma desde la última clave impresa.

Se corre en la ventana que describe ``docs/runbooks/nucleo-tipado-ventana.md``,
**después** de desplegar el código con la escritura dual (si no, las filas que
la ingesta toque durante el backfill quedan con la sombra desfasada; la
verificación las encontraría y un segundo pase las arreglaría, pero es trabajo
tirado) y **antes** de ``v134`` (los índices).

Uso::

    python -m scripts.backfill_nucleo_tipado --verificar          # sólo cuenta
    python -m scripts.backfill_nucleo_tipado                      # rellena
    python -m scripts.backfill_nucleo_tipado --lote 2000 --pausa 0.2
    python -m scripts.backfill_nucleo_tipado --desde 'placsp:12345' --max-lotes 50

Salida 0 si terminó (y, con ``--verificar``, si no hay divergencias); 1 si la
verificación encontró divergencias; 2 si un lote agotó los reintentos.

El SQL vive en ``db/nucleo_tipado.py`` (ADR-022): este script sólo orquesta.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable

from db.nucleo_tipado import DETALLE_VERIFICACION, Lote, rellenar_lote, verificar_lote
from observability.logging import get_logger

log = get_logger(__name__)

_REINTENTOS = 5


def _con_reintentos(paso: Callable[[], Lote], desde: str) -> Lote | None:
    """Ejecuta un lote reintentando si choca con locks o con el timeout.

    Un ``lock_timeout`` es el comportamiento esperado cuando el lote coincide
    con una ingesta que tiene esas filas bloqueadas: se espera y se reintenta,
    no se aborta la ventana. Cualquier otro error se propaga.
    """
    import psycopg

    for intento in range(1, _REINTENTOS + 1):
        try:
            return paso()
        except (psycopg.errors.LockNotAvailable, psycopg.errors.QueryCanceled) as exc:
            espera = min(30.0, 2.0**intento)
            log.warning(
                "nucleo_tipado_lote_reintento",
                desde=desde,
                intento=intento,
                espera_s=espera,
                error=type(exc).__name__,
            )
            time.sleep(espera)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lote", type=int, default=5000, help="filas por lote (default 5000)")
    parser.add_argument(
        "--pausa", type=float, default=0.1, help="segundos entre lotes (default 0.1)"
    )
    parser.add_argument("--desde", default="", help="id_externo exclusivo desde el que empezar")
    parser.add_argument("--max-lotes", type=int, default=0, help="0 = hasta el final")
    parser.add_argument(
        "--verificar", action="store_true", help="no escribe: cuenta divergencias por sombra"
    )
    args = parser.parse_args(argv)
    if args.lote <= 0:
        parser.error("--lote tiene que ser positivo")

    desde: str = args.desde
    lotes = filas = afectadas = 0
    detalle = dict.fromkeys(DETALLE_VERIFICACION, 0)
    inicio = time.monotonic()

    while True:
        cursor = desde

        def paso(cursor: str = cursor) -> Lote:
            if args.verificar:
                return verificar_lote(cursor, args.lote)
            return rellenar_lote(cursor, args.lote)

        lote = _con_reintentos(paso, desde)
        if lote is None:
            print(f"ABORTADO: el lote tras {desde!r} agotó {_REINTENTOS} reintentos.")
            print(f"Reanudar con: --desde {desde!r}")
            return 2
        if lote.hasta is None:
            break
        lotes += 1
        filas += lote.filas
        afectadas += lote.afectadas
        for clave, valor in lote.detalle.items():
            detalle[clave] += valor
        desde = lote.hasta
        # La última clave va siempre a la salida: es lo que permite reanudar
        # con `--desde` si la ventana se corta.
        print(
            f"lote {lotes}: hasta {desde!r} · {lote.filas} filas · "
            f"{lote.afectadas} {'divergentes' if args.verificar else 'reescritas'}",
            flush=True,
        )
        if args.max_lotes and lotes >= args.max_lotes:
            print(f"Parado por --max-lotes. Reanudar con: --desde {desde!r}")
            break
        if args.pausa > 0:
            time.sleep(args.pausa)

    duracion = time.monotonic() - inicio
    verbo = "divergentes" if args.verificar else "reescritas"
    print()
    print(f"{lotes} lotes · {filas} filas · {afectadas} {verbo} · {duracion:.0f} s")
    if args.verificar:
        for clave in DETALLE_VERIFICACION:
            print(f"  {clave}: {detalle[clave]}")
        return 1 if afectadas else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
