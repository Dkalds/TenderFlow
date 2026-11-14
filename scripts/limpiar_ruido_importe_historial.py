"""Borra del historial las filas de «importe cambió» que solo eran ruido de float4.

Paso (1) de la limpieza del ítem «Migrar ``licitaciones.importe`` de ``real`` a
``double precision``» del backlog. Recorre por lotes de id las filas de
``licitaciones_history`` con ``changed_fields='importe'``
(``db.historial_ruido.candidatos_ruido_importe``) y da por ruido las que tienen
importe antes y después y los dos son iguales con la tolerancia con la que se
escribieron (``shared.numeric.FLOAT_REL_TOL``). Con ``--aplicar`` las borra
junto con sus eventos ``modificacion`` de ``importe`` en ``contrato_eventos``,
una transacción por lote.

El borrado es irreversible: sin ``--aplicar`` el CSV (``--csv``) es el plan, y
con él cada lote vuelca **antes** de borrarlo las filas enteras de las dos
tablas a ``<csv>.respaldo.jsonl`` (una por línea, ``{"tabla", "fila"}``), que
es lo que permite restaurarlas con un ``INSERT``. Bajar ``FLOAT_REL_TOL`` va
después de esta limpieza en producción, en otro cambio.

Uso::

    python scripts/limpiar_ruido_importe_historial.py                  # plan + CSV
    python scripts/limpiar_ruido_importe_historial.py --aplicar        # borra
    python scripts/limpiar_ruido_importe_historial.py --desde-id 12345 # retoma

Necesita ``DATABASE_URL`` (escritura con ``--aplicar``).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import UTC, datetime

from db.historial_ruido import borrar_ruido_importe, candidatos_ruido_importe, filas_a_borrar
from observability import configure_logging
from shared.numeric import FLOAT_REL_TOL, values_equal

_MUESTRA = 10


def es_ruido(antes: float | None, despues: float | None) -> bool:
    """True si el «cambio» de importe cabe en el ruido de float4.

    Sin uno de los dos valores (snapshot truncado, licitación borrada) la fila
    no se juzga. Los iguales en bits también son ruido: el snapshot siguiente
    se leyó de la misma columna float4 que el anterior.
    """
    if antes is None or despues is None:
        return False
    return values_equal(antes, despues, rel_tol=FLOAT_REL_TOL)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Limpia el ruido de float4 en el historial de importe")
    p.add_argument("--aplicar", action="store_true", help="Borrar (sin él solo cuenta)")
    p.add_argument("--desde-id", type=int, default=0, help="Empieza tras este history_id")
    p.add_argument("--lote", type=int, default=1000)
    p.add_argument(
        "--csv",
        default=f"ruido_importe_historial_{datetime.now(UTC):%Y%m%dT%H%M%S}.csv",
        help="Fichero donde se vuelca lo que se borra (o se borraría)",
    )
    args = p.parse_args(argv)
    configure_logging()
    respaldo = f"{args.csv.removesuffix('.csv')}.respaldo.jsonl"

    revisadas = ruido = eventos = borradas = 0
    desde = args.desde_id
    with open(args.csv, "w", newline="", encoding="utf-8") as f:
        salida = csv.writer(f)
        salida.writerow(["history_id", "id_externo", "antes", "despues"])
        while True:
            candidatos = candidatos_ruido_importe(desde, args.lote)
            if not candidatos:
                break
            desde = candidatos[-1]["history_id"]
            revisadas += len(candidatos)
            lote = [c for c in candidatos if es_ruido(c["antes"], c["despues"])]
            if not lote:
                continue
            for c in lote:
                salida.writerow([c["history_id"], c["id_externo"], c["antes"], c["despues"]])
                if ruido < _MUESTRA:
                    print(f"  {c['history_id']} {c['id_externo']}: {c['antes']} → {c['despues']}")
                ruido += 1
            f.flush()
            if args.aplicar:
                ids = [c["history_id"] for c in lote]
                # Filas enteras en disco antes de borrar: es lo único que deshace el borrado.
                with open(respaldo, "a", encoding="utf-8") as r:
                    for tabla, filas in filas_a_borrar(ids).items():
                        for fila in filas:
                            r.write(json.dumps({"tabla": tabla, "fila": fila}, default=str))
                            r.write("\n")
                n_eventos, n_filas = borrar_ruido_importe(ids)
                eventos += n_eventos
                borradas += n_filas

    print(f"Filas con solo importe cambiado revisadas : {revisadas}")
    print(f"De ellas, ruido de float4                 : {ruido} (volcadas a {args.csv})")
    print(f"Último history_id revisado                : {desde}")
    if args.aplicar:
        print(f"Borradas en licitaciones_history          : {borradas}")
        print(f"Borrados en contrato_eventos              : {eventos}")
        print(f"Filas enteras para restaurar              : {respaldo}")
    else:
        print("\n(plan: no se ha borrado nada; repetir con --aplicar)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
