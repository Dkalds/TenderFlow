"""Inventario de las licitaciones de PLACSP que otro órgano pisó (solo lectura).

Fase A del RFC `docs/rfc/2026-10-24-rfc-identidad-placsp-organo-expediente.md`.
El `id_externo` de las filas `placsp`/`bulk_*` es el `ContractFolderID` sin
órgano, y dos órganos con el mismo número de expediente se pisan por
`ON CONFLICT(id_externo)`. La fila actual es la última que llegó; la anterior
solo deja rastro en `licitaciones_history`, que guarda un snapshot con el
órgano y el título de cada versión que cambió algo.

Qué cuenta
----------
Para cada `id_externo` de PLACSP, los órganos que aparecen en algún snapshot y
no son el de la fila actual (`db.repositories.identidad.inventario_pisadas_placsp`,
la consulta de detección del RFC), con la similitud de órgano y título frente a
la fila actual:

- `sim_organo < 0,5 AND sim_titulo < 0,5` → **pisada segura**: otra licitación.
- el resto → **dudoso o renombre** del mismo órgano; va a revisión y no se
  toca solo.

Es una **cota inferior**: el historial empieza el 2026-05-22 y solo escribe
snapshot cuando cambia un campo de `HISTORY_TRACKED_FIELDS` (que no incluye el
órgano; en la práctica cambia la `descripcion`, que en PLACSP lleva el órgano).
Medido el 2026-10-24 en producción: 456 ids / 661 pares, de los que 379 ids /
570 pares son pisada segura.

Además imprime las dos cifras que la fase B necesita: cuántas filas de la familia
siguen sin `organo_ref_fuente` (la puerta 1 del RFC: la re-key no empieza
mientras quede alguna; las rellena `scripts/rellenar_organo_ref_placsp.py`, y
`v164_identidad_placsp_rekey` aborta si queda una) y cuántos expedientes con la clave nueva conviven ya
con más de una fila (0 hasta que la fase B escriba esa clave; después, la
medida directa de lo recuperado).

Las filas pisadas **no se reconstruyen de aquí**: el snapshot no tiene CPV, URL
ni hijas. Las recupera la reingesta con la clave nueva (fase 4 del RFC); este
inventario es lo que se compara antes y después.

Uso::

    python scripts/inventario_pisadas_placsp.py              # resumen
    python scripts/inventario_pisadas_placsp.py --csv out.csv  # además, el detalle por par
    python scripts/inventario_pisadas_placsp.py --umbral 0.6

Solo lee (`connect_read`, pool de solo lectura). Necesita `DATABASE_URL`.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

from db.repositories.identidad import (
    UMBRAL_SIMILITUD,
    contar_expedientes_que_conviven,
    contar_placsp_sin_organo_ref,
    inventario_pisadas_placsp,
    resumen_pisadas_placsp,
)

_COLUMNAS_CSV = (
    "id_externo",
    "organo_actual",
    "organo_ref_fuente_actual",
    "organo_perdido",
    "primera",
    "ultima",
    "snapshots",
    "carriles",
    "sim_organo",
    "sim_titulo",
    "clase",
)


def _clase(par: dict[str, Any], umbral: float) -> str:
    seguro = float(par["sim_organo"] or 0.0) < umbral and float(par["sim_titulo"] or 0.0) < umbral
    return "pisada_segura" if seguro else "dudoso_o_renombre"


def _escribir_csv(pares: list[dict[str, Any]], destino: Path, umbral: float) -> None:
    with destino.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=_COLUMNAS_CSV)
        w.writeheader()
        for par in pares:
            fila = {k: par.get(k) for k in _COLUMNAS_CSV if k != "clase"}
            fila["carriles"] = ";".join(str(c) for c in (par.get("carriles") or []))
            fila["clase"] = _clase(par, umbral)
            w.writerow(fila)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inventario de pisadas de PLACSP (solo lectura)")
    parser.add_argument(
        "--umbral",
        type=float,
        default=UMBRAL_SIMILITUD,
        help="similarity (pg_trgm) por debajo del cual órgano y título se consideran distintos",
    )
    parser.add_argument("--csv", type=Path, default=None, help="Escribe el detalle por par")
    parser.add_argument("--ejemplos", type=int, default=10, help="Pisadas seguras que se enseñan")
    args = parser.parse_args(argv)

    pares = inventario_pisadas_placsp()
    resumen = resumen_pisadas_placsp(pares, umbral=args.umbral)
    sin_organo = contar_placsp_sin_organo_ref()
    conviven = contar_expedientes_que_conviven()

    print("PISADAS DETECTADAS EN licitaciones_history (cota inferior)")
    print(f"  id_externo con otro órgano en su historial : {resumen.ids_afectados}")
    print(f"  pares (id_externo, órgano perdido)         : {resumen.pares}")
    print(
        f"  … pisada segura (sim < {args.umbral:.2f} en órgano y título): {resumen.pares_seguros}"
    )
    print(f"  … dudoso o renombre (a revisión)           : {resumen.pares_dudosos}")
    print()
    print("PUERTA 1 DE LA FASE B: filas PLACSP sin organo_ref_fuente, por fuente")
    if sin_organo:
        for fuente, n in sin_organo.items():
            print(f"  {fuente:<34} {n}")
    else:
        print("  ninguna")
    print()
    print(f"EXPEDIENTES CON CLAVE NUEVA QUE CONVIVEN (antes se pisaban): {conviven}")

    seguras = [p for p in pares if _clase(p, args.umbral) == "pisada_segura"]
    if seguras and args.ejemplos:
        print()
        print(f"EJEMPLOS DE PISADA SEGURA (primeros {min(args.ejemplos, len(seguras))})")
        for par in seguras[: args.ejemplos]:
            print(
                f"  {par['id_externo']!r}: ahora {par['organo_actual']!r}; "
                f"perdido {par['organo_perdido']!r} "
                f"({par['primera'][:10]}..{par['ultima'][:10]}, "
                f"carriles {','.join(str(c) for c in par['carriles'] or [])})"
            )

    if args.csv is not None:
        _escribir_csv(pares, args.csv, args.umbral)
        print(f"\nDetalle escrito en {args.csv} ({len(pares)} pares)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
