"""v122: ``pursuit_tasks`` — la oportunidad pasa a ser un espacio de trabajo (C6.1).

Qué corrige
-----------
Una oportunidad tiene **una** próxima acción, y es texto libre:
``pursuits.next_action`` más ``next_action_due`` (``v83``). Preparar una oferta
no es una acción: son diez, con responsables distintos y fechas distintas —pedir
la clasificación, redactar la memoria técnica, conseguir el aval, firmar el
DEUC—. Lo que hoy hace el equipo es escribir la más urgente en ese campo y
llevar las demás en un hilo de correo o en la cabeza de alguien.

La forma
--------
=========================== ================================================
``pursuit_id``              A qué oportunidad pertenece.
``organization_id``         Denormalizado, como en ``pursuit_events``. No es
                            redundancia decorativa: es lo que permite filtrar
                            la agenda por organización **sin unir con
                            ``pursuits``**, y lo que hace barata la regla de
                            que una tarea de otra organización no se vea.
``titulo``                  Qué hay que hacer.
``responsable_user_id``     Quién. ``NULL`` = sin asignar, que es un estado
                            legítimo y distinto de «asignada a nadie».
``vence``                   ``YYYY-MM-DD`` o ``NULL``. TEXT y no DATE, por
                            coherencia con ``next_action_due`` y con el resto
                            de fechas del esquema.
``estado``                  ``pendiente`` | ``hecha`` | ``cancelada``.
=========================== ================================================

``next_action`` no se retira
----------------------------
Se mantiene, pero **derivado**: pasa a ser la tarea pendiente más próxima a
vencer. Así el tablero, el ICS y la agenda siguen leyendo el mismo campo de
siempre y nadie tiene que actualizarlo a mano — que es justo lo que no ocurría.
Un campo que hay que mantener sincronizado a mano se desincroniza.

Por qué ``cancelada`` y no borrar
---------------------------------
«Ya no hace falta pedir el aval» es información: dice que alguien lo evaluó.
Borrar la fila deja el hueco indistinguible de «nadie se acordó».
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v122_pursuit_tasks"
down_revision: str | Sequence[str] | None = "v121_chunks_version_embedding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("CURRENT_TIMESTAMP")

ESTADOS = ("pendiente", "hecha", "cancelada")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    inspector = sa.inspect(op.get_bind())
    tablas = set(inspector.get_table_names())
    if "pursuit_tasks" in tablas or "pursuits" not in tablas:
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
        sa.Column("vence", sa.Text, nullable=True),
        sa.Column("estado", sa.Text, nullable=False, server_default="pendiente"),
        sa.Column(
            "created_by_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.Text, nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.Text, nullable=False, server_default=_NOW),
    )
    estados = ", ".join(f"'{e}'" for e in ESTADOS)
    op.execute(
        "ALTER TABLE pursuit_tasks ADD CONSTRAINT ck_pursuit_tasks_estado "
        f"CHECK (estado IN ({estados}))"
    )
    # La agenda: «qué vence y en qué orden», acotada a la organización. Parcial
    # sobre `pendiente` porque las hechas y las canceladas no salen nunca en
    # ella y acabarán siendo la mayoría de la tabla.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_pursuit_tasks_agenda "
        "ON pursuit_tasks (organization_id, vence) WHERE estado = 'pendiente'"
    )
    op.create_index("idx_pursuit_tasks_pursuit", "pursuit_tasks", ["pursuit_id"])
    # Para «mis tareas»: sin este índice, filtrar por responsable recorre toda
    # la tabla de la organización.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_pursuit_tasks_responsable "
        "ON pursuit_tasks (responsable_user_id) WHERE responsable_user_id IS NOT NULL"
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP TABLE IF EXISTS pursuit_tasks CASCADE")
