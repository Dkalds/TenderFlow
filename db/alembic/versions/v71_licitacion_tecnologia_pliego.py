"""v71: tabla ``licitacion_tecnologia_pliego`` (señal de tecnología por pliego).

Revision ID: v71_licitacion_tecnologia_pliego
Revises: v70_pg_missing_lic_fuente_index
Create Date: 2026-08-04

Plan "categorización alimentada por los pliegos": la señal de tecnología
detectada en el texto de los pliegos (keywords o LLM) vive en tabla propia,
separada de ``licitacion_tecnologia_score`` (que ``precompute_ml_tecnologias``
sobreescribe en cada corrida). El merge hacia ``ml_tecnologias`` y
``licitacion_tecnologia_score`` es un paso aparte (``services/tech_signal.py``)
que se re-aplica después de cada precompute, así que esta tabla sobrevive al
clobber de ``db/upsert.py`` en cada re-scrape.

PK compuesta ``(licitacion_id, tecnologia, method)``: keywords y LLM pueden
coexistir para la misma tecnología sin pisarse -- el merge toma el máximo.

Postgres-only, en línea con ADR-021.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "v71_licitacion_tecnologia_pliego"
down_revision: str | None = "v70_pg_missing_lic_fuente_index"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _protect_table(table: str) -> None:
    """RLS deny-all para Data API; acceso explícito del rol runtime.

    Mismo patrón que v62 (``_protect_table``) -- no se importa entre módulos
    de migración porque cada revisión alembic debe poder aplicarse de forma
    aislada y las migraciones son append-only.
    """
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

    op.create_table(
        "licitacion_tecnologia_pliego",
        sa.Column(
            "licitacion_id",
            sa.Text,
            sa.ForeignKey("licitaciones.id_externo", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tecnologia", sa.Text, nullable=False),
        sa.Column("method", sa.Text, nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("matched_terms", sa.Text, nullable=True),
        sa.Column("evidence_json", sa.Text, nullable=True),
        sa.Column("signal_version", sa.Text, nullable=False),
        sa.Column("computed_at", sa.Text, nullable=False),
        sa.Column("merged_at", sa.Text, nullable=True),
        sa.PrimaryKeyConstraint(
            "licitacion_id", "tecnologia", "method", name="pk_licitacion_tecnologia_pliego"
        ),
        sa.CheckConstraint("method IN ('keywords','llm')", name="ck_lic_tec_pliego_method"),
        sa.CheckConstraint(
            "score >= 0 AND score <= 1", name="ck_lic_tec_pliego_score_range"
        ),
    )
    # Sin índice adicional: la PK (licitacion_id, tecnologia, method) ya cubre
    # el lookup por licitación del endpoint de detalle (prefijo licitacion_id),
    # y la cola de merge (list_signals_for_merge) filtra por score, no por
    # merged_at -- el merge se re-aplica entero en cada corrida nightly, no
    # solo sobre lo "pendiente" (ver services/tech_signal.py::merge_doc_signals).
    _protect_table("licitacion_tecnologia_pliego")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.drop_table("licitacion_tecnologia_pliego")
