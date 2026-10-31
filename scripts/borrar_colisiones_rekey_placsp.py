"""Borra las filas PLACSP que impiden la re-key: colisiones y, a petición, sin órgano.

Paso «ya existen con la clave nueva» de `docs/runbooks/rekey-placsp-organo.md`.
Entre el 2026-10-27 y el 2026-10-28 los escritores de la fase B corrieron
contra la base sin migrar (incidente #577) y guardaron con
`placsp:<órgano>:<expediente>` expedientes que también existen con la clave
vieja. `v164_identidad_placsp_rekey` aborta mientras exista el destino de
alguna fila de su mapa. La fila vieja se queda (historial, datos de usuario) y
la nueva se borra: la reingesta vuelve a traer lo que tenía de más reciente.
Las que tengan pursuits, follows o watchlist **no se borran**: se listan para
decidirlas a mano. Con `--aplicar` borra además las filas de `mat_clusters`
cuya licitación ya no existe: su clave es el id y `v164` abortaba al repuntar
(run 41164414325 del 2026-10-31).

El mapa solo incluye filas viejas con `organo_ref_fuente`, así que esto se
corre **después** del relleno (`scripts/rellenar_organo_ref_placsp.py`).

`--sin-organo` añade el último paso del relleno según el runbook: las filas de
la familia que siguen sin órgano tras los ZIP y el respaldo por nombre, sin
datos de usuario, se borran (la reingesta trae con su clave las que sean
reales). El 2026-10-31 eran 21 filas de prueba de los E2E y smoke tests del
2026-05-11 (`E2E-*`, `LIC-SMOKE-*`, URLs de example.com). Mirar el plan antes
de aplicarlo: con el relleno a medias borraría filas reales.

Uso::

    python scripts/borrar_colisiones_rekey_placsp.py                          # plan
    python scripts/borrar_colisiones_rekey_placsp.py --aplicar                # borra colisiones
    python scripts/borrar_colisiones_rekey_placsp.py --sin-organo             # plan de ambas
    python scripts/borrar_colisiones_rekey_placsp.py --sin-organo --aplicar   # borra ambas

Necesita `DATABASE_URL` (escritura con `--aplicar`).
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

from db.repositories.identidad import (
    borrar_licitaciones_en_colision,
    borrar_mat_clusters_huerfanos,
    colisiones_del_rekey_placsp,
    contar_mat_clusters_huerfanos,
    filas_placsp_sin_organo_ref,
)
from observability import configure_logging


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Borra las filas con la clave nueva que v164 encontraría ya ocupadas"
    )
    p.add_argument("--aplicar", action="store_true", help="Borrar (sin él solo cuenta)")
    p.add_argument(
        "--sin-organo",
        action="store_true",
        help="Incluir las filas de la familia que siguen sin organo_ref_fuente",
    )
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

    if args.sin_organo:
        sin_organo = filas_placsp_sin_organo_ref()
        print(f"Filas de la familia sin organo_ref_fuente : {len(sin_organo)}")
        for f in sin_organo:
            print(
                f"  {f['id_externo']}  [{f['fuente']}] {f['organo_contratacion'] or '-'}  {f['url'] or '-'}"
            )
        borrables += [f["id_externo"] for f in sin_organo]

    print(f"mat_clusters huérfanos (se borran)        : {contar_mat_clusters_huerfanos()}")
    if not args.aplicar:
        print(f"A borrar (sin datos de usuario)           : hasta {len(borrables)}")
        print("\n(plan: no se ha borrado nada; repetir con --aplicar)")
        return 0
    borradas = borrar_licitaciones_en_colision(borrables)
    print(f"Borradas                                  : {borradas}")
    print(f"mat_clusters huérfanos borrados           : {borrar_mat_clusters_huerfanos()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
