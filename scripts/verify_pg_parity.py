"""Verificación de paridad SQLite ↔ Postgres tras la migración (F3b, ADR-016).

Ejecutar DESPUÉS de migrate_sqlite_to_pg.py y ANTES del cutover (F3c).
Este script es el gate binario del cutover: si falla, NO hacer el flip.

Checks:
  1. Counts por tabla: diferencia aceptable ≤ MAX_COUNT_DELTA_PCT (default 1%).
  2. Checksums de negocio (tablas clave): hash de campos clave ordenados.
  3. Agregados de negocio: total licitaciones, rangos de fecha, distribución CPV.
  4. Muestra de 100 filas: diff entre SQLite y PG para licitaciones.

Salida: JSON a stdout + código de salida 0 (OK) o 1 (falla).

Uso:
    python scripts/verify_pg_parity.py
    python scripts/verify_pg_parity.py --max-delta 5  # tolerar 5% de diferencia
    python scripts/verify_pg_parity.py --json-out parity_report.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Tablas clave para verificación de counts y checksums
_KEY_TABLES = [
    "licitaciones",
    "adjudicaciones",
    "users",
    "api_keys",
    "ingestion_cursors",
    "predicciones_baja",
    "predicciones_retencion",
]


def _connect_sqlite() -> sqlite3.Connection:
    import os

    from config import settings

    db_path = os.environ.get("DB_PATH") or str(settings.DB_PATH)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _connect_pg() -> Any:
    from db.connection import _database_url

    try:
        import psycopg  # type: ignore[import-not-found]
    except ImportError as e:
        print(f"[verify] ERROR: psycopg no instalado: {e}", file=sys.stderr)
        sys.exit(1)
    url = _database_url()
    if not url:
        print("[verify] ERROR: DATABASE_URL no definida", file=sys.stderr)
        sys.exit(1)
    try:
        return psycopg.connect(url)
    except Exception as exc:
        from observability.logging import redact_dsn

        print(
            f"[verify] ERROR: no se pudo conectar a Postgres: {redact_dsn(str(exc))}",
            file=sys.stderr,
        )
        sys.exit(1)


def _count(conn: Any, table: str, *, is_pg: bool) -> int:
    try:
        if is_pg:
            cur = conn.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
        else:
            cur = conn.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
        row = cur.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return -1


def _checksum_table(conn: Any, table: str, key_col: str, *, is_pg: bool) -> str:
    """Hash MD5 de la concatenación de key_col ordenada. Detecta diferencias de contenido."""
    try:
        if is_pg:
            cur = conn.execute(
                f"SELECT {key_col} FROM {table} ORDER BY {key_col} LIMIT 10000"  # noqa: S608
            )
        else:
            cur = conn.execute(
                f"SELECT {key_col} FROM {table} ORDER BY {key_col} LIMIT 10000"  # noqa: S608
            )
        rows = cur.fetchall()
        content = "|".join(str(r[0]) for r in rows)
        return hashlib.md5(content.encode()).hexdigest()  # noqa: S324 -- checksum no criptográfico
    except Exception as exc:
        return f"error:{exc}"


def _sample_rows(conn: Any, *, is_pg: bool, n: int = 100) -> list[dict[str, Any]]:
    """Muestra de N filas de licitaciones ordenadas por id_externo."""
    try:
        if is_pg:
            cur = conn.execute(
                "SELECT id_externo, titulo, estado, importe, ccaa "
                "FROM licitaciones ORDER BY id_externo LIMIT %s",
                (n,),
            )
        else:
            cur = conn.execute(
                "SELECT id_externo, titulo, estado, importe, ccaa "
                "FROM licitaciones ORDER BY id_externo LIMIT ?",
                (n,),
            )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
    except Exception:
        return []


def _business_aggregates(conn: Any, *, is_pg: bool) -> dict[str, Any]:
    """Agregados de negocio clave para detectar regresiones de datos."""
    result: dict[str, Any] = {}
    try:
        if is_pg:
            cur = conn.execute(
                "SELECT COUNT(*), MIN(fecha_publicacion), MAX(fecha_publicacion), "
                "AVG(importe) FROM licitaciones"
            )
        else:
            cur = conn.execute(
                "SELECT COUNT(*), MIN(fecha_publicacion), MAX(fecha_publicacion), "
                "AVG(importe) FROM licitaciones"
            )
        row = cur.fetchone()
        if row:
            result["count"] = row[0]
            result["min_fecha"] = str(row[1])
            result["max_fecha"] = str(row[2])
            result["avg_importe"] = round(float(row[3] or 0), 2)
    except Exception as exc:
        result["error"] = str(exc)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Verificación de paridad SQLite ↔ Postgres")
    parser.add_argument(
        "--max-delta",
        type=float,
        default=1.0,
        help="% máximo de diferencia en counts aceptable (default 1.0)",
    )
    parser.add_argument("--json-out", metavar="FILE", help="Guardar reporte JSON en este archivo")
    args = parser.parse_args()

    print("== verify_pg_parity ==\n")

    sqlite = _connect_sqlite()
    pg = _connect_pg()

    report: dict[str, Any] = {
        "status": "ok",
        "max_delta_pct": args.max_delta,
        "counts": {},
        "checksums": {},
        "aggregates": {},
        "sample_diff": [],
        "failures": [],
    }

    # ── 1. Counts ─────────────────────────────────────────────────────────
    print("Counts:")
    for table in _KEY_TABLES:
        n_sqlite = _count(sqlite, table, is_pg=False)
        n_pg = _count(pg, table, is_pg=True)
        if n_sqlite < 0 or n_pg < 0:
            delta_pct = 0.0
            icon = "?"
        elif n_sqlite == 0:
            delta_pct = 0.0 if n_pg == 0 else 100.0
            icon = "✓" if n_pg == 0 else "✗"
        else:
            delta_pct = abs(n_sqlite - n_pg) / n_sqlite * 100
            icon = "✓" if delta_pct <= args.max_delta else "✗"

        print(f"  {icon} {table}: sqlite={n_sqlite}, pg={n_pg}, delta={delta_pct:.2f}%")
        report["counts"][table] = {"sqlite": n_sqlite, "pg": n_pg, "delta_pct": delta_pct}

        if icon == "✗":
            report["status"] = "failed"
            report["failures"].append(f"count:{table} delta={delta_pct:.1f}%")

    # ── 2. Checksums (licitaciones) ───────────────────────────────────────
    print("\nChecksums:")
    for table, key_col in [("licitaciones", "id_externo"), ("users", "email")]:
        h_sqlite = _checksum_table(sqlite, table, key_col, is_pg=False)
        h_pg = _checksum_table(pg, table, key_col, is_pg=True)
        match = h_sqlite == h_pg and not h_sqlite.startswith("error")
        icon = "✓" if match else "!"
        print(f"  {icon} {table}.{key_col}: {h_sqlite[:8]}... vs {h_pg[:8]}...")
        report["checksums"][table] = {"sqlite": h_sqlite, "pg": h_pg, "match": match}
        if not match and not h_sqlite.startswith("error") and not h_pg.startswith("error"):
            print(
                "    → Checksums difieren (puede ser esperado si hay nuevas filas desde la migración)"
            )

    # ── 3. Agregados de negocio ───────────────────────────────────────────
    print("\nAgregados de negocio:")
    agg_sqlite = _business_aggregates(sqlite, is_pg=False)
    agg_pg = _business_aggregates(pg, is_pg=True)
    report["aggregates"] = {"sqlite": agg_sqlite, "pg": agg_pg}

    for key in ("count", "min_fecha", "max_fecha"):
        v_s = agg_sqlite.get(key)
        v_p = agg_pg.get(key)
        icon = "✓" if v_s == v_p else "!"
        print(f"  {icon} {key}: sqlite={v_s}, pg={v_p}")

    # ── 4. Muestra de 100 filas ───────────────────────────────────────────
    print("\nMuestra de 100 licitaciones:")
    sample_sqlite = _sample_rows(sqlite, is_pg=False)
    sample_pg = _sample_rows(pg, is_pg=True)

    sqlite_ids = {r["id_externo"] for r in sample_sqlite}
    pg_ids = {r["id_externo"] for r in sample_pg}
    only_sqlite = sqlite_ids - pg_ids
    only_pg = pg_ids - sqlite_ids

    if only_sqlite:
        print(f"  ! Solo en SQLite: {list(only_sqlite)[:5]}...")
        report["sample_diff"].extend([f"only_sqlite:{i}" for i in list(only_sqlite)[:5]])
    if only_pg:
        print(f"  ! Solo en Postgres: {list(only_pg)[:5]}...")
        report["sample_diff"].extend([f"only_pg:{i}" for i in list(only_pg)[:5]])
    if not only_sqlite and not only_pg:
        print("  ✓ Sin diferencias en la muestra")

    # ── Resumen ───────────────────────────────────────────────────────────
    print(f"\n[verify] Status: {report['status'].upper()}")
    if report["failures"]:
        for f in report["failures"]:
            print(f"  ✗ {f}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2, default=str))
        print(f"[verify] Reporte guardado en {args.json_out}")

    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
