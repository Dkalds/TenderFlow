"""v127: ``pursuit_attachments`` — la propuesta propia deja de vivir fuera (C6.3).

Qué corrige
-----------
El producto guarda **los documentos del órgano** —pliegos, anexos, el binario
que ``v103`` empezó a conservar en el almacén de objetos (S8.1)— y ninguno de
los del equipo. La memoria técnica, el DEUC firmado, el aval, los tres
borradores por los que pasó la oferta: eso vive en un disco de red, en un correo
o en el portátil de quien la escribió. La consecuencia es que la oportunidad
cuenta la mitad de su historia, y que cuando alguien se va, la otra mitad se va
con él.

La forma
--------
=========================== ================================================
``pursuit_id``              A qué oportunidad pertenece.
``organization_id``         Denormalizado como en ``pursuit_tasks`` (``v122``)
                            y por lo mismo: es lo que permite acotar por
                            organización sin unir con ``pursuits``, y lo que
                            hace barata la regla de que un adjunto de otro
                            equipo no se vea nunca.
``blob_key``                Clave en el almacén de objetos. **Única**: el mismo
                            binario subido dos veces no ocupa dos objetos.
``filename``                El nombre que puso quien lo subió, para la descarga.
``content_type``            MIME declarado, ya validado contra la allowlist.
``bytes``                   Tamaño. Se guarda para poder informar del consumo
                            sin ir al bucket fila a fila.
``sha256``                  Huella del contenido. Es lo que hace idempotente
                            volver a subir el mismo fichero.
``indexable``               Opt-in **por adjunto** para que el RAG lo lea.
                            Por defecto ``FALSE``.
=========================== ================================================

Por qué ``indexable`` por defecto en falso
------------------------------------------
Un adjunto propio es dato del equipo, no del expediente público. Indexarlo por
defecto metería la memoria técnica —con precios, márgenes y nombres de
personas— en el contexto que el asistente puede citar, y lo haría sin que nadie
lo hubiera decidido. El opt-in es por fichero y no por organización porque la
decisión no es la misma para el DEUC que para la propuesta económica.

Por qué dato corporativo y no personal
--------------------------------------
El adjunto pertenece a la organización, no a quien lo subió: si esa persona
ejerce su derecho de supresión, el fichero se queda y lo que se anonimiza es
``uploaded_by_user_id`` (``ON DELETE SET NULL``). Lo contrario haría que un baja
del equipo se llevara por delante la oferta que preparó. Queda escrito aquí
porque es la clase de decisión que, sin registrar, alguien invierte más tarde.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v127_pursuit_attachments"
down_revision: str | Sequence[str] | None = "v126_tecnologias_keywords"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    inspector = sa.inspect(op.get_bind())
    tablas = set(inspector.get_table_names())
    if "pursuit_attachments" in tablas or "pursuits" not in tablas:
        return

    op.create_table(
        "pursuit_attachments",
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
        sa.Column("blob_key", sa.Text, nullable=False),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("content_type", sa.Text, nullable=False),
        sa.Column("bytes", sa.Integer, nullable=False),
        sa.Column("sha256", sa.Text, nullable=False),
        sa.Column("indexable", sa.Boolean, nullable=False, server_default=sa.text("FALSE")),
        sa.Column(
            "uploaded_by_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.Text, nullable=False, server_default=_NOW),
    )
    # Idempotencia real: subir dos veces el mismo fichero a la misma
    # oportunidad no crea dos filas ni dos objetos en el bucket. La unicidad va
    # por `(pursuit_id, sha256)` y no por `sha256` a secas porque el mismo
    # modelo de aval puede acompañar a dos ofertas distintas.
    op.create_index(
        "uq_pursuit_attachments_pursuit_sha",
        "pursuit_attachments",
        ["pursuit_id", "sha256"],
        unique=True,
    )
    # El listado de la pestaña Expediente, acotado por organización.
    op.create_index(
        "idx_pursuit_attachments_pursuit",
        "pursuit_attachments",
        ["organization_id", "pursuit_id"],
    )
    # Lo que el RAG puede leer. Parcial porque el opt-in será la minoría.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_pursuit_attachments_indexables "
        "ON pursuit_attachments (pursuit_id) WHERE indexable"
    )
    op.execute(
        "ALTER TABLE pursuit_attachments ADD CONSTRAINT ck_pursuit_attachments_bytes "
        "CHECK (bytes > 0)"
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP TABLE IF EXISTS pursuit_attachments CASCADE")
