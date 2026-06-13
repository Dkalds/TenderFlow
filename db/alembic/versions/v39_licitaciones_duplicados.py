"""Migración v39 — Dedupe cross-fuente de licitaciones (Fase 5.2).

Marca filas duplicadas entre fuentes (PLACSP↔PSCP↔TED) apuntando a su fila
canónica, sin merge físico: las consultas analíticas excluyen las marcadas
como ``confirmed`` (services.dedupe.exclude_duplicados_sql). Los matches de
confianza < 1.0 quedan ``pending`` para revisión humana en la propia tabla.

Idempotente (IF NOT EXISTS): db/schema.py crea la misma tabla en BDs
inicializadas vía init_db().

Revision ID: v39_licitaciones_duplicados
Revises: v38_contrato_eventos
Create Date: 2026-06-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v39_licitaciones_duplicados"
down_revision: str | Sequence[str] | None = "v38_contrato_eventos"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS licitaciones_duplicados (
            licitacion_id TEXT PRIMARY KEY
                          REFERENCES licitaciones(id_externo) ON DELETE CASCADE,
            canonical_id  TEXT NOT NULL
                          REFERENCES licitaciones(id_externo) ON DELETE CASCADE,
            clave_match   TEXT,
            confianza     REAL NOT NULL DEFAULT 1.0,
            status        TEXT NOT NULL DEFAULT 'confirmed'
                          CHECK(status IN ('confirmed','pending','rejected')),
            detectado_en  TEXT NOT NULL DEFAULT (datetime('now')),
            resolved_at   TEXT,
            resolved_by   TEXT
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_lic_dup_canonical "
        "ON licitaciones_duplicados(canonical_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_lic_dup_status ON licitaciones_duplicados(status)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_lic_dup_status")
    op.execute("DROP INDEX IF EXISTS idx_lic_dup_canonical")
    op.execute("DROP TABLE IF EXISTS licitaciones_duplicados")
