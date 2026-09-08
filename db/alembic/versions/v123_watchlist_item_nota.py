"""v123: ``watchlist_items.nota`` — por qué sigo esto (C6.6).

Qué corrige
-----------
Un favorito es un booleano: el expediente está marcado o no. Lo que falta es la
razón —«esperar a que salga el pliego técnico», «preguntar a Marta si tenemos
la clasificación», «ojo: el año pasado quedó desierto»— y hoy vive en un post-it
o no vive.

La regla que no es obvia
------------------------
Un favorito con ``visibility = 'organization'`` lo ve el equipo entero. **La nota
no.** Es de quien la escribió, incluso sobre un favorito compartido: la nota es
el pensamiento de una persona sobre el expediente, no la posición del equipo —
para eso está el hilo de comentarios de la oportunidad, que sí es compartido.

Eso no se resuelve con otra columna de visibilidad sino en la lectura:
``list_items`` proyecta la nota **sólo** para su autor y ``NULL`` para el resto
(``CASE WHEN wi.user_key = %s``). Una columna extra de permisos sería un segundo
sitio donde equivocarse; la proyección lo deja imposible de leer mal.

RGPD
----
Es dato personal del usuario y sale en su export: ``export_items_by_user_key``
hace ``SELECT *``, así que la columna entra sola. Y se va con él:
``anonymize_items_by_user_key`` borra las filas enteras.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v123_watchlist_item_nota"
down_revision: str | Sequence[str] | None = "v122_pursuit_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    inspector = sa.inspect(op.get_bind())
    if "watchlist_items" not in inspector.get_table_names():
        return
    columnas = {c["name"] for c in inspector.get_columns("watchlist_items")}
    if "nota" not in columnas:
        # Sin índice: la nota no se busca ni se ordena, se lee con la fila.
        op.add_column("watchlist_items", sa.Column("nota", sa.Text, nullable=True))


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("ALTER TABLE watchlist_items DROP COLUMN IF EXISTS nota")
