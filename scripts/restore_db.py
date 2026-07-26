"""Restore y verificación de backups SQLite (complementa scripts/backup_db.py).

Hasta ahora el restore vivía solo como snippets inline en
``docs/runbooks/backup-restore.md`` — sin función reutilizable ni probada. Un
backup que nadie restaura no es un backup. Este módulo aporta:

- :func:`verify_backup` — descomprime un ``.db.gz`` a un fichero temporal,
  corre ``PRAGMA integrity_check`` y una query de humo (nº de tablas + filas en
  ``licitaciones``). Devuelve un resultado estructurado; no lanza salvo I/O.
- :func:`restore_backup` — restaura un ``.db.gz`` sobre la BD destino, guardando
  la versión actual como ``.bak`` (reversible).

Ambas son la base del *restore drill* periódico (``.github/workflows/restore-drill.yml``)
y de ``tests/test_backup_restore.py``.

Uso:
    python scripts/restore_db.py --verify                 # verifica el último backup local
    python scripts/restore_db.py --verify path/al.db.gz   # verifica uno concreto
    python scripts/restore_db.py --restore path/al.db.gz  # restaura (crea .bak)
"""

from __future__ import annotations

import argparse
import gzip
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class VerifyResult:
    """Resultado de verificar un backup."""

    backup: str
    ok: bool
    integrity: str
    tablas: int
    licitaciones: int
    error: str | None = None

    def as_line(self) -> str:
        mark = "OK" if self.ok else "FAIL"
        if self.error:
            return f"[{mark}] {self.backup}: {self.error}"
        return (
            f"[{mark}] {self.backup}: integrity={self.integrity}, "
            f"tablas={self.tablas}, licitaciones={self.licitaciones}"
        )


def _decompress_to(gz_path: Path, dest: Path) -> None:
    with gzip.open(gz_path, "rb") as f_in, open(dest, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)


def _materialize_compressed_backup(backup: Path, temp_dir: Path) -> Path:
    """Return a .db.gz path, decrypting GPG backups only into a temp directory."""
    if backup.suffix != ".gpg":
        return backup
    passphrase = os.environ.get("BACKUP_ENCRYPTION_KEY", "")
    if not passphrase:
        raise OSError("BACKUP_ENCRYPTION_KEY is required for encrypted backup restore")
    gpg_bin = shutil.which("gpg")
    if not gpg_bin:
        raise OSError("gpg is required for encrypted backup restore")
    decrypted = temp_dir / backup.with_suffix("").name
    try:
        subprocess.run(
            [
                gpg_bin,
                "--batch",
                "--yes",
                "--pinentry-mode",
                "loopback",
                "--passphrase-fd",
                "0",
                "--output",
                str(decrypted),
                "--decrypt",
                str(backup),
            ],
            check=True,
            capture_output=True,
            input=passphrase.encode(),
        )
    except subprocess.CalledProcessError as exc:
        raise OSError("could not decrypt backup") from exc
    return decrypted


def verify_backup(gz_path: Path) -> VerifyResult:
    """Descomprime y valida un backup ``.db.gz``: integridad + query de humo.

    No lanza por errores de contenido (BD corrupta, gzip inválido): los reporta
    en ``VerifyResult.ok=False`` para que el llamador (drill/test) decida. Sí
    puede propagar errores de I/O del sistema de ficheros.
    """
    name = gz_path.name
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        tmp_db = Path(tmp) / "restored.db"
        try:
            _decompress_to(_materialize_compressed_backup(gz_path, tmp_dir), tmp_db)
        except (OSError, EOFError, gzip.BadGzipFile, zlib.error) as exc:
            return VerifyResult(name, False, "n/a", 0, 0, error=f"descompresión: {exc}")

        try:
            con = sqlite3.connect(str(tmp_db))
            try:
                integrity = str(con.execute("PRAGMA integrity_check").fetchone()[0])
                tablas = int(
                    con.execute(
                        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
                    ).fetchone()[0]
                )
                # Query de humo: la tabla canónica debe existir y ser consultable.
                licitaciones = int(con.execute("SELECT COUNT(*) FROM licitaciones").fetchone()[0])
            finally:
                con.close()
        except sqlite3.DatabaseError as exc:
            return VerifyResult(name, False, "error", 0, 0, error=f"sqlite: {exc}")

        ok = integrity == "ok" and tablas > 0
        return VerifyResult(name, ok, integrity, tablas, licitaciones)


def latest_backup(backup_dir: Path) -> Path | None:
    """El backup ``.db.gz`` más reciente por mtime, o None si no hay."""
    backups = sorted(
        [*backup_dir.glob("*.db.gz"), *backup_dir.glob("*.db.gz.gpg")],
        key=lambda p: p.stat().st_mtime,
    )
    return backups[-1] if backups else None


def restore_backup(gz_path: Path, target: Path, *, backup_current: bool = True) -> Path:
    """Restaura ``gz_path`` sobre ``target``. Devuelve la ruta restaurada.

    Si ``backup_current`` y ``target`` existe, lo preserva como ``<target>.bak``
    (sobrescribiendo un ``.bak`` previo) antes de restaurar — reversible.
    Verifica el backup ANTES de tocar el destino: si no pasa, no restaura.
    """
    result = verify_backup(gz_path)
    if not result.ok:
        raise ValueError(f"backup no válido, no se restaura: {result.as_line()}")

    target.parent.mkdir(parents=True, exist_ok=True)
    if backup_current and target.exists():
        bak = Path(str(target) + ".bak")
        bak.unlink(missing_ok=True)
        target.replace(bak)

    with tempfile.TemporaryDirectory() as tmp:
        source = _materialize_compressed_backup(gz_path, Path(tmp))
        _decompress_to(source, target)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore/verify de backups SQLite")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--verify",
        nargs="?",
        const="",
        metavar="GZ",
        help="Verifica un backup .db.gz (sin argumento: el último local)",
    )
    group.add_argument(
        "--restore", metavar="GZ", help="Restaura un backup .db.gz sobre la BD destino"
    )
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from config import settings

    backup_dir = settings.DATA_DIR / "backups"

    if args.verify is not None:
        gz = Path(args.verify) if args.verify else latest_backup(backup_dir)
        if gz is None:
            print(f"[restore] No hay backups en {backup_dir}", file=sys.stderr)
            return 1
        result = verify_backup(gz)
        print(result.as_line())
        return 0 if result.ok else 1

    # --restore
    gz = Path(args.restore)
    target = settings.DB_PATH or (settings.DATA_DIR / "licitaciones.db")
    try:
        restored = restore_backup(gz, target)
    except (ValueError, OSError) as exc:
        print(f"[restore] ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"[restore] {gz.name} → {restored}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
