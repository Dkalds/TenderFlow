"""v119: el chunk dice de qué modelo es su embedding y de qué página sale (C5.7, C5.3).

Qué corrige
-----------
**C5.7 — Cambiar de modelo de embeddings no tenía camino.**
``EMBEDDING_VERSION`` existe en ``config/settings.py`` desde que se escribió el
retrieval y **no lo lee ningún módulo**: es una variable declarada que nadie
consulta. ``documento_chunks`` guarda el vector y nada más, así que un cambio de
modelo obligaba a elegir entre dos malas opciones: borrar todos los chunks y
quedarse sin retrieval hasta terminar de re-embeber, o mezclar vectores de dos
espacios distintos en la misma consulta ``<=>``, que devuelve un orden sin
significado — dos modelos no comparten geometría, así que la distancia entre un
vector viejo y uno nuevo no mide parecido, mide nada.

Con ``embedding_model`` y ``embedding_version`` en la fila, el retrieval puede
pedir una versión concreta y el job puede re-embeber por lotes mientras la
versión anterior sigue sirviendo.

**C5.3 — Una cita sin página no se puede seguir.**
El asistente recibe fragmentos de pliego y responde en texto libre; para que la
UI pueda enlazar cada afirmación a su sitio hace falta saber en qué página del
documento cae el fragmento. ``documento_pages`` guarda las páginas con su
``start_offset``, y el chunking es determinista sobre el mismo texto, así que la
página se puede calcular al crear el chunk. Se persiste en vez de recalcularse
en cada request: el cálculo necesita el texto completo del documento, que en
serving no está cargado.

Por qué nullable, y sin backfill
--------------------------------
Los chunks ya escritos no saben de qué modelo salieron. Rellenar
``embedding_version`` con la versión de hoy afirmaría algo que no consta —el
mismo error que ``importe_tipo`` evitó en v112 al dejar el histórico en
``desconocido``— y haría que el retrieval filtrase como "vigentes" vectores que
podrían no serlo. Nulo significa "de origen desconocido", y el job de
re-embedding los trata como pendientes.

``page_number`` es nullable por una razón distinta: hay documentos sin páginas
persistidas (extracción antigua, o formatos que no paginan). Un chunk sin página
sigue siendo citable por documento; lo que no puede es enlazar a una página que
no existe.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "v119_documento_chunks_version_pagina"
down_revision: str | Sequence[str] | None = "v118_webhook_deliveries_reintento"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNAS: tuple[tuple[str, type[sa.types.TypeEngine[Any]]], ...] = (
    ("embedding_model", sa.Text),
    ("embedding_version", sa.Text),
    ("page_number", sa.Integer),
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    inspector = sa.inspect(op.get_bind())
    if "documento_chunks" not in inspector.get_table_names():
        return
    existentes = {c["name"] for c in inspector.get_columns("documento_chunks")}
    for nombre, tipo in COLUMNAS:
        if nombre not in existentes:
            op.add_column("documento_chunks", sa.Column(nombre, tipo, nullable=True))

    # El índice del re-embedding: «qué chunks no están en la versión vigente».
    # Parcial sobre las filas con embedding porque las que no lo tienen no son
    # trabajo de este job, y son las únicas que el retrieval ya ignora.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_documento_chunks_version "
        "ON documento_chunks (embedding_version) WHERE embedding IS NOT NULL"
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP INDEX IF EXISTS idx_documento_chunks_version")
    for nombre, _ in COLUMNAS:
        op.execute(f"ALTER TABLE documento_chunks DROP COLUMN IF EXISTS {nombre}")
