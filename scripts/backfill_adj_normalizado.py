"""Backfill de ``adjudicaciones.nombre_normalizado``/``nif_normalizado`` (``v191``).

Rellena por lotes de ``id`` las filas con nombre y sin identidad normalizada,
con la misma ``shared.normalization`` que usa el upsert. Idempotente y
reanudable: solo toca filas con ``nombre_normalizado IS NULL``, y ``--desde``
retoma tras el último ``id`` impreso. Una transacción por lote.

Hasta que termine, el healthcheck normaliza en Python las filas que falten,
así que su recuento de la cobertura de empresas no cambia durante el relleno.

Uso::

    python -m scripts.backfill_adj_normalizado              # rellena
    python -m scripts.backfill_adj_normalizado --lote 2000 --desde 81234

El SQL vive en ``db/empresas.py`` (ADR-022): este script solo orquesta.
"""

from __future__ import annotations

import argparse

from db.empresas import normalizar_lote
from observability.logging import get_logger

log = get_logger(__name__)


def rellenar(*, desde: int = 0, lote: int = 2000) -> int:
    """Rellena lote a lote y devuelve cuántas filas escribió."""
    total = 0
    while True:
        escritas, ultimo = normalizar_lote(desde_id=desde, lote=lote)
        if ultimo is None:
            return total
        total += escritas
        desde = ultimo
        log.info("adj_normalizado_lote", hasta_id=desde, filas=escritas, total=total)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Backfill de la identidad normalizada (v191)")
    p.add_argument("--desde", type=int, default=0, help="Empieza tras este id")
    p.add_argument("--lote", type=int, default=2000)
    args = p.parse_args(argv)
    print(f"Filas normalizadas: {rellenar(desde=args.desde, lote=args.lote)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
