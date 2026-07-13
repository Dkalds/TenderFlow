"""Backfill de metadatos de documentos (pliegos) sobre licitaciones históricas.

La extracción de adjuntos (``parse_document_references`` → tabla
``documentos``) solo vive en el camino connector (``PlacspAtomConnector`` /
``PlacspBulkConnector`` vía ``run_connector``, plan Pliegos+RAG F6). El feed
diario ya cubre de aquí en adelante; el carril de backfill histórico
(``scheduler.run_update --backfill``) sigue siendo legacy y nunca extrae
documentos (ver ADR-009, nota del flip F2). Este script cierra ese hueco para
las licitaciones que ya estaban en BD antes de que el feature existiera:
recorre los ZIPs mensuales de PLACSP hacia atrás y re-corre el conector bulk.

Idempotente y seguro de re-ejecutar: ``PlacspBulkConnector`` no tiene cursor
propio (paramétrico por mes), el upsert de licitaciones/adjudicaciones es el
mismo de siempre, y ``documentos`` tiene ``UNIQUE(licitacion_id, uri)`` con
``ON CONFLICT DO NOTHING`` -- un mes ya procesado no duplica nada. Si se corta
a mitad de camino, ``--skip-months N`` permite retomar sin repetir los meses
ya hechos.

Uso:
    python -m scripts.backfill_documentos                  # últimos 5 años
    python -m scripts.backfill_documentos --years 2         # últimos 2 años
    python -m scripts.backfill_documentos --dry-run          # solo lista los meses
    python -m scripts.backfill_documentos --skip-months 20   # retoma tras un corte
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime


def _months_back(years: int) -> list[tuple[int, int]]:
    """Últimos ``years * 12`` meses, del más reciente al más antiguo."""
    from dateutil.relativedelta import relativedelta

    today = datetime.now(UTC).date()
    return [
        ((today - relativedelta(months=i)).year, (today - relativedelta(months=i)).month)
        for i in range(years * 12)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill histórico de metadatos de documentos (pliegos)"
    )
    parser.add_argument("--years", type=int, default=5, help="Años hacia atrás (default 5)")
    parser.add_argument(
        "--skip-months",
        type=int,
        default=0,
        help="Salta los N meses más recientes de la lista (para retomar tras un corte)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Solo lista los meses a procesar, sin tocar la BD"
    )
    args = parser.parse_args(argv)

    months = _months_back(args.years)[args.skip_months :]
    print(f"Backfill de documentos: {len(months)} meses (últimos {args.years} años)")

    if args.dry_run:
        for year, month in months:
            print(f"  {year}-{month:02d}")
        return 0

    from db.database import init_db
    from db.repositories.documentos import DocumentosRepository
    from scraper.connectors.base import run_connector
    from scraper.connectors.placsp import PlacspBulkConnector

    init_db()
    docs_repo = DocumentosRepository()

    docs_antes = docs_repo.count_all()
    total_nuevas = total_actualizadas = total_adjudicaciones = total_errores = 0
    meses_fallidos: list[str] = []
    t0 = time.time()

    for year, month in months:
        label = f"{year}-{month:02d}"
        try:
            connector = PlacspBulkConnector(year, month)
            result = run_connector(connector)
        except Exception as exc:  # defensa extra: un mes roto no debe abortar el resto
            print(f"  {label}: FALLÓ -- {exc}")
            meses_fallidos.append(label)
            continue

        if result.fetch_failed:
            meses_fallidos.append(label)

        total_nuevas += result.nuevas
        total_actualizadas += result.actualizadas
        total_adjudicaciones += result.adjudicaciones
        total_errores += result.errores
        print(
            f"  {label}: fetched={result.fetched} parsed={result.parsed} "
            f"nuevas={result.nuevas} actualizadas={result.actualizadas} "
            f"errores={result.errores}" + (" [fetch_failed]" if result.fetch_failed else "")
        )

    elapsed = time.time() - t0
    docs_despues = docs_repo.count_all()
    print(
        f"\nBackfill completo en {elapsed / 60:.1f} min: "
        f"{total_nuevas} nuevas · {total_actualizadas} actualizadas · "
        f"{total_adjudicaciones} adjudicaciones · {total_errores} errores · "
        f"documentos {docs_antes} -> {docs_despues} (+{docs_despues - docs_antes})"
    )
    if meses_fallidos:
        print(
            f"Meses con fetch fallido (reintentar con --skip-months apuntando a ellos): "
            f"{', '.join(meses_fallidos)}"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
