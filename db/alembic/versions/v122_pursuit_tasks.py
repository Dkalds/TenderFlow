"""v122: ``pursuit_tasks`` — la oportunidad deja de ser una ficha (C6.1).

Revision ID: v122_pursuit_tasks
Revises: v121_asistente_feedback
Create Date: 2026-09-07

Qué corrige
-----------
Una oportunidad tiene **una** `next_action` con **una** fecha. Preparar una
oferta no es una acción: son cinco o diez, con responsables distintos y plazos
distintos. Con un solo campo, el equipo o se organiza fuera del producto —hoja
de cálculo, chat— o pierde todo menos la siguiente.

`next_action` **no se retira**: pasa a ser una vista derivada («la tarea abierta
más urgente»). Retirarla rompería el tablero, la agenda y el ICS a cambio de
nada, y un campo derivado que coincide con la tabla es más barato de mantener
que dos fuentes que pueden discrepar.

Alcance por organización, no por usuario
----------------------------------------
`organization_id` va desnormalizado (el pursuit ya lo tiene), igual que en
`pursuit_events` y `pursuit_comments`: toda consulta de la agenda se acota por
organización sin pasar por `pursuits`. Sin eso, la agenda de Mi Pipeline —que
lee por organización y ordena por urgencia— tendría que unir tres tablas para
responder «qué me toca hoy».

`responsable_user_id` es `ON DELETE SET NULL`: la tarea sigue siendo trabajo del
equipo cuando quien la tenía asignada se va, y perderla porque alguien borra su
cuenta sería destruir trabajo ajeno — la misma regla de ADR-030 §D.

Timestamps TEXT ISO por coherencia con la familia de pursuits (v61/v83/v97).

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v122_pursuit_tasks"
down_revision: str | Sequence[str] | None = "v121_asistente_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Estados de una tarea. Cerrado a propósito: un estado libre convierte la
#: agenda en un campo de texto que nadie puede ordenar por urgencia.
ESTADOS = ("pendiente", "en_curso", "hecha", "descartada")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _protect_table(table: str) -> None:
    """Cierra Data API y conserva acceso del rol runtime (patrón de v97)."""
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
        f"GRANT USAGE, SELECT ON SEQUENCE {table}_id_seq TO tenderflow_app; "
        f"CREATE POLICY tenderflow_app_full_access ON {table} "
        "FOR ALL TO tenderflow_app USING (true) WITH CHECK (true); "
        "END IF; END $$"
    )


def upgrade() -> None:
    if not _is_postgres():
        return
    if "pursuit_tasks" in set(sa.inspect(op.get_bind()).get_table_names()):
        return

    op.create_table(
        "pursuit_tasks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "pursuit_id",
            sa.Integer,
            sa.ForeignKey("pursuits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            sa.Integer,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("titulo", sa.Text, nullable=False),
        sa.Column(
            "responsable_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Fecha de vencimiento (YYYY-MM-DD). Nullable: una tarea sin fecha es
        # legítima —«revisar el pliego técnico»— y forzarla haría que el equipo
        # inventase fechas para poder crearla, que es peor que no tenerla.
        sa.Column("vence", sa.Text, nullable=True),
        sa.Column("estado", sa.Text, nullable=False, server_default="pendiente"),
        sa.Column("created_at", sa.Text, nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.Text, nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint(
            "char_length(titulo) BETWEEN 1 AND 300",
            name="ck_pursuit_tasks_titulo_length",
        ),
        sa.CheckConstraint(
            "estado IN " + str(ESTADOS),
            name="ck_pursuit_tasks_estado",
        ),
    )
    # La agenda: «qué vence antes en mi organización». Parcial sobre las
    # abiertas porque las hechas son la mayoría con el tiempo y la agenda nunca
    # las mira.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_pursuit_tasks_agenda "
        "ON pursuit_tasks (organization_id, vence) "
        "WHERE estado IN ('pendiente', 'en_curso')"
    )
    op.create_index("idx_pursuit_tasks_pursuit", "pursuit_tasks", ["pursuit_id", "id"])
    op.create_index("idx_pursuit_tasks_responsable", "pursuit_tasks", ["responsable_user_id"])
    _protect_table("pursuit_tasks")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP INDEX IF EXISTS idx_pursuit_tasks_agenda")
    op.execute("DROP INDEX IF EXISTS idx_pursuit_tasks_responsable")
    op.execute("DROP INDEX IF EXISTS idx_pursuit_tasks_pursuit")
    op.execute("DROP TABLE IF EXISTS pursuit_tasks CASCADE")
