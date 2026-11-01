"""Limpia las hijas que una pisada dejó en la fila superviviente, tras la reingesta.

Pasos 1 y 2 de §«Las filas ya pisadas» del RFC
`docs/rfc/2026-10-24-rfc-identidad-placsp-organo-expediente.md` (paso 5 de
`docs/runbooks/reingesta-unica-placsp.md`). Toma las pisadas seguras del
inventario (`sim_organo` y `sim_titulo` por debajo del umbral; los renombres
probables no se tocan) y, sobre esas filas:

- cuenta, y con `--aplicar` borra, las adjudicaciones, lotes y condiciones que
  la reingesta no reescribió y los documentos que también cuelgan de la fila
  hermana del otro órgano (`db.repositories.identidad.limpiar_hijas_pisadas`);
- lista los pursuits y follows sobre ellas con sus filas hermanas: se mueven a
  mano, nunca solos.

`--desde` es el inicio de la reingesta (ISO UTC): lo escrito antes en una fila
que la reingesta reescribió es lo que ninguna versión de los ZIP volvió a traer.

Uso::

    python scripts/limpiar_hijas_pisadas_placsp.py --desde 2026-10-31T15:37:00            # plan
    python scripts/limpiar_hijas_pisadas_placsp.py --desde 2026-10-31T15:37:00 --aplicar  # borra

Necesita `DATABASE_URL` (escritura con `--aplicar`).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from db.repositories.identidad import (
    UMBRAL_SIMILITUD,
    datos_de_usuario_en,
    inventario_pisadas_placsp,
    limpiar_hijas_pisadas,
)
from observability import configure_logging


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Limpia las hijas de las filas PLACSP pisadas")
    p.add_argument("--desde", required=True, help="Inicio de la reingesta, ISO UTC")
    p.add_argument("--umbral", type=float, default=UMBRAL_SIMILITUD)
    p.add_argument("--aplicar", action="store_true", help="Borrar (sin él solo cuenta)")
    args = p.parse_args(argv)
    datetime.fromisoformat(args.desde)  # falla aquí, no comparando texto mal formado
    configure_logging()

    ids = sorted(
        {
            par["id_externo"]
            for par in inventario_pisadas_placsp()
            if float(par["sim_organo"] or 0.0) < args.umbral
            and float(par["sim_titulo"] or 0.0) < args.umbral
        }
    )
    print(f"Filas con pisada segura                   : {len(ids)}")

    filas = limpiar_hijas_pisadas(ids, reingesta_desde=args.desde, aplicar=args.aplicar)
    verbo = "Borradas" if args.aplicar else "A borrar"
    for tabla, n in filas.items():
        print(f"{verbo} en {tabla:<35}: {n}")

    datos = datos_de_usuario_en(ids)
    print(f"Datos de usuario (se mueven a mano)       : {len(datos)}")
    for d in datos:
        hermanas = ", ".join(d["hermanas"]) or "ninguna"
        print(f"  {d['tabla']}: {d['id_externo']} (creado {d['creado']}) → hermanas: {hermanas}")

    if not args.aplicar:
        print("\n(plan: no se ha borrado nada; repetir con --aplicar)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
