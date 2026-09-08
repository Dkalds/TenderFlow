"""v124: nota en el favorito y menciones del comentario (C6.6, C6.2).

Revision ID: v124_notas_y_menciones
Revises: v123_go_no_go
Create Date: 2026-09-07

**C6.6 — `watchlist_items.nota`.** Un favorito guarda «me interesa» y nada más.
El motivo —«esperar al pliego técnico», «preguntar a Marta si tenemos perfil»—
vive fuera del producto o se pierde. La nota es **personal**: la fila ya está
acotada por `user_key`, así que dos personas de la misma organización que sigan
el mismo expediente tienen cada una la suya, y la de una nunca se le enseña a la
otra aunque el favorito esté compartido a nivel de organización.

Entra en el export RGPD por lo mismo que es personal: es texto que escribió esa
persona sobre su propio trabajo.

**C6.2 — `pursuit_comment_mentions`.** El comentario guarda su texto; una
mención necesita saber **a quién** se refiere para poder notificar y para que la
UI la enlace. Guardar el nombre resuelto dentro del texto sería congelarlo: la
persona cambia su `display_name` y el comentario queda mencionando a alguien que
ya no se llama así, sin forma de saber a quién apuntaba.

Tabla aparte y no una columna con ids: una mención tiene cardinalidad (varias
por comentario), se consulta al revés («¿en qué me han mencionado?») y se borra
con la persona. `ON DELETE CASCADE` sobre `users` y no `SET NULL`: una mención a
una cuenta borrada no es información, es una fila huérfana.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v124_notas_y_menciones"
down_revision: str | Sequence[str] | None = "v123_go_no_go"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _protect_table(table: str) -> None:
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
    inspector = sa.inspect(op.get_bind())
    tablas = set(inspector.get_table_names())

    if "watchlist_items" in tablas:
        columnas = {c["name"] for c in inspector.get_columns("watchlist_items")}
        if "nota" not in columnas:
            op.add_column("watchlist_items", sa.Column("nota", sa.Text, nullable=True))
            op.execute(
                "ALTER TABLE watchlist_items ADD CONSTRAINT ck_watchlist_items_nota_length "
                "CHECK (nota IS NULL OR char_length(nota) <= 2000)"
            )

    if "pursuit_comment_mentions" not in tablas and "pursuit_comments" in tablas:
        op.create_table(
            "pursuit_comment_mentions",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column(
                "comment_id",
                sa.Integer,
                sa.ForeignKey("pursuit_comments.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                sa.Integer,
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("created_at", sa.Text, nullable=False, server_default=sa.text("NOW()")),
        )
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_pursuit_comment_mentions "
            "ON pursuit_comment_mentions(comment_id, user_id)"
        )
        # «¿En qué me han mencionado?» es la consulta del destinatario.
        op.create_index(
            "idx_pursuit_comment_mentions_user", "pursuit_comment_mentions", ["user_id", "id"]
        )
        _protect_table("pursuit_comment_mentions")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP TABLE IF EXISTS pursuit_comment_mentions CASCADE")
    op.execute(
        "ALTER TABLE watchlist_items DROP CONSTRAINT IF EXISTS ck_watchlist_items_nota_length"
    )
    op.execute("ALTER TABLE watchlist_items DROP COLUMN IF EXISTS nota")
