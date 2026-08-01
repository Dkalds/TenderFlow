"""v65: lotes como entidad de primera clase.

Revision ID: v65_lotes
Revises: v64_organization_scope
Create Date: 2026-07-31

Postgres-only, en línea con ADR-021.

En contratación pública española un expediente se divide en lotes:
presupuesto, CPV y adjudicatario propios por lote. CODICE modela cada lote
como un ``cac:ProcurementProjectLot`` y cada adjudicación referencia el suyo
vía ``cac:TenderResult/cac:ProcurementProjectLotReference/cbc:ID`` -- el
parser lo ignoraba, y la unique ``(licitacion_id, nif, importe_adjudicado)``
descartaba en silencio una fila cuando la misma empresa ganaba dos lotes por
el mismo importe (ver docs/IMPROVEMENT_BACKLOG.md).

La unique vieja se sustituye por DOS índices únicos parciales en vez de
extenderla con ``lote_id`` sin más: una unique
``(licitacion_id, lote_id, nif, importe_adjudicado)`` simple perdería toda
protección para expedientes sin lote parseado -- ``lote_id`` sería NULL en
todas sus filas, y NULL <> NULL en SQL (mismo razonamiento que
``db/upsert.py::_dedup_adj_rows`` ya documenta para nif/importe), que hoy es
el 100% de los casos existentes. Por eso:

  - ``uq_adjudicaciones_lic_nif_importe_sin_lote`` (WHERE lote_id IS NULL):
    idéntica en efecto a la constraint que sustituye, para el caso sin lote.
  - ``uq_adjudicaciones_lic_lote_nif_importe`` (WHERE lote_id IS NOT NULL):
    protección nueva, por lote, para cuando sí se parsea -- permite que la
    misma empresa gane dos lotes por el mismo importe sin colisionar.

La constraint vieja no tiene nombre fijo en todos los entornos (se creó
inline en ``baseline002_pg_core_genesis``/``db/migrations.py`` según cuál
bootstrapeó cada base), así que se localiza dinámicamente por su conjunto de
columnas antes de borrarla.

Los índices (incluidas las dos unique parciales nuevas) se crean
``CONCURRENTLY`` en la revisión siguiente (v66_lotes_index_concurrent),
mismo patrón que v61->v63: ``autocommit_block`` confirma esta transacción
antes de construirlos sin bloquear escrituras sobre ``adjudicaciones``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "v65_lotes"
down_revision: str | None = "v64_organization_scope"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

_DROP_OLD_ADJ_UNIQUE = """
DO $$
DECLARE
    c_name text;
BEGIN
    SELECT tc.constraint_name INTO c_name
    FROM information_schema.table_constraints tc
    WHERE tc.table_name = 'adjudicaciones'
      AND tc.constraint_type = 'UNIQUE'
      AND tc.constraint_name IN (
          SELECT constraint_name FROM information_schema.key_column_usage
          WHERE table_name = 'adjudicaciones'
          GROUP BY constraint_name
          -- column_name es information_schema.sql_identifier, sin operador
          -- "=" contra text[] sin cast explícito.
          HAVING array_agg(column_name::text ORDER BY column_name)
                 = ARRAY['importe_adjudicado', 'licitacion_id', 'nif']
      )
    LIMIT 1;
    IF c_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE adjudicaciones DROP CONSTRAINT %I', c_name);
    END IF;
END $$;
"""

_RESTORE_OLD_ADJ_UNIQUE = (
    "ALTER TABLE adjudicaciones ADD CONSTRAINT "
    "adjudicaciones_licitacion_id_nif_importe_adjudicado_key "
    "UNIQUE (licitacion_id, nif, importe_adjudicado)"
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _protect_table(table: str) -> None:
    """RLS fail-closed para Data API y acceso explícito del rol runtime."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN "
        f"REVOKE ALL ON TABLE {table} FROM anon; "
        "END IF; "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN "
        f"REVOKE ALL ON TABLE {table} FROM authenticated; "
        "END IF; "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tenderflow_app') THEN "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO tenderflow_app; "
        "IF NOT EXISTS (SELECT 1 FROM pg_policies "
        f"WHERE schemaname = 'public' AND tablename = '{table}' "
        "AND policyname = 'tenderflow_app_full_access') THEN "
        f"CREATE POLICY tenderflow_app_full_access ON {table} "
        "FOR ALL TO tenderflow_app USING (true) WITH CHECK (true); "
        "END IF; END IF; END $$"
    )


def upgrade() -> None:
    if not _is_postgres():
        return

    op.create_table(
        "lotes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "licitacion_id",
            sa.Text,
            sa.ForeignKey("licitaciones.id_externo", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("numero", sa.Text, nullable=False),
        sa.Column("titulo", sa.Text, nullable=True),
        sa.Column("cpv", sa.Text, nullable=True),
        sa.Column("importe", sa.Float, nullable=True),
        sa.Column("fecha_limite", sa.Text, nullable=True),
        sa.Column("fecha_extraccion", sa.Text, nullable=False),
        sa.UniqueConstraint("licitacion_id", "numero", name="uq_lotes_licitacion_numero"),
    )

    # adjudicaciones ya existe y puede ser grande -- ADD COLUMN nullable sin
    # DEFAULT es metadata-only en Postgres (sin rewrite de tabla), igual que
    # las columnas de linaje que v62 añadió a licitaciones.
    op.add_column(
        "adjudicaciones",
        sa.Column(
            "lote_id",
            sa.Integer,
            sa.ForeignKey("lotes.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.execute(_DROP_OLD_ADJ_UNIQUE)

    _protect_table("lotes")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute(_RESTORE_OLD_ADJ_UNIQUE)
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tenderflow_app') THEN "
        "DROP POLICY IF EXISTS tenderflow_app_full_access ON lotes; "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE lotes FROM tenderflow_app; "
        "END IF; END $$"
    )
    op.drop_column("adjudicaciones", "lote_id")
    op.drop_table("lotes")
