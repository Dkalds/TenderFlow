"""Parte las adjudicaciones de PSCP con varios adjudicatarios y limpia el maestro.

Hasta el 2026-11-06 el conector de PSCP guardaba como un solo adjudicatario la
fila que publica varios, con nombres y NIFs unidos por ``||``, y la resolución
de entidades creaba con ella una empresa ficticia («A SL||B SA», NIF
«B1||B2»). Medido en producción ese día: 101 adjudicaciones compuestas y 1.821
empresas compuestas, 1.720 de ellas ya sin ninguna adjudicación. El parser ya
reparte por posición (``scraper.connectors.pscp.adjudicatarios_de_la_fila``);
esto arregla lo guardado antes.

Qué hace (``db.empresas.limpiar_adjudicatarios_compuestos``, una transacción):

1. Cada adjudicación compuesta pasa a una fila por empresa, con su NIF si
   tiene tantas posiciones como nombres. El importe no se reparte: el
   guardado es único para varias empresas.
2. Borra las empresas compuestas que ya no usa nada; sus alias, miembros de
   UTE y candidaturas de revisión caen en cascada.

Después enlaza las filas nuevas con sus empresas reales por NIF
(``services.entity_resolution.resolve_all_unlinked`` acotado a PSCP).

Los importes por empresa no se recuperan aquí: no están en la base. Los trae
la reingesta (``python -m scraper.connectors.pscp --desde AAAA-MM-DD``).

Uso::

    python -m scripts.partir_adjudicatarios_pscp            # cuenta, no escribe
    python -m scripts.partir_adjudicatarios_pscp --apply    # parte, borra y enlaza

Es idempotente: una segunda pasada no encuentra nada que partir.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from db.empresas import limpiar_adjudicatarios_compuestos  # noqa: E402
from scraper.connectors.pscp import SOURCE_ID  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--apply", action="store_true", help="Escribe (sin él, solo cuenta)")
    args = parser.parse_args(argv)

    recuento = limpiar_adjudicatarios_compuestos(aplicar=args.apply)
    verbo = "Partidas" if args.apply else "Se partirían"
    print(
        f"{verbo} {recuento.adjudicaciones_compuestas} adjudicaciones compuestas en "
        f"{recuento.adjudicaciones_nuevas} filas; empresas compuestas "
        f"{'borradas' if args.apply else 'a borrar'}: {recuento.empresas_borradas}."
    )
    if not args.apply:
        print("Nada se ha escrito. Repetí con --apply para aplicarlo.")
        return 0

    from services.entity_resolution import resolve_all_unlinked

    stats = resolve_all_unlinked(fuente=SOURCE_ID, scope_fuente=SOURCE_ID)
    print(f"Resolución de entidades (pscp): {stats.as_dict()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
