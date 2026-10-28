"""Rellena `licitaciones.organo_ref_fuente` del histórico PLACSP desde los ZIP mensuales.

Fase 2 del RFC `docs/rfc/2026-10-24-rfc-identidad-placsp-organo-expediente.md`
y paso previo de la ventana de re-key (`docs/runbooks/rekey-placsp-organo.md`).
La lógica —qué meses lee, cómo cruza por `idEvl`, qué es un conflicto— está en
`scraper/relleno_organo_placsp.py`; esto es la línea de comandos.

Uso::

    python scripts/rellenar_organo_ref_placsp.py                  # plan: cuenta, no escribe
    python scripts/rellenar_organo_ref_placsp.py --solo-meses     # qué ZIP leería, sin descargar
    python scripts/rellenar_organo_ref_placsp.py --aplicar        # escribe, mes a mes
    python scripts/rellenar_organo_ref_placsp.py --desde 2025-01 --hasta 2026-10 --aplicar
    python scripts/rellenar_organo_ref_placsp.py --respaldo-por-nombre --aplicar

Idempotente (solo escribe filas con la columna vacía) y reanudable (escribe al
terminar cada mes; la siguiente ejecución recalcula los meses desde lo que
siga pendiente). La puerta de la re-key la mide
`python scripts/inventario_pisadas_placsp.py`: «filas PLACSP sin
organo_ref_fuente» tiene que decir «ninguna».

Necesita `DATABASE_URL` (escritura con `--aplicar`) y red para los ZIP.
"""

from __future__ import annotations

import argparse
import sys

from observability import configure_logging
from scraper.relleno_organo_placsp import meses_entre, rellenar


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Rellena organo_ref_fuente del histórico PLACSP desde los ZIP mensuales"
    )
    p.add_argument("--aplicar", action="store_true", help="Escribir (sin él solo cuenta)")
    p.add_argument("--desde", help="Primer mes, YYYY-MM (con --hasta, fuerza el rango)")
    p.add_argument("--hasta", help="Último mes, YYYY-MM (incluido)")
    p.add_argument(
        "--respaldo-por-nombre",
        action="store_true",
        help="Al final, deducir el órgano del nombre cuando las demás filas son unánimes",
    )
    p.add_argument("--conservar-zip", action="store_true", help="No borrar los ZIP leídos")
    p.add_argument(
        "--solo-meses", action="store_true", help="Lista los meses a leer y sale sin descargar"
    )
    args = p.parse_args(argv)
    if bool(args.desde) != bool(args.hasta):
        p.error("--desde y --hasta van juntos")
    configure_logging()
    resumen = rellenar(
        aplicar=args.aplicar,
        meses=meses_entre(args.desde, args.hasta) if args.desde else None,
        respaldo_por_nombre=args.respaldo_por_nombre,
        conservar_zip=args.conservar_zip,
        solo_meses=args.solo_meses,
    )
    meses = ", ".join(f"{y}-{m:02d}" for y, m in resumen.meses[:6])
    print(f"Filas de la familia sin organo_ref_fuente : {resumen.pendientes}")
    print(
        f"Meses a leer                              : {len(resumen.meses)} "
        f"({meses}{'…' if len(resumen.meses) > 6 else ''})"
    )
    if args.solo_meses:
        return 0
    print(f"Resueltas por idEvl                       : {resumen.por_evl}")
    print(f"Resueltas por expediente + órgano         : {resumen.por_expediente}")
    print(f"Resueltas por nombre (opt-in)             : {resumen.por_nombre}")
    print(f"Esquema del órgano usado (idEvl)          : {resumen.por_esquema}")
    print(f"Conflictos (dos órganos para una fila)    : {resumen.conflictos}")
    print(f"Entradas cruzadas sin órgano              : {resumen.entradas_sin_organo}")
    print(f"Sin resolver                              : {resumen.sin_resolver}")
    print(f"Escritas                                  : {resumen.escritas}")
    if not args.aplicar:
        print("\n(plan: no se ha escrito nada; repetir con --aplicar)")
    print("Puerta de la re-key: python scripts/inventario_pisadas_placsp.py → «ninguna».")
    return 0


if __name__ == "__main__":
    sys.exit(main())
