"""Política de retención de datos — script CLI.

La lógica de retención vive en ``scheduler.retention``. Este script es el
entrypoint CLI para ejecución manual o desde cron externo.

Tablas afectadas (NO toca licitaciones ni adjudicaciones): las de
``scheduler.retention.POLITICA_RETENCION``. Los plazos por defecto son los
publicados en ``docs/SECURITY.md``; los flags ``--*-days`` los sobrescriben
para una ejecución puntual.

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

from scheduler.retention import POLITICA_RETENCION, run_retention  # noqa: E402


def _plazo(tabla: str) -> int:
    """Plazo publicado para *tabla*. Los defaults del CLI son la política."""
    return next(r.dias for r in POLITICA_RETENCION if r.tabla == tabla)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Purga de datos históricos por política de retención"
    )
    parser.add_argument(
        "--apply", action="store_true", help="Ejecutar la purga (sin este flag es dry-run)"
    )
    parser.add_argument(
        "--runs-days",
        type=int,
        default=_plazo("extraction_runs"),
        help="Retención extraction_runs (días)",
    )
    parser.add_argument(
        "--audit-days", type=int, default=_plazo("audit_log"), help="Retención audit_log (días)"
    )
    parser.add_argument(
        "--dlq-days",
        type=int,
        default=_plazo("failed_extractions"),
        help="Retención DLQ resueltos (días)",
    )
    parser.add_argument(
        "--history-days",
        type=int,
        default=_plazo("licitaciones_history"),
        help="Retención licitaciones_history (días)",
    )
    parser.add_argument(
        "--access-days", type=int, default=_plazo("access_log"), help="Retención access_log (días)"
    )
    parser.add_argument(
        "--idempotency-days",
        type=int,
        default=_plazo("idempotency_keys"),
        help="Retención idempotency_keys (días)",
    )
    parser.add_argument(
        "--webhook-deliveries-days",
        type=int,
        default=_plazo("webhook_deliveries"),
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
