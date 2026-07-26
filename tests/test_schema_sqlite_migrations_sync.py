"""Tests de integración de la capa Turso/libSQL.

No requieren credenciales de Turso reales: usamos libsql en modo file (que es la
misma API client) para ejercitar el camino de connect() + migraciones + upsert.
Esto nos da confianza de que el código no rompe la forma de conexión usada en
GitHub Actions, donde se usa Turso remoto.
"""

from __future__ import annotations


def test_connect_and_migrate_on_sqlite_path(tmp_db):
    """init_db completa el esquema sobre una ruta fichero (modo réplica)."""
    db_mod, _tmp_path = tmp_db
    with db_mod.connect() as c:
        tables = {
            r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    assert {
        "licitaciones",
        "adjudicaciones",
        "extraction_runs",
        "failed_extractions",
        "watchlist_cpv",
        "schema_version",
    }.issubset(tables)


def test_upsert_then_readback_preserves_row(tmp_db):
    db_mod, _ = tmp_db
    lic = db_mod.Licitacion(
        id_externo="SYNC-1", titulo="Test Turso", importe=123.45, cpv="72200000"
    )
    nuevas, _ = db_mod.upsert_licitaciones([lic])
    assert nuevas == 1
    with db_mod.connect() as c:
        row = c.execute(
            "SELECT id_externo, titulo, importe, cpv FROM licitaciones WHERE id_externo = ?",
            ("SYNC-1",),
        ).fetchone()
    assert row[0] == "SYNC-1"
    assert row[1] == "Test Turso"
    assert row[2] == 123.45
    assert row[3] == "72200000"


def test_schema_version_tracks_applied_migrations(tmp_db):
    db_mod, _ = tmp_db
    from db.migrations import current_version

    with db_mod.connect() as c:
        assert current_version(c) >= 1


def test_second_init_does_not_duplicate_schema_rows(tmp_db):
    db_mod, _ = tmp_db
    db_mod.init_db()
    db_mod.init_db()
    with db_mod.connect() as c:
        n = c.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    # Debe coincidir con el número de migraciones conocidas
    from db.migrations import MIGRATIONS

    assert n == len(MIGRATIONS)
