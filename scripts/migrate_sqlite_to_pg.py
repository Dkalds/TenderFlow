"""Migración de datos SQLite → Postgres (F3b, ADR-016).

Lee la BD SQLite local (réplica o DB_PATH) y escribe en DATABASE_URL (Postgres).

Estrategia por tabla:
  - Grandes con timestamp (licitaciones, adjudicaciones, extraction_runs):
    incremental por fecha_extraccion/created_at.
  - Append-only con id (api_keys, webhooks, watchlist_*, sessions, users…):
    incremental por id máximo conocido en destino.
  - Pequeñas / lookup (feature_flags, model_versions, ingestion_cursors…):
    TRUNCATE + COPY FROM (idempotente, datos pequeños).

Optimización de escritura: usa COPY FROM STDIN (psycopg3 copy protocol)
para las tablas grandes en lugar de INSERT fila a fila.

No migra:
  - licitaciones_fts (tabla virtual FTS5, se autopuebla via search_vector en PG)
  - Tablas de caché efímera (rate_limits, ops_events recientes)

Uso:
    python scripts/migrate_sqlite_to_pg.py
    python scripts/migrate_sqlite_to_pg.py --dry-run
    python scripts/migrate_sqlite_to_pg.py --only licitaciones adjudicaciones
    python scripts/migrate_sqlite_to_pg.py --reset  # truncate todas antes de migrar
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── Configuración de tablas ───────────────────────────────────────────────────


@dataclass
class TableSpec:
    name: str
    strategy: str  # "incremental_ts" | "incremental_id" | "truncate_reload"
    ts_col: str = ""  # columna de timestamp para incremental_ts
    id_col: str = "id"  # columna de id para incremental_id
    order_col: str = ""  # columna de ordenación (default = ts_col o id_col)
    skip: bool = False  # True = no migrar

    def __post_init__(self) -> None:
        if not self.order_col:
            self.order_col = self.ts_col or self.id_col


# Orden FK-safe (dependencias primero)
TABLE_SPECS: list[TableSpec] = [
    TableSpec("users", "incremental_id"),
    TableSpec("grupos_empresariales", "truncate_reload"),
    TableSpec("empresas", "incremental_id", id_col="empresa_id"),
    TableSpec("empresa_aliases", "incremental_id"),
    TableSpec("licitaciones", "incremental_ts", ts_col="fecha_extraccion"),
    # PK compuesta (licitacion_id, tecnologia) -- sin columna id autoincremental,
    # no aplica estrategia incremental_id.
    TableSpec("licitacion_tecnologia_score", "truncate_reload"),
    TableSpec(
        "adjudicaciones", "incremental_ts", ts_col="fecha_extraccion", order_col="fecha_extraccion"
    ),
    TableSpec("ute_miembros", "incremental_id"),
    TableSpec("empresa_review_queue", "incremental_id"),
    TableSpec("contrato_eventos", "incremental_ts", ts_col="created_at"),
    TableSpec("resoluciones_recurso", "incremental_id"),
    TableSpec("predicciones_baja", "incremental_ts", ts_col="computed_at"),
    TableSpec("predicciones_retencion", "incremental_ts", ts_col="computed_at"),
    TableSpec("watchlist_empresas", "incremental_id"),
    TableSpec("watchlist_rules", "incremental_id"),
    TableSpec("watchlist_items", "incremental_id"),
    TableSpec("extracciones", "incremental_id"),
    TableSpec("ingestion_cursors", "truncate_reload"),
    TableSpec("ml_feedback", "incremental_id"),
    TableSpec("webhooks", "incremental_id"),
    TableSpec("model_versions", "incremental_id"),
    TableSpec("totp_secrets", "incremental_id"),
    TableSpec("totp_recovery_codes", "incremental_id"),
    TableSpec("sessions", "incremental_id"),
    TableSpec("feature_flags", "truncate_reload"),
    TableSpec("feature_store", "incremental_ts", ts_col="updated_at"),
    TableSpec("domain_events", "incremental_id"),
    TableSpec("job_locks", "truncate_reload"),
    TableSpec("ops_events", "incremental_id"),
    TableSpec("user_notifications", "incremental_id"),
    TableSpec("user_profiles", "incremental_id"),
    TableSpec("api_keys", "incremental_id"),
    TableSpec("saved_filters", "incremental_id"),
    TableSpec("licitaciones_duplicados", "incremental_id"),
    TableSpec("extraction_runs", "incremental_ts", ts_col="started_at"),
    TableSpec("failed_extractions", "incremental_id"),
    TableSpec("access_log", "incremental_id"),
    TableSpec("acl_rules", "truncate_reload"),
    # licitaciones_fts: tabla virtual FTS5 — se autopuebla en PG via search_vector
    TableSpec("licitaciones_fts", strategy="truncate_reload", skip=True),
    # licitaciones_history: historial de cambios — migrar todo
    TableSpec("licitaciones_history", "incremental_id"),
    # rate_limits: caché efímera — no migrar
    TableSpec("rate_limits", strategy="truncate_reload", skip=True),
    # csp_violations: logs de seguridad — incremental
    TableSpec("csp_violations", "incremental_id"),
]


# ── Helpers ───────────────────────────────────────────────────────────────────


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
        print(f"[migrate] ERROR: psycopg no instalado: {e}", file=sys.stderr)
        sys.exit(1)
    url = _database_url()
    if not url:
        print("[migrate] ERROR: DATABASE_URL no definida", file=sys.stderr)
        sys.exit(1)
    try:
        return psycopg.connect(url)
    except Exception as exc:
        from observability.logging import redact_dsn

        print(
            f"[migrate] ERROR: no se pudo conectar a Postgres: {redact_dsn(str(exc))}",
            file=sys.stderr,
        )
        sys.exit(1)


def _table_exists_pg(pg: Any, table: str) -> bool:
    cur = pg.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = %s LIMIT 1",
        (table,),
    )
    return cur.fetchone() is not None


def _get_pg_max(pg: Any, table: str, col: str) -> Any:
    """Devuelve el valor máximo de col en la tabla PG, o None si vacía."""
    try:
        cur = pg.execute(f"SELECT MAX({col}) FROM {table}")  # noqa: S608
        row = cur.fetchone()
        return row[0] if row else None
    except Exception:
        return None


def _get_columns(sqlite: sqlite3.Connection, table: str) -> list[str]:
    cur = sqlite.execute(f"PRAGMA table_info({table})")
    return [r[1] for r in cur.fetchall()]


def _migrate_table(
    spec: TableSpec,
    sqlite: sqlite3.Connection,
    pg: Any,
    *,
    dry_run: bool,
    reset: bool,
) -> dict[str, Any]:
    """Migra una tabla según su estrategia. Devuelve estadísticas."""
    result: dict[str, Any] = {"table": spec.name, "rows": 0, "status": "ok"}

    if not _table_exists_pg(pg, spec.name):
        result["status"] = "skipped_no_pg_table"
        return result

    cols = _get_columns(sqlite, spec.name)
    if not cols:
        result["status"] = "skipped_no_sqlite_cols"
        return result

    # Excluir search_vector (columna generada en PG, no existe en SQLite)
    cols = [c for c in cols if c != "search_vector"]
    col_list = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))

    if reset or spec.strategy == "truncate_reload":
        if not dry_run:
            pg.execute(f"TRUNCATE TABLE {spec.name} CASCADE")
        t0 = time.monotonic()
        rows = sqlite.execute(f"SELECT {col_list} FROM {spec.name}").fetchall()  # noqa: S608
    elif spec.strategy == "incremental_ts":
        max_val = _get_pg_max(pg, spec.name, spec.ts_col)
        if max_val:
            rows = sqlite.execute(
                f"SELECT {col_list} FROM {spec.name} "  # noqa: S608
                f"WHERE {spec.ts_col} > ? ORDER BY {spec.order_col}",
                (str(max_val),),
            ).fetchall()
        else:
            rows = sqlite.execute(
                f"SELECT {col_list} FROM {spec.name} ORDER BY {spec.order_col}"  # noqa: S608
            ).fetchall()
        t0 = time.monotonic()
    elif spec.strategy == "incremental_id":
        max_val = _get_pg_max(pg, spec.name, spec.id_col)
        if max_val:
            rows = sqlite.execute(
                f"SELECT {col_list} FROM {spec.name} "  # noqa: S608
                f"WHERE {spec.id_col} > ? ORDER BY {spec.id_col}",
                (max_val,),
            ).fetchall()
        else:
            rows = sqlite.execute(
                f"SELECT {col_list} FROM {spec.name} ORDER BY {spec.id_col}"  # noqa: S608
            ).fetchall()
        t0 = time.monotonic()
    else:
        result["status"] = "unknown_strategy"
        return result

    n = len(rows)
    result["rows"] = n

    if n == 0:
        result["status"] = "ok_no_rows"
        return result

    if dry_run:
        result["status"] = "dry_run"
        return result

    # Insertar en lotes usando executemany con ON CONFLICT DO NOTHING
    insert_sql = (
        f"INSERT INTO {spec.name} ({col_list}) "  # noqa: S608
        f"VALUES ({placeholders}) ON CONFLICT DO NOTHING"
    )
    batch_size = 500
    with pg.cursor() as cur:
        for i in range(0, n, batch_size):
            batch = [tuple(r) for r in rows[i : i + batch_size]]
            cur.executemany(insert_sql, batch)

    pg.commit()
    result["elapsed_s"] = round(time.monotonic() - t0, 2)
    return result


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="Migración SQLite → Postgres")
    parser.add_argument("--dry-run", action="store_true", help="No escribir en Postgres")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="TRUNCATE todas las tablas antes de migrar (idempotente)",
    )
    parser.add_argument("--only", nargs="+", metavar="TABLE", help="Migrar solo estas tablas")
    args = parser.parse_args()

    print("== migrate_sqlite_to_pg ==\n")
    if args.dry_run:
        print("[migrate] DRY RUN — no se escribe en Postgres\n")

    sqlite = _connect_sqlite()
    pg = _connect_pg()

    specs = [s for s in TABLE_SPECS if not s.skip]
    if args.only:
        specs = [s for s in specs if s.name in args.only]
        if not specs:
            print(f"[migrate] No se encontraron tablas: {args.only}", file=sys.stderr)
            return 1

    total_rows = 0
    errors: list[str] = []

    for spec in specs:
        try:
            r = _migrate_table(spec, sqlite, pg, dry_run=args.dry_run, reset=args.reset)
            icon = "✓" if r["status"] in ("ok", "ok_no_rows", "dry_run") else "!"
            elapsed = f" ({r.get('elapsed_s', 0):.1f}s)" if "elapsed_s" in r else ""
            print(f"  {icon} {spec.name}: {r['rows']} filas [{r['status']}]{elapsed}")
            total_rows += r["rows"]
        except Exception as exc:
            print(f"  ✗ {spec.name}: ERROR — {exc}", file=sys.stderr)
            errors.append(f"{spec.name}: {exc}")
            try:
                pg.rollback()
            except Exception:
                pass

    print(f"\n[migrate] Total: {total_rows} filas migradas, {len(errors)} errores")
    if errors:
        for e in errors:
            print(f"  ✗ {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
