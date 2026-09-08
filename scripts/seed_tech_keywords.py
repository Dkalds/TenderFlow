"""Siembra ``tecnologias_keywords`` con el diccionario de ``config/keywords.py`` (C5.6).

Idempotente y conservador: si la tabla ya tiene filas no toca nada. Nunca
reactiva una keyword que alguien retiró — si la semilla pudiera resucitarlas,
cada despliegue desharía las decisiones del equipo.

Uso::

    python scripts/seed_tech_keywords.py          # siembra si está vacía
    python scripts/seed_tech_keywords.py --check  # sólo informa, no escribe
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Informa sin escribir")
    args = parser.parse_args(argv)

    from db.database import init_db
    from services.tech_dictionary import huella, origen, sembrar_si_vacio, semilla, vigente

    init_db()
    if args.check:
        efectivo = vigente(refrescar=True)
        total = sum(len(v) for v in efectivo.values())
        print(f"Diccionario vigente: {len(efectivo)} tecnologías · {total} keywords")
        print(f"Origen             : {origen()}")
        print(f"Huella             : {huella(efectivo)}")
        return 0

    nuevas = sembrar_si_vacio()
    total_semilla = sum(len(v) for v in semilla().values())
    if nuevas:
        print(f"Sembradas {nuevas} keywords de {total_semilla} en la semilla.")
    else:
        print("La tabla ya tenía filas: no se tocó nada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
