"""Restore drill: prueba que un backup SQLite restaura a una BD consultable.

Un backup que nadie restaura no es un backup. Estos tests ejercitan el ciclo
completo backup → verify → restore con ``scripts/backup_db.py`` +
``scripts/restore_db.py``, y comprueban que la verificación detecta backups
corruptos (no da falso verde).
"""

from __future__ import annotations

import gzip
import sqlite3
from pathlib import Path

import pytest

from scripts.backup_db import backup_sqlite
from scripts.restore_db import latest_backup, restore_backup, verify_backup


def _make_db(path: Path, n_rows: int = 3) -> None:
    con = sqlite3.connect(str(path))
    try:
        con.execute("CREATE TABLE licitaciones (id_externo TEXT PRIMARY KEY, titulo TEXT)")
        con.executemany(
            "INSERT INTO licitaciones (id_externo, titulo) VALUES (?, ?)",
            [(f"placsp:{i}", f"Licitación {i}") for i in range(n_rows)],
        )
        con.commit()
    finally:
        con.close()


def test_backup_verify_roundtrip(tmp_path: Path) -> None:
    src = tmp_path / "source.db"
    _make_db(src, n_rows=5)
    backup_dir = tmp_path / "backups"

    gz = backup_sqlite(src, backup_dir)
    assert gz.exists()
    assert gz.suffix == ".gz"

    result = verify_backup(gz)
    assert result.ok, result.as_line()
    assert result.integrity == "ok"
    assert result.tablas >= 1
    assert result.licitaciones == 5


def test_restore_produces_queryable_db(tmp_path: Path) -> None:
    src = tmp_path / "source.db"
    _make_db(src, n_rows=4)
    backup_dir = tmp_path / "backups"
    gz = backup_sqlite(src, backup_dir)

    target = tmp_path / "restored" / "licitaciones.db"
    restore_backup(gz, target, backup_current=False)

    assert target.exists()
    con = sqlite3.connect(str(target))
    try:
        rows = con.execute("SELECT COUNT(*) FROM licitaciones").fetchone()[0]
    finally:
        con.close()
    assert rows == 4


def test_restore_preserves_current_as_bak(tmp_path: Path) -> None:
    src = tmp_path / "source.db"
    _make_db(src, n_rows=2)
    gz = backup_sqlite(src, tmp_path / "backups")

    target = tmp_path / "licitaciones.db"
    target.write_bytes(b"old contents")

    restore_backup(gz, target, backup_current=True)

    bak = Path(str(target) + ".bak")
    assert bak.exists()
    assert bak.read_bytes() == b"old contents"


def test_verify_detects_corrupt_backup(tmp_path: Path) -> None:
    bad = tmp_path / "corrupt.db.gz"
    with gzip.open(bad, "wb") as f:
        f.write(b"this is not a valid sqlite database file")

    result = verify_backup(bad)
    assert not result.ok
    assert result.error is not None


def test_verify_detects_truncated_gzip(tmp_path: Path) -> None:
    bad = tmp_path / "truncated.db.gz"
    bad.write_bytes(b"\x1f\x8b\x08\x00 not really gzip")

    result = verify_backup(bad)
    assert not result.ok
    assert result.error is not None


def test_restore_refuses_invalid_backup(tmp_path: Path) -> None:
    bad = tmp_path / "corrupt.db.gz"
    with gzip.open(bad, "wb") as f:
        f.write(b"garbage")
    target = tmp_path / "licitaciones.db"

    with pytest.raises(ValueError, match="no válido"):
        restore_backup(bad, target)
    assert not target.exists()


def test_latest_backup_picks_newest(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    # Dos backups con mtime distinto (el timestamp del nombre tiene
    # granularidad de segundos, así que se fija el mtime explícitamente).
    import os

    first = backup_dir / "licitaciones_20260101_000000.db.gz.gpg"
    second = backup_dir / "licitaciones_20260102_000000.db.gz.gpg"
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    os.utime(first, (1_000_000, 1_000_000))
    os.utime(second, (2_000_000, 2_000_000))

    assert latest_backup(backup_dir) == second
