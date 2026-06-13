"""Migración v35 — Maestro de empresas (entity resolution).

Tablas dimensionales para resolver las empresas adjudicatarias a una entidad
canónica: ``empresas`` (NIF canónico + nombre), ``empresa_aliases`` (cada
variante de nombre/NIF vista en la fuente), ``grupos_empresariales``
(matriz-filial), ``ute_miembros`` (composición de UTEs) y
``empresa_review_queue`` (cola de revisión humana para matches fuzzy).

Añade ``adjudicaciones.empresa_id`` (FK nullable durante la transición).
El enlace de filas lo hace services.entity_resolution, no la migración.

Idempotente a propósito: ``db/schema.py`` (SCHEMA) crea estas mismas tablas
en BDs inicializadas vía ``init_db()``, así que esta migración debe poder
aplicarse después sin colisionar (mismo problema que rompía el roundtrip
de v34 con ``job_locks``). DDL con IF NOT EXISTS + guard PRAGMA en el ALTER.

Revision ID: v35_empresa_master
Revises: v34_job_locks
Create Date: 2026-06-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import context, op

revision: str = "v35_empresa_master"
down_revision: str | Sequence[str] | None = "v34_job_locks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DDL = """
CREATE TABLE IF NOT EXISTS grupos_empresariales (
    grupo_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre      TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS empresas (
    empresa_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nif_canonico    TEXT,
    nombre_canonico TEXT NOT NULL,
    es_ute          INTEGER NOT NULL DEFAULT 0,
    es_pyme         INTEGER,
    grupo_id        INTEGER REFERENCES grupos_empresariales(grupo_id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_empresas_nif ON empresas(nif_canonico)
    WHERE nif_canonico IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_empresas_grupo ON empresas(grupo_id);
CREATE TABLE IF NOT EXISTS empresa_aliases (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    empresa_id        INTEGER NOT NULL REFERENCES empresas(empresa_id) ON DELETE CASCADE,
    alias_normalizado TEXT NOT NULL,
    nif_variante      TEXT,
    fuente            TEXT NOT NULL DEFAULT '',
    confianza         REAL NOT NULL DEFAULT 1.0,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_empresa_aliases_alias ON empresa_aliases(alias_normalizado);
CREATE INDEX IF NOT EXISTS idx_empresa_aliases_nif   ON empresa_aliases(nif_variante);
CREATE UNIQUE INDEX IF NOT EXISTS idx_empresa_aliases_uniq
    ON empresa_aliases(empresa_id, alias_normalizado, COALESCE(nif_variante, ''));
CREATE TABLE IF NOT EXISTS ute_miembros (
    ute_empresa_id     INTEGER NOT NULL REFERENCES empresas(empresa_id) ON DELETE CASCADE,
    miembro_empresa_id INTEGER NOT NULL REFERENCES empresas(empresa_id) ON DELETE CASCADE,
    PRIMARY KEY (ute_empresa_id, miembro_empresa_id)
);
CREATE TABLE IF NOT EXISTS empresa_review_queue (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_original      TEXT NOT NULL,
    alias_normalizado    TEXT NOT NULL,
    nif                  TEXT,
    candidato_empresa_id INTEGER REFERENCES empresas(empresa_id) ON DELETE CASCADE,
    score                REAL NOT NULL,
    status               TEXT NOT NULL DEFAULT 'pending'
                         CHECK(status IN ('pending','accepted','rejected')),
    created_at           TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at          TEXT,
    resolved_by          TEXT
);
CREATE INDEX IF NOT EXISTS idx_empresa_review_status ON empresa_review_queue(status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_empresa_review_pending
    ON empresa_review_queue(alias_normalizado, COALESCE(nif, ''), candidato_empresa_id)
    WHERE status = 'pending';
"""


def upgrade() -> None:
    for stmt in _DDL.split(";"):
        if stmt.strip():
            op.execute(stmt)

    if context.is_offline_mode():
        # En modo offline (alembic --sql) no se puede introspeccionar la BD;
        # el script se aplica sobre una BD real con adjudicaciones ya presente
        # (v1-v13 creadas por el sistema casero), así que emitimos el DDL.
        op.execute(
            "ALTER TABLE adjudicaciones ADD COLUMN empresa_id INTEGER "
            "REFERENCES empresas(empresa_id)"
        )
        op.execute("CREATE INDEX IF NOT EXISTS idx_adj_empresa ON adjudicaciones(empresa_id)")
        return

    bind = op.get_bind()
    # adjudicaciones puede no existir (BD alembic-only sin baseline aplicado)
    # o ya tener la columna (BD inicializada vía init_db con SCHEMA actual).
    table_exists = bind.exec_driver_sql(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='adjudicaciones'"
    ).fetchone()
    if table_exists:
        cols = {
            row[1] for row in bind.exec_driver_sql("PRAGMA table_info(adjudicaciones)").fetchall()
        }
        if "empresa_id" not in cols:
            op.execute(
                "ALTER TABLE adjudicaciones ADD COLUMN empresa_id INTEGER "
                "REFERENCES empresas(empresa_id)"
            )
        op.execute("CREATE INDEX IF NOT EXISTS idx_adj_empresa ON adjudicaciones(empresa_id)")


def downgrade() -> None:
    # adjudicaciones.empresa_id no se elimina (ADD COLUMN irreversible en
    # SQLite < 3.35); queda huérfana pero inocua.
    op.execute("DROP INDEX IF EXISTS idx_adj_empresa")
    op.execute("DROP INDEX IF EXISTS idx_empresa_review_pending")
    op.execute("DROP INDEX IF EXISTS idx_empresa_review_status")
    op.execute("DROP TABLE IF EXISTS empresa_review_queue")
    op.execute("DROP TABLE IF EXISTS ute_miembros")
    op.execute("DROP INDEX IF EXISTS idx_empresa_aliases_uniq")
    op.execute("DROP INDEX IF EXISTS idx_empresa_aliases_nif")
    op.execute("DROP INDEX IF EXISTS idx_empresa_aliases_alias")
    op.execute("DROP TABLE IF EXISTS empresa_aliases")
    op.execute("DROP INDEX IF EXISTS idx_empresas_grupo")
    op.execute("DROP INDEX IF EXISTS idx_empresas_nif")
    op.execute("DROP TABLE IF EXISTS empresas")
    op.execute("DROP TABLE IF EXISTS grupos_empresariales")
