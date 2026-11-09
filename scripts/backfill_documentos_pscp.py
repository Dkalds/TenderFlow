"""Lee la ficha de los expedientes PSCP ya cerrados que se quedaron sin documentos.

Hasta el 2026-11-09 la pasada de documentos de PSCP solo leía las convocatorias
vigentes, y la ficha de un expediente cerrado es la de su última fase, que no
trae pliegos (``scraper.documentos_plataforma``). Desde entonces cada ingesta
lee los que cambian de fase; este pase lee una vez el atraso. Medido ese día en
producción: 19.291 expedientes sin documentos, 2.351 publicados en 2026.

Por defecto solo cuenta (no pide ni escribe nada). ``--aplicar`` lee las fichas
y escribe las referencias en ``documentos`` como ``pending``: las descarga la
pasada nocturna con su orden de siempre, que pone por delante lo abierto y lo
que alguien sigue. Empieza por lo que cambió más recientemente. Es idempotente:
un expediente que ya tiene documentos deja de ser candidato, así que se puede
cortar y repetir; ``--presupuesto`` acota cada tanda.

Uso::

    python -m scripts.backfill_documentos_pscp                 # cuenta, no pide nada
    python -m scripts.backfill_documentos_pscp --aplicar
    python -m scripts.backfill_documentos_pscp --aplicar --presupuesto 7200 --pausa 0.5

Las candidatas y la escritura viven en ``db/repositories/documentos.py``
(ADR-022) y la lectura de la ficha en ``scraper/documentos_plataforma.py``:
este script solo orquesta.
"""

from __future__ import annotations

import argparse
import json

from db.repositories.documentos import DocumentosRepository
from scraper.documentos_plataforma import completar_documentos_pscp

#: El atraso entero cabe en una sola lista: así cada expediente se lee una vez
#: por tanda y los que no tienen pliegos no se repiten.
_LIMITE = 50_000


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--aplicar", action="store_true", help="lee y escribe (por defecto cuenta)")
    parser.add_argument("--presupuesto", type=float, default=3600.0, help="segundos por tanda")
    parser.add_argument("--pausa", type=float, default=0.5, help="segundos entre fichas")
    args = parser.parse_args(argv)

    candidatas = DocumentosRepository().pscp_para_documentos(limit=_LIMITE, dias_cambio=None)
    print(f"Expedientes PSCP cuya ficha toca leer: {len(candidatas)}")
    if not args.aplicar:
        print("Sin --aplicar: no se ha pedido ni escrito nada.")
        return 0

    resumen = completar_documentos_pscp(
        limite=_LIMITE, presupuesto_s=args.presupuesto, pausa_s=args.pausa, dias_cambio=None
    )
    print(json.dumps(resumen.as_dict(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
