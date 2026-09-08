"""v126: ``tecnologias_keywords`` — el diccionario deja de ser un deploy (C5.6, D28).

Qué corrige
-----------
El diccionario de tecnologías vive en ``config/keywords.py``. Añadir una keyword
—«nos hemos dado cuenta de que Workday también aparece como *hcm cloud*»— es un
PR, una revisión, un merge y un despliegue. Mientras tanto, los expedientes que
la llevan entran al corpus sin etiqueta y nadie los ve.

Peor: como el filtro decide qué se **persiste** en varias fuentes (PSCP,
Euskadi, los RSS), una keyword que falta no es una etiqueta que falta, es un
expediente que no está.

La forma
--------
Una fila por ``(tecnologia, keyword)``. Sin listas JSON: una tabla de filas
permite activar y desactivar una keyword suelta, saber cuándo entró y quién la
puso, y contar cuántos expedientes trajo. Un JSON con la lista entera obliga a
reescribirla para cambiar una palabra, y el histórico se pierde.

``activa`` en vez de borrar
---------------------------
Una keyword retirada explica el pasado: los expedientes que entraron por ella
siguen ahí, y su ``filter_version`` apunta a un diccionario que la incluía.
Borrar la fila deja esas filas sin explicación.

El único es sobre ``lower(keyword)``
------------------------------------
«SAP» y «sap» son la misma keyword —el filtro es insensible a mayúsculas— y
tenerlas dos veces sólo duplicaría trabajo en el regex.

La semilla sigue siendo código
------------------------------
``config/keywords.py`` no se retira: es la semilla con la que arranca una
instalación limpia y el respaldo si la tabla no se puede leer. Un diccionario
vacío no es «no filtres nada»: es «no persistas nada», y esa no puede ser la
respuesta a un fallo de base de datos.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v126_tecnologias_keywords"
down_revision: str | Sequence[str] | None = "v125_pursuit_gonogo"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    if "tecnologias_keywords" in set(sa.inspect(op.get_bind()).get_table_names()):
        return

    op.create_table(
        "tecnologias_keywords",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tecnologia", sa.Text, nullable=False),
        sa.Column("keyword", sa.Text, nullable=False),
        sa.Column("activa", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_by_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.Text, nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.Text, nullable=False, server_default=_NOW),
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_tecnologias_keywords_uniq "
        "ON tecnologias_keywords (tecnologia, lower(keyword))"
    )
    # La carga del diccionario pide las activas agrupadas por tecnología, y es
    # una consulta caliente: la hace el arranque de cada worker de ingesta.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tecnologias_keywords_activas "
        "ON tecnologias_keywords (tecnologia) WHERE activa"
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP TABLE IF EXISTS tecnologias_keywords CASCADE")
