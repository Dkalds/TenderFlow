"""Migración v40 — Resoluciones de recursos contractuales TACRC (Fase 5.3).

Una resolución no es una licitación: vive en su propia tabla
``resoluciones_recurso`` con vinculación débil opcional a ``licitaciones``
(matching por expediente + órgano normalizado, services.resoluciones).
``UNIQUE(tribunal, numero_resolucion)`` hace idempotente la ingesta.

Además amplía el CHECK de ``contrato_eventos.tipo`` con ``'recurso'``: una
resolución estimatoria vinculada genera un evento en la línea de tiempo del
contrato. SQLite no permite alterar un CHECK, así que se reconstruye la tabla
(guard: solo si el CHECK actual no incluye ya 'recurso' — BDs nuevas creadas
desde SCHEMA ya lo traen).

Idempotente (IF NOT EXISTS + guard sobre sqlite_master): db/schema.py crea
las mismas tablas en BDs inicializadas vía init_db().

Revision ID: v40_resoluciones_recurso
Revises: v39_licitaciones_duplicados
Create Date: 2026-06-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "v40_resoluciones_recurso"
down_revision: str | Sequence[str] | None = "v39_licitaciones_duplicados"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENTOS_DDL_NUEVO = """
CREATE TABLE contrato_eventos_new (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    licitacion_id TEXT NOT NULL REFERENCES licitaciones(id_externo) ON DELETE CASCADE,
    tipo          TEXT NOT NULL CHECK(tipo IN
                  ('adjudicacion','formalizacion','modificacion','prorroga',
                   'anulacion','cambio_estado','recurso')),
    fecha         TEXT NOT NULL,
    campo         TEXT,
    valor_antes   TEXT,
    valor_despues TEXT,
    importe_delta REAL,
    detalle       TEXT,
    history_id    INTEGER,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
)
"""


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        # AUTOINCREMENT no es válido en Postgres, y la introspección de
        # sqlite_master usada más abajo tampoco existe ahí. resoluciones_recurso
        # y el CHECK ampliado de contrato_eventos (con 'recurso') los crea
        # v55_pg_v27_v49_tables_backfill (DDL portable, más adelante).
        return
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS resoluciones_recurso (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            tribunal          TEXT NOT NULL DEFAULT 'tacrc',
            numero_resolucion TEXT NOT NULL,
            numero_recurso    TEXT,
            fecha             TEXT,
            expediente        TEXT,
            organo            TEXT,
            sentido           TEXT CHECK(sentido IS NULL OR sentido IN
                              ('estimado','desestimado','inadmitido','desistimiento')),
            url_pdf           TEXT,
            resumen           TEXT,
            licitacion_id     TEXT REFERENCES licitaciones(id_externo),
            fecha_extraccion  TEXT NOT NULL,
            UNIQUE(tribunal, numero_resolucion)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_resoluciones_lic ON resoluciones_recurso(licitacion_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_resoluciones_fecha ON resoluciones_recurso(fecha)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_resoluciones_sentido "
        "ON resoluciones_recurso(sentido, fecha)"
    )

    # Rebuild de contrato_eventos solo si el CHECK aún no admite 'recurso'.
    # En modo offline (alembic --sql) no se puede introspeccionar el CHECK
    # actual; el script se aplica sobre una BD real, así que reconstruimos.
    if not context.is_offline_mode():
        conn = op.get_bind()
        current_ddl = conn.execute(
            sa.text(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'contrato_eventos'"
            )
        ).scalar()
        if not current_ddl or "'recurso'" in current_ddl:
            return
    op.execute(_EVENTOS_DDL_NUEVO)
    op.execute(
        "INSERT INTO contrato_eventos_new "
        "(id, licitacion_id, tipo, fecha, campo, valor_antes, valor_despues, "
        " importe_delta, detalle, history_id, created_at) "
        "SELECT id, licitacion_id, tipo, fecha, campo, valor_antes, valor_despues, "
        "       importe_delta, detalle, history_id, created_at FROM contrato_eventos"
    )
    op.execute("DROP TABLE contrato_eventos")
    op.execute("ALTER TABLE contrato_eventos_new RENAME TO contrato_eventos")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_eventos_lic ON contrato_eventos(licitacion_id, fecha)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_eventos_tipo ON contrato_eventos(tipo, fecha)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_eventos_dedupe "
        "ON contrato_eventos(history_id, tipo, COALESCE(campo, '')) "
        "WHERE history_id IS NOT NULL"
    )


def downgrade() -> None:
    # El CHECK ampliado es backwards-compatible; solo se elimina la tabla nueva.
    op.execute("DROP INDEX IF EXISTS idx_resoluciones_sentido")
    op.execute("DROP INDEX IF EXISTS idx_resoluciones_fecha")
    op.execute("DROP INDEX IF EXISTS idx_resoluciones_lic")
    op.execute("DROP TABLE IF EXISTS resoluciones_recurso")
