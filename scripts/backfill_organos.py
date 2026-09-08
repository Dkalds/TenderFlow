"""Construye el maestro de órganos y resuelve `licitaciones.organo_id` (C1.2).

`v114` crea el maestro vacío y `v115` abre la columna. Este script las llena.

**No es un `UPDATE`, es un proceso con criterio.** Resolver 706.000 filas de
texto libre contra un maestro que arranca vacío significa construir el maestro:
normalizar cada grafía, agrupar, elegir la canónica y **encolar las dudosas**
en vez de decidirlas. Por eso vive aquí y no dentro de una migración: una
migración que tarda una hora bloquea el despliegue, no se puede reanudar si
falla a mitad, y no da ocasión de mirar el delta antes de que la analítica
empiece a agrupar por el resultado.

Orden de trabajo
----------------
Las grafías se procesan **por volumen descendente**: resolver primero las que
más expedientes arrastran hace que la cobertura suba rápido y que el delta sea
visible desde el primer lote, en vez de tener que esperar al final para saber si
funcionó.

Uso::

    python scripts/backfill_organos.py                    # dry-run con el plan
    python scripts/backfill_organos.py --apply
    python scripts/backfill_organos.py --apply --grafias 500 --batch 2000

Tras aplicarlo, la cobertura se mide con ``--cobertura`` y el delta de
``make audit-truth-check`` se anota en la PR.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from db.repositories import organos as repo  # noqa: E402
from observability.logging import get_logger  # noqa: E402
from services.organos import resolver  # noqa: E402

log = get_logger(__name__)

#: Fuente cuya cobertura fija el criterio de aceptación de C1.2 (≥ 95 % de los
#: expedientes de los últimos doce meses).
FUENTE_OBJETIVO = "placsp"
MESES_OBJETIVO = 12


def _hace_doce_meses() -> str:
    return (datetime.now(UTC) - timedelta(days=365 * MESES_OBJETIVO // 12)).date().isoformat()


def imprimir_cobertura(titulo: str) -> dict[str, int]:
    desde = _hace_doce_meses()
    total = repo.cobertura()
    objetivo = repo.cobertura(fuente=FUENTE_OBJETIVO, desde=desde)
    pct_total = 100.0 * total["resueltos"] / total["total"] if total["total"] else 0.0
    pct_obj = 100.0 * objetivo["resueltos"] / objetivo["total"] if objetivo["total"] else 0.0

    print(f"\n{titulo}")
    print(
        f"  todo el corpus:            {total['resueltos']:>8,} / {total['total']:<8,} "
        f"({pct_total:5.1f} %)"
    )
    print(
        f"  {FUENTE_OBJETIVO} últimos 12 meses:  {objetivo['resueltos']:>8,} / "
        f"{objetivo['total']:<8,} ({pct_obj:5.1f} %)   objetivo ≥ 95 %"
    )
    return {"pct_total": int(pct_total), "pct_objetivo": int(pct_obj)}


def procesar(*, max_grafias: int, batch: int, aplicar: bool) -> dict[str, int]:
    """Resuelve las grafías pendientes. Devuelve el recuento por vía."""
    grafias = repo.grafias_sin_resolver(limit=max_grafias)
    conteo = {"dir3": 0, "nombre": 0, "nuevo": 0, "revision": 0, "sin_nombre": 0}
    asignadas = 0

    for fila in grafias:
        nombre = str(fila.get("nombre") or "")
        # `crear_si_falta=aplicar`: en dry-run se cuenta lo que pasaría sin
        # escribir nada en el maestro.
        resolucion = resolver(
            nombre,
            ccaa=fila.get("ccaa"),
            crear_si_falta=aplicar,
        )
        if resolucion is None:
            conteo["sin_nombre"] += 1
            continue
        conteo[resolucion.via] = conteo.get(resolucion.via, 0) + 1

        if not aplicar or resolucion.organo_id is None:
            continue
        # La asignación va por lotes sobre la grafía cruda, que es como está en
        # la tabla: `lower(btrim(...))` es el mismo predicado que usa la consulta
        # que las descubrió.
        plano = str(fila.get("nombre_plano") or "")
        while True:
            n = repo.asignar_a_licitaciones(
                resolucion.organo_id, nombre_normalizado=plano, limit=batch
            )
            if n <= 0:
                break
            asignadas += n

    conteo["expedientes_asignados"] = asignadas
    return conteo


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Escribe el maestro y asigna")
    parser.add_argument(
        "--grafias",
        type=int,
        default=1_000,
        help="Grafías distintas a procesar en esta pasada (default 1000)",
    )
    parser.add_argument(
        "--batch", type=int, default=2_000, help="Filas por lote al asignar (default 2000)"
    )
    parser.add_argument("--cobertura", action="store_true", help="Solo mide la cobertura y sale")
    args = parser.parse_args()

    if args.cobertura:
        imprimir_cobertura("COBERTURA")
        return 0

    imprimir_cobertura("ANTES")
    conteo = procesar(max_grafias=args.grafias, batch=args.batch, aplicar=args.apply)

    print(f"\n{'APLICADO' if args.apply else 'DRY-RUN'} — resolución de grafías")
    print(f"  por DIR3:              {conteo['dir3']:>6,}")
    print(f"  por nombre existente:  {conteo['nombre']:>6,}")
    print(f"  órganos nuevos:        {conteo['nuevo']:>6,}")
    print(f"  a revisión humana:     {conteo['revision']:>6,}")
    print(f"  sin nombre utilizable: {conteo['sin_nombre']:>6,}")
    if args.apply:
        print(f"  expedientes asignados: {conteo['expedientes_asignados']:>6,}")
        imprimir_cobertura("DESPUÉS")
        pendientes = len(repo.listar_pendientes(limit=1_000))
        print(
            f"\n{pendientes} fusión/es esperando decisión humana. Revisalas antes de "
            "dar la cobertura por buena: una fusión errónea junta dos historiales "
            "de contratación y no se ve mirando la ficha."
        )
    else:
        print("\nEjecutá con --apply para escribir el maestro.")

    log.info("backfill_organos_done", aplicar=args.apply, **conteo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
