"""Política de retención de datos — script CLI.

La lógica de retención vive en ``scheduler.retention``. Este script es el
entrypoint CLI para ejecución manual o desde cron externo.

Tablas afectadas (NO toca licitaciones ni adjudicaciones):
    - extraction_runs      — runs del pipeline        (default: >90 días)
    - audit_log            — acciones de usuario      (default: >180 días)
    - failed_extractions   — DLQ resueltos            (default: >30 días)
    - licitaciones_history — histórico de cambios     (default: >365 días)
    - access_log           — log de accesos           (default: >180 días)
    - idempotency_keys     — claves de idempotencia   (default: >1 día)
    - webhook_deliveries   — historial de entregas    (default: >90 días)
    - rate_limits          — ventanas de rate limit   (expiradas — siempre)

Uso:
    python scripts/retention_cleanup.py           # dry-run (muestra qué borraría)
    python scripts/retention_cleanup.py --apply   # ejecuta la purga
    python scripts/retention_cleanup.py --apply --runs-days 60
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Asegurar que el root del proyecto está en sys.path para importación standalone
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scheduler.retention import run_retention  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Purga de datos históricos por política de retención"
    )
    parser.add_argument(
        "--apply", action="store_true", help="Ejecutar la purga (sin este flag es dry-run)"
    )
    parser.add_argument(
        "--runs-days", type=int, default=90, help="Retención extraction_runs (días)"
    )
    parser.add_argument("--audit-days", type=int, default=180, help="Retención audit_log (días)")
    parser.add_argument("--dlq-days", type=int, default=30, help="Retención DLQ resueltos (días)")
    parser.add_argument(
        "--history-days", type=int, default=365, help="Retención licitaciones_history (días)"
    )
    parser.add_argument("--access-days", type=int, default=180, help="Retención access_log (días)")
    parser.add_argument(
        "--idempotency-days", type=int, default=1, help="Retención idempotency_keys (días)"
    )
    parser.add_argument(
        "--webhook-deliveries-days",
        type=int,
        default=90,
        help="Retención webhook_deliveries (días)",
    )
    args = parser.parse_args()

    mode = "APLICANDO" if args.apply else "DRY-RUN"
    print(f"\n[retention] {mode} — política de retención de datos")
    print(f"  extraction_runs:      >{args.runs_days}d")
    print(f"  audit_log:            >{args.audit_days}d")
    print(f"  failed_extractions:   >{args.dlq_days}d (solo resueltos)")
    print(f"  licitaciones_history: >{args.history_days}d")
    print(f"  access_log:           >{args.access_days}d")
    print(f"  idempotency_keys:     >{args.idempotency_days}d")
    print(f"  webhook_deliveries:   >{args.webhook_deliveries_days}d")
    print("  rate_limits:          expiradas")
    print()

    results = run_retention(
        runs_days=args.runs_days,
        audit_days=args.audit_days,
        dlq_days=args.dlq_days,
        history_days=args.history_days,
        access_days=args.access_days,
        idempotency_days=args.idempotency_days,
        webhook_deliveries_days=args.webhook_deliveries_days,
        apply=args.apply,
    )

    total = sum(v for v in results.values() if v >= 0)
    if args.apply:
        print(f"\n[retention] {total:,} registros purgados en total.")
    else:
        print(f"\n[retention] {total:,} registros serían purgados. Usa --apply para ejecutar.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
