"""Backfill por lotes de las sombras ``<columna>_ts`` de ``v159``.

Rellena cada sombra a partir de su columna de texto, recorriendo la tabla por
su clave primaria en lotes de una transacción cada uno. Idempotente y
reanudable: solo reescribe las filas cuya sombra **diverge** del texto, y
``--desde`` retoma desde la última clave impresa.

Se corre en la ventana de ``docs/runbooks/fechas-ts-ventana.md``: **después**
de ``v159`` y del despliegue con la escritura dual de ``licitaciones`` (los
triggers de las demás tablas nacen con la migración), y **antes** de ``v160``
(el índice).

Uso::

    python -m scripts.backfill_fechas_ts --verificar                 # todas, solo cuenta
    python -m scripts.backfill_fechas_ts                             # rellena todas
    python -m scripts.backfill_fechas_ts --tabla licitaciones --lote 2000 --pausa 0.2
    python -m scripts.backfill_fechas_ts --tabla documentos --desde 41234

Salida 0 si terminó (y, con ``--verificar``, sin divergencias); 1 si la
verificación encontró divergencias; 2 si un lote agotó los reintentos.

El SQL vive en ``db/fechas_ts.py`` (ADR-022): este script solo orquesta.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable

from db.fechas_ts import (
    TABLAS,
    Lote,
    TablaFechas,
    cursor_de_texto,
    detalle_verificacion,
    rellenar_lote,
    tabla,
    verificar_lote,
)
from observability.logging import get_logger

log = get_logger(__name__)

_REINTENTOS = 5


def _con_reintentos(paso: Callable[[], Lote], desde: str | int) -> Lote | None:
    """Ejecuta un lote reintentando si choca con locks o con el timeout."""
    import psycopg

    for intento in range(1, _REINTENTOS + 1):
        try:
            return paso()
        except (psycopg.errors.LockNotAvailable, psycopg.errors.QueryCanceled) as exc:
            espera = min(30.0, 2.0**intento)
            log.warning(
                "fechas_ts_lote_reintento",
                desde=str(desde),
                intento=intento,
                espera_s=espera,
                error=type(exc).__name__,
            )
            time.sleep(espera)
    return None


def _recorrer(
    t: TablaFechas, desde_texto: str, *, tamano: int, pausa: float, max_lotes: int, verificar: bool
) -> int:
    """Recorre una tabla. Devuelve el código de salida parcial (0, 1 o 2)."""
    desde = cursor_de_texto(t, desde_texto)
    lotes = filas = afectadas = 0
    claves = detalle_verificacion(t)
    detalle = dict.fromkeys(claves, 0)
    inicio = time.monotonic()
    verbo = "divergentes" if verificar else "reescritas"
    print(f"== {t.nombre}")

    while True:
        cursor = desde

        def paso(cursor: str | int = cursor) -> Lote:
            if verificar:
                return verificar_lote(t.nombre, cursor, tamano)
            return rellenar_lote(t.nombre, cursor, tamano)

        lote = _con_reintentos(paso, desde)
        if lote is None:
            print(f"ABORTADO: el lote tras {desde!r} agotó {_REINTENTOS} reintentos.")
            print(f"Reanudar con: --tabla {t.nombre} --desde {desde!r}")
            return 2
        if lote.hasta is None:
            break
        lotes += 1
        filas += lote.filas
        afectadas += lote.afectadas
        for clave, valor in lote.detalle.items():
            detalle[clave] += valor
        desde = lote.hasta
        # La última clave va siempre a la salida: permite reanudar con --desde.
        print(
            f"lote {lotes}: hasta {desde!r} · {lote.filas} filas · {lote.afectadas} {verbo}",
            flush=True,
        )
        if max_lotes and lotes >= max_lotes:
            print(f"Parado por --max-lotes. Reanudar con: --tabla {t.nombre} --desde {desde!r}")
            break
        if pausa > 0:
            time.sleep(pausa)

    duracion = time.monotonic() - inicio
    print(f"{t.nombre}: {lotes} lotes · {filas} filas · {afectadas} {verbo} · {duracion:.0f} s")
    if verificar:
        for clave in claves:
            print(f"  {clave}: {detalle[clave]}")
        return 1 if afectadas else 0
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--tabla",
        choices=[t.nombre for t in TABLAS],
        help="una sola tabla (default: todas las que admiten backfill)",
    )
    parser.add_argument("--lote", type=int, default=5000, help="filas por lote (default 5000)")
    parser.add_argument("--pausa", type=float, default=0.1, help="segundos entre lotes")
    parser.add_argument("--desde", default="", help="clave exclusiva desde la que empezar")
    parser.add_argument("--max-lotes", type=int, default=0, help="0 = hasta el final")
    parser.add_argument(
        "--verificar", action="store_true", help="no escribe: cuenta divergencias por sombra"
    )
    args = parser.parse_args(argv)
    if args.lote <= 0:
        parser.error("--lote tiene que ser positivo")
    if args.desde and not args.tabla:
        parser.error("--desde exige --tabla: cada tabla tiene su propia clave")

    if args.tabla:
        elegidas = [tabla(args.tabla)]
        if not elegidas[0].backfill and not args.verificar:
            parser.error(f"{args.tabla} no admite backfill (la rellena v159); usá --verificar")
    else:
        elegidas = [t for t in TABLAS if t.backfill or args.verificar]

    salida = 0
    for t in elegidas:
        parcial = _recorrer(
            t,
            args.desde,
            tamano=args.lote,
            pausa=args.pausa,
            max_lotes=args.max_lotes,
            verificar=args.verificar,
        )
        if parcial == 2:
            return 2
        salida = max(salida, parcial)
    return salida


if __name__ == "__main__":
    sys.exit(main())
