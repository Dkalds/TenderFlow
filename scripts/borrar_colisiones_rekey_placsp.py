"""Borra las filas PLACSP escritas ya con la clave nueva que chocan con la re-key.

Paso «ya existen con la clave nueva» de `docs/runbooks/rekey-placsp-organo.md`.
Entre el 2026-10-27 y el 2026-10-28 los escritores de la fase B corrieron
contra la base sin migrar (incidente #577) y guardaron con
`placsp:<órgano>:<expediente>` expedientes que también existen con la clave
vieja. `v164_identidad_placsp_rekey` aborta mientras exista el destino de
alguna fila de su mapa. La fila vieja se queda (historial, datos de usuario) y
la nueva se borra: la reingesta vuelve a traer lo que tenía de más reciente.
Las que tengan pursuits, follows o watchlist **no se borran**: se listan para
decidirlas a mano.

El mapa solo incluye filas viejas con `organo_ref_fuente`, así que esto se
corre **después** del relleno (`scripts/rellenar_organo_ref_placsp.py`).

Uso::

    python scripts/borrar_colisiones_rekey_placsp.py            # plan: lista y cuenta
    python scripts/borrar_colisiones_rekey_placsp.py --aplicar  # borra

Necesita `DATABASE_URL` (escritura con `--aplicar`).
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

from db.repositories.identidad import borrar_licitaciones_en_colision, colisiones_del_rekey_placsp
from observability import configure_logging


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Borra las filas con la clave nueva que v164 encontraría ya ocupadas"
    )
    p.add_argument("--aplicar", action="store_true", help="Borrar (sin él solo cuenta)")
    args = p.parse_args(argv)
    configure_logging()

    colisiones = colisiones_del_rekey_placsp()
    con_usuario = [c for c in colisiones if c["datos_de_usuario"]]
    borrables = [c["id_externo"] for c in colisiones if not c["datos_de_usuario"]]
    por_fuente = Counter(c["fuente"] for c in colisiones)

    print(f"Filas con la clave nueva que chocan       : {len(colisiones)}")
    for fuente, n in sorted(por_fuente.items()):
        print(f"  {fuente:<40}: {n}")
    print(f"Con datos de usuario (no se borran)       : {len(con_usuario)}")
    for c in con_usuario:
        print(f"  {c['id_externo']}  (vieja: {c['id_viejo']})")
    if not args.aplicar:
        print(f"A borrar                                  : {len(borrables)}")
        print("\n(plan: no se ha borrado nada; repetir con --aplicar)")
        return 0
    borradas = borrar_licitaciones_en_colision(borrables)
    print(f"Borradas                                  : {borradas}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
