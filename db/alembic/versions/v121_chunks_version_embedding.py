"""v121: ``documento_chunks`` dice con qué modelo se embebió (C5.7).

Qué corrige
-----------
``EMBEDDING_VERSION`` está declarada en ``config/settings.py`` desde que existe
el RAG, con un comentario que promete «si cambia, se re-embebe», y **no la lee
nadie**: cero coincidencias en todo el repo fuera de su propia declaración. La
promesa no la cumplía ningún código.

La consecuencia no es cosmética. Los embeddings viven en ``documento_chunks`` y
no llevan ninguna marca de con qué modelo se calcularon. Cambiar
``EMBEDDING_MODEL`` deja la tabla con vectores de dos espacios distintos
mezclados, y ``search_chunks_by_embedding`` los ordena a todos con el mismo
``<=>``: las distancias entre espacios no significan nada, así que el retrieval
devuelve fragmentos plausibles y equivocados. Sin columna no hay forma de
detectarlo ni de re-embeber sólo lo que hace falta.

Columnas nuevas
---------------
================== =========================================================
``embedding_model``  El nombre del modelo (``EMBEDDING_MODEL``). Es lo que
                     define el espacio vectorial.
``embedding_version`` La versión lógica (``EMBEDDING_VERSION``). Permite
                     forzar un re-embebido sin cambiar de modelo — por
                     ejemplo si cambia el chunking o la normalización, que
                     también mueven los vectores.
================== =========================================================

Ambas nullable: las filas existentes se embebieron antes de que hubiera
etiqueta, y **no se rellenan a ciegas**. Poner el modelo actual en filas
históricas sería afirmar algo que nadie comprobó; ``NULL`` significa «no
consta», que es la verdad. El job de re-embebido las trata como pendientes.

Índice
------
Parcial sobre las filas que **no** están en la versión corriente, que es la
única consulta que esta columna habilita: «¿qué queda por re-embeber?». Un
índice completo sobre una columna con dos valores distintos no serviría de nada.
El literal de la versión no puede ir en un índice parcial (cambia con la
configuración), así que el índice cubre el par y la consulta filtra.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v121_chunks_version_embedding"
down_revision: str | Sequence[str] | None = "v120_asistente_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNAS = ("embedding_model", "embedding_version")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return

    inspector = sa.inspect(op.get_bind())
    if "documento_chunks" not in inspector.get_table_names():
        return
    existentes = {c["name"] for c in inspector.get_columns("documento_chunks")}

    for nombre in COLUMNAS:
        if nombre not in existentes:
            op.add_column("documento_chunks", sa.Column(nombre, sa.Text, nullable=True))

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_documento_chunks_embedding_version "
        "ON documento_chunks (embedding_model, embedding_version)"
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP INDEX IF EXISTS idx_documento_chunks_embedding_version")
    for nombre in COLUMNAS:
        op.execute(f"ALTER TABLE documento_chunks DROP COLUMN IF EXISTS {nombre}")
