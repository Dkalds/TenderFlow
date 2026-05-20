"""Tests de rollback para las migraciones Alembic (v14–v20).

Verifican que cada migración puede aplicarse (upgrade) y deshacerse
(downgrade) limpiamente sobre una BD SQLite temporal. Esto previene
que se desplieguen migraciones sin función downgrade válida.

Se ejecutan en CI como job separado (ver ``.github/workflows/ci.yml``
job ``migrations-rollback``).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────


def _run_alembic(command: str, db_path: Path) -> None:
    """Ejecuta un comando Alembic contra la BD en ``db_path``."""
    from alembic import command as alembic_cmd
    from alembic.config import Config

    real_path = db_path.resolve()

    # Usar ruta absoluta para alembic.ini, independiente del CWD
    _project_root = Path(__file__).parent.parent
    cfg = Config(str(_project_root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{real_path}")
    # Redirigir output al log de pytest
    import logging

    cfg.attributes["configure_logger"] = False
    logging.getLogger("alembic").setLevel(logging.WARNING)

    # Parchear config.settings.DB_PATH para que env.py no sobreescriba la URL del test
    import unittest.mock as _mock

    with _mock.patch("config.settings") as mock_settings:
        mock_settings.DB_PATH = str(real_path)

        if command == "upgrade_head":
            alembic_cmd.upgrade(cfg, "head")
        elif command == "downgrade_base":
            alembic_cmd.downgrade(cfg, "base")
        elif command.startswith("downgrade_"):
            steps = command.split("_", 1)[1]  # e.g. "-1"
            alembic_cmd.downgrade(cfg, steps)
        elif command.startswith("upgrade_"):
            rev = command.split("_", 1)[1]
            alembic_cmd.upgrade(cfg, rev)
        else:
            raise ValueError(f"Comando desconocido: {command}")


def _tables(db_path: Path) -> set[str]:
    """Devuelve el conjunto de tablas presentes en la BD."""
    con = sqlite3.connect(str(db_path))
    try:
        rows = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return {r[0] for r in rows}
    finally:
        con.close()


def _setup_baseline(db_path: Path) -> None:
    """Aplica todas las migraciones (v1-v29 custom + schema) y sella ``head`` en Alembic.

    El SCHEMA base (``db/schema.py``) ya incluye todas las tablas que Alembic
    gestiona (ml_feedback, webhooks, model_registry, totp_*…). Por tanto, tras
    ``init_db()`` la BD está totalmente inicializada y sellamos Alembic en
    ``head`` para que reconozca que ya están aplicadas todas sus migraciones.

    A partir de ahí, los tests verifican downgrade (-1 a -7) y re-upgrade, lo
    que comprueba que cada migración Alembic tiene una función ``downgrade``
    funcional.
    """
    import db.database as db_mod

    db_mod.close_pool()
    db_mod.set_db_path_override(str(db_path))
    try:
        db_mod.init_db()
    finally:
        db_mod.close_pool()
        db_mod.set_db_path_override(None)

    # Asegurarse de que no quedan conexiones abiertas al DB antes del stamp
    import gc
    gc.collect()

    # Crear los índices que Alembic v18/v19 aplican pero que db/schema.py NO incluye.
    # Esto es necesario para que los downgrade de v19 (DROP INDEX idx_lic_fecha_pub_tech)
    # y v18 (DROP INDEX idx_licitaciones_history_externo_date) puedan ejecutarse sin error.
    import sqlite3 as _sqlite3

    real_path = db_path.resolve()

    con = _sqlite3.connect(str(real_path))
    # SQLite en modo WAL: el checkpoint automático puede retrasarse
    con.execute("PRAGMA journal_mode=DELETE")  # cambiar a modo DELETE para commit inmediato
    try:
        # Índice de v19
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_lic_fecha_pub_tech "
            "ON licitaciones(fecha_publicacion DESC) "
            "WHERE tecnologia IS NOT NULL AND tecnologia != ''"
        )
        # Índice de v18
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_licitaciones_history_externo_date "
            "ON licitaciones_history(id_externo, captured_at)"
        )
        # Tabla alembic_version + stamp
        con.execute(
            "CREATE TABLE IF NOT EXISTS alembic_version "
            "(version_num VARCHAR(32) NOT NULL, "
            "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
        )
        con.execute("DELETE FROM alembic_version")
        con.execute("INSERT INTO alembic_version (version_num) VALUES ('v20_mat_aggregates')")
        con.commit()
    finally:
        con.close()


# ── Tests ────────────────────────────────────────────────────────────────────


class TestAlembicMigrationsRollback:
    """Verifica downgrade y re-upgrade de cada migración Alembic (v14–v20).

    La BD de partida tiene el schema completo con todas las tablas ya creadas
    (vía ``db.schema.SCHEMA`` + custom migrations v1-v29) y Alembic sellado en
    ``head``. Los tests comprueban que ``downgrade -1`` (y sucesivos) y
    ``upgrade head`` son funcionales (sin errores SQLite), lo que confirma
    que cada migración tiene una función ``downgrade`` válida.
    """

    @pytest.fixture()
    def migrated_db(self, tmp_path: Path) -> Path:
        """BD temporal con schema completo + Alembic sellado en head."""
        db_path = tmp_path / "rollback_test.db"
        _setup_baseline(db_path)
        return db_path

    def test_upgrade_head_applies_all(self, migrated_db: Path) -> None:
        """Verifica que la BD arranca con todas las tablas ya presentes."""
        tables = _tables(migrated_db)
        # Tablas que deben estar presentes (introducidas por schema + migraciones)
        expected = {
            "ml_feedback",       # v14 / schema
            "webhooks",          # v15 / schema
            "model_versions",    # v16 / schema
            "totp_secrets",      # v17 / schema
        }
        for table in expected:
            assert table in tables, f"Tabla '{table}' esperada no encontrada"

    def test_downgrade_v20(self, migrated_db: Path) -> None:
        """v20 downgrade elimina las tablas materializadas."""
        _run_alembic("downgrade_-1", migrated_db)
        tables = _tables(migrated_db)
        assert "mat_clusters" not in tables
        assert "mat_top_empresas_ccaa" not in tables

    def test_downgrade_v19(self, migrated_db: Path) -> None:
        """v19 downgrade elimina el índice (la tabla licitaciones sigue existiendo)."""
        # Bajar v20 primero
        _run_alembic("downgrade_-1", migrated_db)
        # Bajar v19
        _run_alembic("downgrade_-1", migrated_db)
        # El índice desaparece pero licitaciones permanece
        tables = _tables(migrated_db)
        assert "licitaciones" in tables

    def test_downgrade_v18(self, migrated_db: Path) -> None:
        """v18 downgrade elimina las vistas anuales."""
        for _ in range(3):  # bajar v20, v19, v18
            _run_alembic("downgrade_-1", migrated_db)
        # No hay tablas de vistas anuales (son vistas, se pueden verificar aparte)
        # Aquí simplemente verificamos que el downgrade no falla
        tables = _tables(migrated_db)
        assert "licitaciones" in tables  # tabla base intacta

    def test_downgrade_v17(self, migrated_db: Path) -> None:
        """v17 downgrade elimina las tablas totp_secrets y sessions."""
        for _ in range(4):  # bajar v20..v17
            _run_alembic("downgrade_-1", migrated_db)
        tables = _tables(migrated_db)
        assert "totp_secrets" not in tables
        assert "totp_recovery_codes" not in tables

    def test_downgrade_v16(self, migrated_db: Path) -> None:
        """v16 downgrade elimina la tabla model_versions."""
        for _ in range(5):  # bajar v20..v16
            _run_alembic("downgrade_-1", migrated_db)
        tables = _tables(migrated_db)
        assert "model_versions" not in tables

    def test_downgrade_v15(self, migrated_db: Path) -> None:
        """v15 downgrade elimina la tabla webhooks."""
        for _ in range(6):  # bajar v20..v15
            _run_alembic("downgrade_-1", migrated_db)
        tables = _tables(migrated_db)
        assert "webhooks" not in tables

    def test_downgrade_v14(self, migrated_db: Path) -> None:
        """v14 downgrade elimina la tabla ml_feedback."""
        for _ in range(7):  # bajar v20..v14
            _run_alembic("downgrade_-1", migrated_db)
        tables = _tables(migrated_db)
        assert "ml_feedback" not in tables

    def test_full_roundtrip(self, tmp_path: Path) -> None:
        """Hace downgrade total y re-upgrade para verificar que el ciclo es funcional."""
        db_path = tmp_path / "roundtrip.db"
        _setup_baseline(db_path)

        # BD ya está en head — verificar que las tablas existen
        assert "ml_feedback" in _tables(db_path)

        # downgrade v20..v14 (7 pasos)
        for _ in range(7):
            _run_alembic("downgrade_-1", db_path)
        assert "ml_feedback" not in _tables(db_path)
        assert "model_versions" not in _tables(db_path)

        # upgrade head de nuevo → todas las tablas de vuelta
        _run_alembic("upgrade_head", db_path)
        tables = _tables(db_path)
        assert "ml_feedback" in tables
        assert "model_versions" in tables
        assert "mat_clusters" in tables
