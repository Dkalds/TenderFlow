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
from pathlib import Path

# Ensure project root is on sys.path when run as `python -m scheduler.run_update`
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from db.database import count_licitaciones  # noqa: E402
from observability import (  # noqa: E402
    AlertLevel,
    configure_logging,
    get_logger,
    notify,
)
from scheduler.watchlist_alerts import check_and_notify  # noqa: E402
from scraper.pipeline import backfill, update_daily, update_recent  # noqa: E402


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
            result = update_daily()
            _handle_daily_result(result, log)
            return 0 if result.get("status") == "ok" else 1
        elif args.backfill:
            results = backfill(args.backfill[0], args.backfill[1])
        else:
            results = update_recent(args.months)
    except Exception as e:
        log.exception("pipeline_fatal_error")
        notify(AlertLevel.CRITICAL, "Pipeline licitaciones falló con error fatal", body=str(e))
        return 1

    failed = [r for r in results if r.get("status") not in ("ok", "no_publicado")]
    total_nuevas = sum(r.get("nuevas", 0) for r in results)
    total_act = sum(r.get("actualizadas", 0) for r in results)
    total_db = count_licitaciones()
    log.info(
        "pipeline_summary",
        nuevas=total_nuevas,
        actualizadas=total_act,
        total_bd=total_db,
        meses_fallidos=len(failed),
    )

    if failed:
        notify(
            AlertLevel.WARN,
            "Pipeline licitaciones con meses fallidos",
            body=f"{len(failed)} mes(es) con error.",
            meses_fallidos=[f"{r['year']}-{r['month']:02d}:{r['status']}" for r in failed],
            nuevas=total_nuevas,
            total_bd=total_db,
        )
        return 1

    try:
        check_and_notify()
    except Exception:
        log.exception("watchlist_alert_error")

    return 0


def _handle_daily_result(result: dict, log) -> None:
    """Procesa resultado del carril diario: alertas watchlist + notificación."""
    if result.get("status") != "ok":
        return

    inserted = result.get("inserted", [])
    modified = result.get("modified", [])
    total_nuevas = len(inserted)
    total_modificadas = len(modified)

    log.info(
        "daily_pipeline_summary",
        nuevas=total_nuevas,
        modificadas=total_modificadas,
        total_bd=count_licitaciones(),
    )

    # Disparar alertas watchlist (cubre tanto nuevas como existentes)
    try:
        check_and_notify()
    except Exception:
        log.exception("watchlist_alert_error_daily")

    # Notificar si hubo modificaciones interesantes
    if total_modificadas > 0:
        notify(
            AlertLevel.INFO,
            f"Feed diario: {total_modificadas} licitación(es) modificada(s)",
            body=f"IDs modificados: {', '.join(modified[:20])}"
            + (f" (+{total_modificadas - 20} más)" if total_modificadas > 20 else ""),
            nuevas=total_nuevas,
            modificadas=total_modificadas,
        )


if __name__ == "__main__":
    sys.exit(main())
