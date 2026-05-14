"""Política de retención de datos — purga registros antiguos de tablas de soporte.

Tablas afectadas (NO toca licitaciones ni adjudicaciones):
    - extraction_runs      — runs del pipeline        (default: >90 días)
    - audit_log            — acciones de usuario      (default: >180 días)
    - failed_extractions   — DLQ resueltos            (default: >30 días)
    - licitaciones_history — histórico de cambios     (default: >365 días)
    - access_log           — log de accesos           (default: >180 días)

Uso:
    python scripts/retention_cleanup.py           # dry-run (muestra qué borraría)
    python scripts/retention_cleanup.py --apply   # ejecuta la purga
    python scripts/retention_cleanup.py --apply --runs-days 60
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path


def _cutoff_iso(days: int) -> str:
    from datetime import timedelta

    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _count_and_delete(conn, table: str, date_col: str, cutoff: str, *, apply: bool) -> int:
    cur = conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {date_col} < ?",  # noqa: S608
        (cutoff,),
    )
    count = cur.fetchone()[0]
    if apply and count > 0:
        conn.execute(
            f"DELETE FROM {table} WHERE {date_col} < ?",  # noqa: S608
            (cutoff,),
        )
    return int(count)


def run_retention(
    *,
    runs_days: int,
    audit_days: int,
    dlq_days: int,
    history_days: int,
    access_days: int,
    apply: bool,
) -> dict[str, int]:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from db.database import connect

    results: dict[str, int] = {}

    rules = [
        ("extraction_runs", "started_at", runs_days),
        ("audit_log", "created_at", audit_days),
        ("licitaciones_history", "changed_at", history_days),
        ("access_log", "logged_in_at", access_days),
    ]

    with connect() as conn:
        for table, col, days in rules:
            cutoff = _cutoff_iso(days)
            try:
                n = _count_and_delete(conn, table, col, cutoff, apply=apply)
                results[table] = n
                verb = "purgados" if apply else "a purgar"
                print(f"  {table}: {n:,} registros {verb} (>{days}d, antes de {cutoff[:10]})")
            except Exception as exc:
                print(f"  {table}: ERROR — {exc}", file=sys.stderr)
                results[table] = -1

        # DLQ: solo resueltos
        cutoff_dlq = _cutoff_iso(dlq_days)
        try:
            cur = conn.execute(
                "SELECT COUNT(*) FROM failed_extractions "
                "WHERE resolved_at IS NOT NULL AND resolved_at < ?",
                (cutoff_dlq,),
            )
            n_dlq = cur.fetchone()[0]
            if apply and n_dlq > 0:
                conn.execute(
                    "DELETE FROM failed_extractions "
                    "WHERE resolved_at IS NOT NULL AND resolved_at < ?",
                    (cutoff_dlq,),
                )
            results["failed_extractions"] = int(n_dlq)
            verb = "purgados" if apply else "a purgar"
            print(f"  failed_extractions (resueltos): {n_dlq:,} registros {verb} (>{dlq_days}d)")
        except Exception as exc:
            print(f"  failed_extractions: ERROR — {exc}", file=sys.stderr)
            results["failed_extractions"] = -1

    return results


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
    args = parser.parse_args()

    mode = "APLICANDO" if args.apply else "DRY-RUN"
    print(f"\n[retention] {mode} — política de retención de datos")
    print(f"  extraction_runs:      >{args.runs_days}d")
    print(f"  audit_log:            >{args.audit_days}d")
    print(f"  failed_extractions:   >{args.dlq_days}d (solo resueltos)")
    print(f"  licitaciones_history: >{args.history_days}d")
    print(f"  access_log:           >{args.access_days}d")
    print()

    results = run_retention(
        runs_days=args.runs_days,
        audit_days=args.audit_days,
        dlq_days=args.dlq_days,
        history_days=args.history_days,
        access_days=args.access_days,
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
