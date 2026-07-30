"""v62: linaje analítico, páginas/ficha del pliego y SLA por fuente.

Revision ID: v62_product_truth_and_tender_facts
Revises: v61_organizations_pursuits
Create Date: 2026-07-30

Postgres-only, en línea con ADR-021.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "v62_product_truth_and_tender_facts"
down_revision: str | None = "v61_organizations_pursuits"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _protect_table(table: str) -> None:
    """RLS deny-all para Data API; acceso explícito del rol runtime."""
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
        f"IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='public' "
        f"AND tablename='{table}' AND policyname='tenderflow_app_full_access') THEN "
        f"CREATE POLICY tenderflow_app_full_access ON {table} "
        "FOR ALL TO tenderflow_app USING (true) WITH CHECK (true); "
        "END IF; "
        "END IF; END $$"
    )


def upgrade() -> None:
    if not _is_postgres():
        return

    # Columnas nullable: metadatos aditivos, sin rewrite/default sobre la tabla
    # grande. Filas históricas nulas se muestran explícitamente como pre-linaje.
    for name in (
        "filter_version",
        "classifier_model_version",
        "inclusion_reason",
        "analysis_universe",
    ):
        op.add_column("licitaciones", sa.Column(name, sa.Text, nullable=True))

    op.create_table(
        "documento_pages",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "documento_id",
            sa.Integer,
            sa.ForeignKey("documentos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_number", sa.Integer, nullable=False),
        sa.Column("texto", sa.Text, nullable=False),
        sa.Column("start_offset", sa.Integer, nullable=False),
        sa.Column("end_offset", sa.Integer, nullable=False),
        sa.CheckConstraint("page_number > 0", name="ck_documento_pages_number"),
        sa.CheckConstraint(
            "start_offset >= 0 AND end_offset >= start_offset",
            name="ck_documento_pages_offsets",
        ),
        sa.UniqueConstraint(
            "documento_id",
            "page_number",
            name="uq_documento_pages_document_page",
        ),
    )
    op.create_table(
        "tender_fact_sheets",
        sa.Column(
            "licitacion_id",
            sa.Text,
            sa.ForeignKey("licitaciones.id_externo", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("extraction_version", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=True),
        sa.Column("data_json", sa.Text, nullable=True),
        sa.Column("field_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("evidence_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_detail", sa.Text, nullable=True),
        sa.Column("extracted_at", sa.Text, nullable=True),
        sa.Column("updated_at", sa.Text, nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint(
            "status IN ('pending','extracted','needs_review','failed')",
            name="ck_tender_fact_sheets_status",
        ),
        sa.CheckConstraint(
            "field_count >= 0 AND evidence_count >= 0",
            name="ck_tender_fact_sheets_counts",
        ),
    )
    op.create_table(
        "source_ingestion_health",
        sa.Column("source", sa.Text, primary_key=True),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("last_started_at", sa.Text, nullable=True),
        sa.Column("last_completed_at", sa.Text, nullable=True),
        sa.Column("last_success_at", sa.Text, nullable=True),
        sa.Column("fetched", sa.Integer, nullable=False, server_default="0"),
        sa.Column("parsed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("discarded", sa.Integer, nullable=False, server_default="0"),
        sa.Column("errors", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cursor_value", sa.Text, nullable=True),
        sa.Column("updated_at", sa.Text, nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint(
            "status IN ('running','success','partial','failed')",
            name="ck_source_ingestion_health_status",
        ),
    )

    # Las tablas están vacías al crearse; los índices no escanean datos
    # históricos ni bloquean escrituras existentes.
    op.create_index(
        "idx_documento_pages_document",
        "documento_pages",
        ["documento_id", "page_number"],
    )
    op.create_index(
        "idx_tender_fact_sheets_status",
        "tender_fact_sheets",
        ["status", "updated_at"],
    )
    for table in (
        "documento_pages",
        "tender_fact_sheets",
        "source_ingestion_health",
    ):
        _protect_table(table)

    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tenderflow_app') THEN "
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO tenderflow_app; "
        "END IF; END $$"
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.drop_table("source_ingestion_health")
    op.drop_table("tender_fact_sheets")
    op.drop_table("documento_pages")
    for name in (
        "analysis_universe",
        "inclusion_reason",
        "classifier_model_version",
        "filter_version",
    ):
        op.drop_column("licitaciones", name)
