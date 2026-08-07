"""Tests para scripts/backup_db.py y scripts/retention_cleanup.py."""

from __future__ import annotations

import gzip
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest


class TestBackupSqlite:
    def test_crea_backup_comprimido(self, tmp_path):
        """backup_sqlite() crea un .db.gz con contenido válido."""
        # Crear una BD de test
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE foo (id INTEGER PRIMARY KEY, val TEXT)")
        conn.execute("INSERT INTO foo VALUES (1, 'hello')")
        conn.commit()
        conn.close()

        backup_dir = tmp_path / "backups"
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from scripts.backup_db import backup_sqlite

        result = backup_sqlite(db_path, backup_dir)

        assert result.exists()
        assert result.suffix == ".gz"
        assert result.stat().st_size > 0

        # Verificar que se puede descomprimir y leer
        with gzip.open(result, "rb") as f:
            data = f.read()
        assert len(data) > 0

    def test_prune_old_backups(self, tmp_path):
        """prune_old_backups() elimina los más antiguos."""
        import time

        from scripts.backup_db import prune_old_backups

        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        # Crear 5 archivos de backup falsos
        files = []
        for i in range(5):
            f = backup_dir / f"licitaciones_200{i}0101_000000.db.gz.gpg"
            f.write_bytes(b"fake")
            time.sleep(0.01)  # Pequeño delay para diferencia en mtime
            files.append(f)

        pruned = prune_old_backups(backup_dir, keep=3)

        assert pruned == 2
        remaining = list(backup_dir.glob("*.db.gz.gpg"))
        assert len(remaining) == 3

    def test_prune_noop_si_pocos_backups(self, tmp_path):
        from scripts.backup_db import prune_old_backups

        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        (backup_dir / "test.db.gz.gpg").write_bytes(b"fake")

        pruned = prune_old_backups(backup_dir, keep=7)
        assert pruned == 0


class TestBackupEncryption:
    def test_refuses_to_leave_a_plaintext_backup_without_a_key(self, tmp_path, monkeypatch):
        from scripts.backup_db import encrypt_backup_file

        backup = tmp_path / "licitaciones.db.gz"
        backup.write_bytes(b"sensitive backup")
        monkeypatch.delenv("BACKUP_ENCRYPTION_KEY", raising=False)

        with pytest.raises(RuntimeError, match="BACKUP_ENCRYPTION_KEY"):
            encrypt_backup_file(backup)
        assert backup.exists()


class TestRetentionCleanup:
    def test_dry_run_no_borra_nada(self, tmp_db):
        """dry_run=False ejecuta pero no aplica — en este caso apply=False."""
        db_mod, _tmp_path = tmp_db

        # Insertar datos de test en extraction_runs
        with db_mod.connect() as c:
            c.execute(
                "INSERT INTO extraction_runs (run_id, started_at, status) VALUES (%s, %s, %s)",
                (f"run-{uuid4()}", "2000-01-01T00:00:00", "ok"),
            )

        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from scripts.retention_cleanup import run_retention

        results = run_retention(
            runs_days=1,
            audit_days=1,
            dlq_days=1,
            history_days=1,
            access_days=1,
            apply=False,
        )

        # En dry-run, marca cuántos borraría pero no los borra
        assert results.get("extraction_runs", 0) >= 1

        # Verificar que el registro sigue existiendo
        with db_mod.connect() as c:
            cur = c.execute(
                "SELECT COUNT(*) FROM extraction_runs WHERE started_at = '2000-01-01T00:00:00'"
            )
            assert cur.fetchone()[0] == 1

    def test_apply_borra_registros_antiguos(self, tmp_db):
        """apply=True elimina registros más antiguos que el umbral."""
        db_mod, _tmp_path = tmp_db

        with db_mod.connect() as c:
            c.execute(
                "INSERT INTO extraction_runs (run_id, started_at, status) VALUES (%s, %s, %s)",
                (f"run-{uuid4()}", "2000-01-01T00:00:00", "ok"),
            )

        from scripts.retention_cleanup import run_retention

        results = run_retention(
            runs_days=1,
            audit_days=1,
            dlq_days=1,
            history_days=1,
            access_days=1,
            apply=True,
        )

        assert results.get("extraction_runs", 0) >= 1

        with db_mod.connect() as c:
            cur = c.execute(
                "SELECT COUNT(*) FROM extraction_runs WHERE started_at = '2000-01-01T00:00:00'"
            )
            assert cur.fetchone()[0] == 0

    def test_apply_no_borra_registros_recientes(self, tmp_db):
        """No purga registros dentro del periodo de retención."""
        from datetime import UTC, datetime

        db_mod, _tmp_path = tmp_db

        recent_ts = datetime.now(UTC).isoformat()
        with db_mod.connect() as c:
            c.execute(
                "INSERT INTO extraction_runs (run_id, started_at, status) VALUES (%s, %s, %s)",
                (f"run-{uuid4()}", recent_ts, "ok"),
            )

        from scripts.retention_cleanup import run_retention

        run_retention(
            runs_days=90,
            audit_days=180,
            dlq_days=30,
            history_days=365,
            access_days=180,
            apply=True,
        )

        with db_mod.connect() as c:
            cur = c.execute(
                "SELECT COUNT(*) FROM extraction_runs WHERE started_at = %s", (recent_ts,)
            )
            assert cur.fetchone()[0] == 1
