"""Backfill del maestro de empresas sobre las adjudicaciones históricas.

Resuelve cada adjudicación sin ``empresa_id`` contra el maestro (NIF → alias
→ fuzzy → alta) en lotes transaccionales. Idempotente: re-ejecutarlo solo
procesa lo pendiente.

Reanudable: guarda el último id procesado en ``ingestion_cursors`` (uno por
ámbito), así que un job cortado por timeout retoma donde quedó en vez de volver
a recorrer el prefijo ya visto. Con ``--restart`` se vuelve a empezar.

Uso:
    python -m scripts.backfill_empresas                    # backfill completo
    python -m scripts.backfill_empresas --dry-run          # solo cobertura actual
    python -m scripts.backfill_empresas --no-fuzzy         # sin cola de revisión fuzzy
    python -m scripts.backfill_empresas --batch 2000       # tamaño de lote
    python -m scripts.backfill_empresas --scope-fuente pscp  # solo una fuente
    python -m scripts.backfill_empresas --time-budget 3600 # corta al cabo de 1 h
    python -m scripts.backfill_empresas --restart          # ignora el cursor guardado
"""

from __future__ import annotations

import argparse
import sys
import time


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill maestro de empresas")
    parser.add_argument("--batch", type=int, default=5000, help="Tamaño de lote (default 5000)")
    parser.add_argument("--no-fuzzy", action="store_true", help="Desactiva el matching fuzzy")
    parser.add_argument("--dry-run", action="store_true", help="Muestra cobertura sin escribir")
    parser.add_argument("--fuente", default="placsp", help="Etiqueta de fuente para los aliases")
    parser.add_argument(
        "--scope-fuente",
        default=None,
        help="Acota el recorrido a las licitaciones de esa fuente (default: todas)",
    )
    parser.add_argument(
        "--time-budget",
        type=float,
        default=None,
        help="Segundos de pared tras los cuales cortar (deja el cursor guardado)",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Ignora el cursor guardado y recorre desde el principio",
    )
    args = parser.parse_args(argv)

    from db.database import init_db
    from db.empresas import resolution_stats
    from services.entity_resolution import reset_resolution_cursor, resolve_all_unlinked

    init_db()

    before = resolution_stats()
    print(
        f"Cobertura actual: {before['adjudicaciones_enlazadas']}/{before['adjudicaciones_total']} filas "
        f"({before['pct_filas']:.1f}%) · {before['pct_importe']:.1f}% del importe · "
        f"{before['empresas']} empresas · {before['revisiones_pendientes']} revisiones pendientes"
    )
    if args.dry_run:
        return 0

    if args.restart:
        reset_resolution_cursor(args.scope_fuente)
        print(f"Cursor reseteado para el ámbito '{args.scope_fuente or 'all'}'.")

    t0 = time.time()
    stats = resolve_all_unlinked(
        args.batch,
        fuente=args.fuente,
        fuzzy=not args.no_fuzzy,
        scope_fuente=args.scope_fuente,
        resume=True,
        time_budget_s=args.time_budget,
    )
    elapsed = time.time() - t0

    print(
        f"Procesadas {stats.fetched} adjudicaciones en {elapsed:.1f}s: "
        f"{stats.linked_nif} por NIF · {stats.linked_alias} por alias · "
        f"{stats.created} empresas nuevas · {stats.utes} UTEs · "
        f"{stats.queued_review} a revisión · {stats.skipped} omitidas"
    )
    if args.time_budget is not None and elapsed >= args.time_budget:
        print(
            f"Presupuesto agotado en el id {stats.last_id}. Volvé a lanzarlo "
            f"para continuar desde ahí."
        )

    after = resolution_stats()
    print(
        f"Cobertura final: {after['adjudicaciones_enlazadas']}/{after['adjudicaciones_total']} filas "
        f"({after['pct_filas']:.1f}%) · {after['pct_importe']:.1f}% del importe · "
        f"{after['empresas']} empresas · {after['revisiones_pendientes']} revisiones pendientes"
    )
    if after["revisiones_pendientes"]:
        print(
            "Hay matches dudosos en cola: revisar en la página Active Learning "
            "o vía db.empresas.apply_review()."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
