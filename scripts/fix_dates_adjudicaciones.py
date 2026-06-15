"""One-shot data fix: normalize DD/MM/YYYY dates to ISO in adjudicaciones.

Run against the production DB to correct dates that were stored in
DD/MM/YYYY format before the _normalize_date() parser fix.

Usage:
    python -m scripts.fix_dates_adjudicaciones --dry-run   # preview changes
    python -m scripts.fix_dates_adjudicaciones              # apply changes
"""

from __future__ import annotations

import argparse
import re
import sys

from db.database import connect, init_db
from observability.logging import get_logger

log = get_logger(__name__)

_DATE_DMY_RE = re.compile(r"^(\d{2})[/\-](\d{2})[/\-](\d{4})$")


def _normalize(raw: str) -> str | None:
    """Convert DD/MM/YYYY → YYYY-MM-DD. Returns None if already ISO or unrecognized."""
    m = _DATE_DMY_RE.match(raw.strip())
    if m:
        day, month, year = m.groups()
        return f"{year}-{month}-{day}"
    return None


def fix_adjudicaciones(dry_run: bool = True) -> int:
    """Find and fix DD/MM/YYYY dates in adjudicaciones.fecha_adjudicacion."""
    init_db()
    fixed = 0
    with connect() as c:
        rows = c.execute(
            "SELECT id, licitacion_id, fecha_adjudicacion FROM adjudicaciones "
            "WHERE fecha_adjudicacion IS NOT NULL"
        ).fetchall()
        for row_id, lic_id, fecha in rows:
            normalized = _normalize(str(fecha))
            if normalized:
                fixed += 1
                log.info(
                    "fix_date",
                    table="adjudicaciones",
                    id=row_id,
                    licitacion_id=lic_id,
                    old=fecha,
                    new=normalized,
                    dry_run=dry_run,
                )
                if not dry_run:
                    c.execute(
                        "UPDATE adjudicaciones SET fecha_adjudicacion = ? WHERE id = ?",
                        (normalized, row_id),
                    )

    # Also fix licitaciones date fields
    date_cols = [
        "fecha_publicacion",
        "fecha_limite",
        "fecha_inicio",
        "fecha_fin",
    ]
    with connect() as c:
        for col in date_cols:
            rows = c.execute(
                f"SELECT id_externo, {col} FROM licitaciones WHERE {col} IS NOT NULL"  # noqa: S608
            ).fetchall()
            for id_ext, fecha in rows:
                normalized = _normalize(str(fecha))
                if normalized:
                    fixed += 1
                    log.info(
                        "fix_date",
                        table="licitaciones",
                        id_externo=id_ext,
                        column=col,
                        old=fecha,
                        new=normalized,
                        dry_run=dry_run,
                    )
                    if not dry_run:
                        c.execute(
                            f"UPDATE licitaciones SET {col} = ? WHERE id_externo = ?",  # noqa: S608
                            (normalized, id_ext),
                        )

    return fixed


def main() -> int:
    parser = argparse.ArgumentParser(description="Fix DD/MM/YYYY dates in DB")
    parser.add_argument("--dry-run", action="store_true", help="Preview without modifying")
    args = parser.parse_args()

    n = fix_adjudicaciones(dry_run=args.dry_run)
    mode = "DRY RUN" if args.dry_run else "APPLIED"
    print(f"[{mode}] {n} dates would be/were fixed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
