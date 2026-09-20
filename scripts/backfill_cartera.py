"""Lleva a la cartera (F4.3) las oportunidades que ya estaban ganadas.

``contratos_cartera`` existe desde ``v106`` y hasta el escritor de 2026-09-19
nada la rellenaba: cerrar una oportunidad como ``won`` no dejaba rastro en la
cartera. El escritor nuevo cubre los cierres de ahora en adelante; este script
cubre los de antes.

Idempotente: es la misma ``services.cartera.sincronizar_cartera`` que corre el
paso diario ``cartera_avisos``, así que ejecutarlo dos veces seguidas no
escribe nada la segunda. Una fecha corregida a mano (``fecha_fin_origen =
'manual'``) no se pisa.

Uso::

    python scripts/backfill_cartera.py            # dry-run: cuenta, no escribe
    python scripts/backfill_cartera.py --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from observability.logging import get_logger  # noqa: E402
from services.cartera import ResumenSincronizacion, sincronizar_cartera  # noqa: E402

log = get_logger(__name__)


def imprimir(resumen: ResumenSincronizacion) -> None:
    print(f"\n{'DRY-RUN' if resumen.dry_run else 'APLICADO'} — cartera de contratos")
    print(f"  oportunidades ganadas:     {resumen.ganadas:>6,}")
    print(f"  contratos nuevos:          {resumen.nuevos:>6,}")
    print(f"  contratos actualizados:    {resumen.actualizados:>6,}")
    print(f"  sin cambios:               {resumen.sin_cambios:>6,}")
    print(f"  con fecha manual (no se pisa): {resumen.manuales:>2,}")
    print(f"  sin fecha de fin:          {resumen.sin_fecha:>6,}  (entran sin aviso)")
    if resumen.dry_run:
        print("\nEjecutá con --apply para escribir.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Escribe en contratos_cartera")
    args = parser.parse_args(argv)

    resumen = sincronizar_cartera(dry_run=not args.apply)
    imprimir(resumen)
    log.info("backfill_cartera_done", **resumen.model_dump())
    return 0


if __name__ == "__main__":
    sys.exit(main())
