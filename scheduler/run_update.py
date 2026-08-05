"""Punto de entrada para ejecuciones programadas (GitHub Actions / cron).

Uso:
  python -m scheduler.run_update                # actualiza últimos 3 meses
  python -m scheduler.run_update --backfill 2024 1   # desde ene-2024
  python -m scheduler.run_update --months 6     # últimos 6 meses
  python -m scheduler.run_update --daily        # feed ATOM en vivo
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from db.database import count_licitaciones
from observability import (
    AlertLevel,
    configure_logging,
    get_logger,
    notify,
)
from scheduler.pipeline_runs import (
    run_backfill_pipeline,
    run_bulk_pipeline,
    run_daily_pipeline,
)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--months", type=int, default=3, help="Cuántos meses recientes refrescar (default 3)"
    )
    p.add_argument(
        "--backfill",
        nargs=2,
        type=int,
        metavar=("YEAR", "MONTH"),
        help="Backfill desde año/mes hasta hoy",
    )
    p.add_argument(
        "--daily",
        action="store_true",
        help="Ejecutar carril diario (feed ATOM en vivo)",
    )
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument(
        "--log-format",
        choices=("json", "console"),
        default=None,
        help="Formato de logs (default: auto)",
    )
    args = p.parse_args()

    configure_logging(
        level="DEBUG" if args.verbose else "INFO",
        json_logs=(args.log_format == "json") if args.log_format else None,
    )
    log = get_logger("run_update")

    try:
        if args.daily:
            pipeline_result = run_daily_pipeline()
            _log_daily_summary(pipeline_result, log)
            # Retorna 1 si la ingesta falló (alerta ya enviada en pipeline).
            ingestion_status = pipeline_result.get("ingestion_result", {}).get("status", "ok")
            return 0 if ingestion_status == "ok" else 1
        elif args.backfill:
            pipeline_result = run_backfill_pipeline(args.backfill[0], args.backfill[1])
        else:
            pipeline_result = run_bulk_pipeline(args.months)
    except Exception as e:
        log.exception("pipeline_fatal_error")
        notify(AlertLevel.CRITICAL, "Pipeline licitaciones falló con error fatal", body=str(e))
        return 1

    _log_bulk_summary(pipeline_result, log)
    # status="degraded" → algunos meses fallaron pero la pipeline completó los
    # pasos post-ingesta (alerta WARN ya emitida). Exit 1 para que CI/monitoring
    # lo detecte, sin la semántica de "error fatal".
    return 0 if pipeline_result.get("status") == "ok" else 1


def _log_daily_summary(pipeline_result: dict[str, Any], log: Any) -> None:
    """Log resumen del carril diario."""
    ingestion = pipeline_result.get("ingestion_result", {})
    inserted = ingestion.get("inserted", [])
    modified = ingestion.get("modified", [])
    total_nuevas = len(inserted)
    total_modificadas = len(modified)

    log.info(
        "daily_pipeline_summary",
        nuevas=total_nuevas,
        modificadas=total_modificadas,
        # estimado=True: este número es informativo, pero la llamada vive dentro
        # del try de main(), así que un COUNT(*) que cruce el statement_timeout
        # (19,5 s medidos en 2026-08 sobre 1,3 M filas) se convertiría en
        # "pipeline_fatal_error" + alerta CRITICAL + exit 1 con la ingesta ya
        # terminada bien. Una línea de log no puede tumbar el carril diario.
        total_bd=count_licitaciones(estimado=True),
        steps=pipeline_result.get("steps"),
    )

    if total_modificadas > 0:
        notify(
            AlertLevel.INFO,
            f"Feed diario: {total_modificadas} licitación(es) modificada(s)",
            body=f"IDs modificados: {', '.join(modified[:20])}"
            + (f" (+{total_modificadas - 20} más)" if total_modificadas > 20 else ""),
            nuevas=total_nuevas,
            modificadas=total_modificadas,
        )


def _log_bulk_summary(pipeline_result: dict[str, Any], log: Any) -> None:
    """Log resumen del carril bulk/backfill."""
    results = pipeline_result.get("ingestion_results", [])
    total_nuevas = sum(r.get("nuevas", 0) for r in results)
    total_act = sum(r.get("actualizadas", 0) for r in results)
    total_db = count_licitaciones(estimado=True)  # ver _log_daily_summary

    log.info(
        "pipeline_summary",
        nuevas=total_nuevas,
        actualizadas=total_act,
        total_bd=total_db,
        steps=pipeline_result.get("steps"),
    )


if __name__ == "__main__":
    sys.exit(main())
