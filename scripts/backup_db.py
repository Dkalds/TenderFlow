"""Backup de la base de datos SQLite local y Turso.

Uso:
    python scripts/backup_db.py                 # SQLite local
    python scripts/backup_db.py --turso         # Turso (requiere turso CLI)
    python scripts/backup_db.py --keep 7        # retener últimos N backups (default: 7)

El backup se guarda en data/backups/ con timestamp en el nombre.
Los backups más antiguos que --keep se eliminan automáticamente.
"""

from __future__ import annotations

import argparse
import gzip
import shutil
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


def backup_sqlite(db_path: Path, backup_dir: Path) -> Path:
    """Copia segura (online backup) de una base de datos SQLite."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / f"licitaciones_{_timestamp()}.db"
    src_conn = sqlite3.connect(str(db_path))
    dst_conn = sqlite3.connect(str(dest))
    try:
        src_conn.backup(dst_conn)
        dst_conn.close()
    finally:
        src_conn.close()

    # Comprimir el backup
    gz_dest = Path(str(dest) + ".gz")
    with open(dest, "rb") as f_in, gzip.open(gz_dest, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    dest.unlink()

    size_kb = gz_dest.stat().st_size // 1024
    print(f"[backup] SQLite → {gz_dest} ({size_kb} KB)")
    return gz_dest


def backup_turso(backup_dir: Path) -> Path | None:
    """Backup de Turso usando el CLI oficial.

    Requiere: turso CLI instalado y autenticado (``turso auth login``).
    Lee TURSO_DATABASE_URL del entorno para determinar el nombre de la BD.
    """
    import os

    turso_url = os.environ.get("TURSO_DATABASE_URL", "")
    if not turso_url:
        print("[backup] TURSO_DATABASE_URL no configurada — omitiendo backup Turso.", file=sys.stderr)
        return None

    db_name = turso_url.rstrip("/").split("/")[-1]
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / f"turso_{db_name}_{_timestamp()}.db"

    try:
        subprocess.run(
            ["turso", "db", "shell", db_name, ".dump"],
            check=True,
            stdout=open(dest, "w"),
            text=True,
        )
    except FileNotFoundError:
        print("[backup] turso CLI no encontrado. Instala: https://docs.turso.tech/cli/introduction", file=sys.stderr)
        return None
    except subprocess.CalledProcessError as exc:
        print(f"[backup] Error ejecutando turso CLI: {exc}", file=sys.stderr)
        return None

    # Comprimir
    gz_dest = Path(str(dest) + ".gz")
    with open(dest, "rb") as f_in, gzip.open(gz_dest, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    dest.unlink()

    size_kb = gz_dest.stat().st_size // 1024
    print(f"[backup] Turso → {gz_dest} ({size_kb} KB)")
    return gz_dest


def prune_old_backups(backup_dir: Path, keep: int) -> int:
    """Elimina los backups más antiguos, manteniendo los últimos ``keep``."""
    backups = sorted(backup_dir.glob("*.db.gz"), key=lambda p: p.stat().st_mtime)
    to_delete = backups[: max(0, len(backups) - keep)]
    for f in to_delete:
        f.unlink()
        print(f"[backup] Eliminado backup antiguo: {f.name}")
    return len(to_delete)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup de la base de datos")
    parser.add_argument("--turso", action="store_true", help="Hacer backup de Turso además de SQLite local")
    parser.add_argument("--keep", type=int, default=7, help="Número de backups a retener (default: 7)")
    parser.add_argument("--dry-run", action="store_true", help="Solo mostrar qué se haría, sin ejecutar")
    args = parser.parse_args()

    # Importar settings para obtener rutas
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from config import settings

    backup_dir = settings.DATA_DIR / "backups"
    db_path = settings.DB_PATH or (settings.DATA_DIR / "licitaciones.db")

    if args.dry_run:
        print(f"[dry-run] Backup SQLite: {db_path} → {backup_dir}")
        if args.turso:
            print("[dry-run] Backup Turso habilitado")
        print(f"[dry-run] Retener últimos {args.keep} backups")
        return 0

    errors = 0
    if db_path and db_path.exists():
        try:
            backup_sqlite(db_path, backup_dir)
        except Exception as exc:
            print(f"[backup] ERROR backup SQLite: {exc}", file=sys.stderr)
            errors += 1
    else:
        print(f"[backup] SQLite no encontrada en {db_path}", file=sys.stderr)

    if args.turso:
        try:
            backup_turso(backup_dir)
        except Exception as exc:
            print(f"[backup] ERROR backup Turso: {exc}", file=sys.stderr)
            errors += 1

    pruned = prune_old_backups(backup_dir, args.keep)
    if pruned:
        print(f"[backup] {pruned} backup(s) antiguos eliminados.")

    return errors


if __name__ == "__main__":
    raise SystemExit(main())
