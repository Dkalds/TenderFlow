"""Declara ``sin_iva`` el importe adjudicado de las filas PSCP ya guardadas (ADR-032).

El parser de PSCP marcaba ``desconocido`` la fila cuyo único importe era el
adjudicado (``import_adjudicacio_sense``, sin IVA): sobre todo las
publicaciones agregadas de contratos menores. Desde el 2026-11-07 lo declara
``sin_iva``; este pase lleva la regla a lo ya ingerido sin re-leer el dataset
entero. Medido ese día en producción: 26.929 filas canónicas corregibles de las
27.041 PSCP en ``desconocido``.

Por defecto solo cuenta (no escribe). ``--aplicar`` corrige por lotes de una
transacción; es idempotente y se puede cortar y repetir.

**Orden de despliegue.** Correrlo *después* de desplegar el parser: antes, la
pasada diaria de PSCP volvería a escribir ``desconocido`` en lo que toque.

Uso::

    python -m scripts.backfill_importe_tipo_pscp              # cuenta, no escribe
    python -m scripts.backfill_importe_tipo_pscp --aplicar
    python -m scripts.backfill_importe_tipo_pscp --aplicar --lote 1000 --pausa 0.5

El SQL vive en ``db/importe_tipo.py`` (ADR-022): este script solo orquesta.
"""

from __future__ import annotations

import argparse
import time

from db.importe_tipo import aplicar_lote, contar_candidatas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--aplicar", action="store_true", help="escribe (por defecto solo cuenta)")
    parser.add_argument("--lote", type=int, default=2000, help="filas por transacción")
    parser.add_argument("--pausa", type=float, default=0.2, help="segundos entre lotes")
    args = parser.parse_args(argv)

    por_estado = contar_candidatas()
    total = sum(por_estado.values())
    print(f"Filas PSCP corregibles: {total}")
    for estado, n in por_estado.items():
        print(f"  {estado}: {n}")
    if not args.aplicar:
        print("Sin --aplicar: no se ha escrito nada.")
        return 0

    corregidas = 0
    while n := aplicar_lote(args.lote):
        corregidas += n
        print(f"lote: {n} filas · {corregidas} en total", flush=True)
        time.sleep(args.pausa)
    print(f"Corregidas: {corregidas}. Quedan: {sum(contar_candidatas().values())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
