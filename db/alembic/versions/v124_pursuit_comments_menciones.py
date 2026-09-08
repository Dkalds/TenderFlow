"""v124: ``pursuit_comments.mentions_json`` — a quién iba dirigido (C6.2).

Qué guarda
----------
Los ``user_id`` mencionados en el comentario, como lista JSON. **Los ids, no el
texto resuelto**: si mañana alguien cambia su nombre visible, la mención sigue
apuntando a la misma persona. Guardar «@Ana Pérez» ya resuelto convierte el hilo
en un registro de nombres viejos, y encima obliga a re-resolverlo para saber a
quién notificar.

Por qué en la fila y no en una tabla puente
-------------------------------------------
Una mención no se consulta al revés. Nadie pregunta «¿en qué comentarios me han
mencionado?» contra esta tabla: eso lo responde el outbox
(``domain_events``, eventos ``pursuit.mentioned``), que es donde vive la
notificación y su estado. Aquí sólo hace falta pintar el comentario resaltando a
quien se mencionó, y para eso la lista viaja con la fila que ya se está leyendo.

Una tabla puente añadiría un JOIN a la consulta del hilo —la más caliente del
espacio de trabajo— a cambio de una consulta inversa que no existe.

``NULL`` frente a ``[]``
------------------------
``NULL`` son los comentarios anteriores a esta revisión: no se sabe si tenían
menciones porque nadie las buscó. ``[]`` es «se buscaron y no había». La
diferencia importa el día que alguien quiera reprocesar el histórico.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v124_pursuit_comments_menciones"
down_revision: str | Sequence[str] | None = "v123_watchlist_item_nota"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    inspector = sa.inspect(op.get_bind())
    if "pursuit_comments" not in inspector.get_table_names():
        return
    columnas = {c["name"] for c in inspector.get_columns("pursuit_comments")}
    if "mentions_json" not in columnas:
        # Sin índice: la lista se lee con la fila del hilo, nunca se filtra por
        # ella (ver el docstring).
        op.add_column("pursuit_comments", sa.Column("mentions_json", sa.Text, nullable=True))


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("ALTER TABLE pursuit_comments DROP COLUMN IF EXISTS mentions_json")
