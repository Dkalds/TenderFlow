"""v127: ``pursuit_attachments`` — adjuntos propios de la oportunidad (C6.3).

Revision ID: v127_pursuit_attachments
Revises: v126_tecnologias_keywords
Create Date: 2026-09-08

Qué corrige
-----------
La pestaña Expediente enseñaba los documentos **del pliego** —lo que publica el
órgano— y nada de lo que el equipo escribe para responderlo. La propuesta, sus
borradores y el modelo de oferta vivían en el disco de alguien o en un chat, de
modo que el producto sabía qué se pedía y no sabía qué se entregó.

Este ítem estuvo bloqueado hasta ahora porque exigía el almacén de objetos de
v2 S8.1 (`shared/object_store.py`), que llegó a `master` con #274.

El binario NO vive aquí
-----------------------
La fila guarda metadatos y la **clave** del objeto; los bytes van al almacén.
Meter el fichero en la columna habría convertido cada backup de la base en una
copia del bucket, y `pg_dump` en algo que nadie ejecuta.

`blob_key` es única: dos adjuntos no pueden apuntar al mismo objeto, porque
entonces borrar uno dejaría al otro sin bytes. La clave incorpora el `sha256`,
así que subir dos veces el mismo fichero a la misma oportunidad choca contra la
unicidad en vez de duplicar el objeto — y el servicio lo traduce a un 409.

`organization_id` desnormalizado, igual que en `pursuit_tasks` (v122) y
`pursuit_comments`: el listado y el borrado se acotan por organización sin pasar
por `pursuits`. Es también lo que hace que el adjunto sea **dato corporativo** a
efectos del GDPR: acompaña a la organización, no a quien lo subió, y por eso
`uploaded_by_user_id` es `ON DELETE SET NULL` (regla de ADR-030 §D: quien se va
no se lleva el trabajo del equipo).

`indexable` nace en `false`
---------------------------
El criterio de C6.3 es que **el RAG no indexe adjuntos propios salvo opt-in por
adjunto**. La columna existe para que ese opt-in tenga dónde vivir, y su
`server_default` es `false` porque el valor por defecto de un permiso es «no».
Hoy ningún camino de indexación mira esta tabla —el RAG lee `documentos`— así
que la garantía es estructural; la columna es lo que permitirá levantarla por
fichero sin volver a migrar.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v127_pursuit_attachments"
down_revision: str | Sequence[str] | None = "v126_tecnologias_keywords"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
    if "pursuit_attachments" in set(sa.inspect(op.get_bind()).get_table_names()):
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
        # Clave del objeto en el almacén. Única: ver la cabecera.
        sa.Column("blob_key", sa.Text, nullable=False),
        # Nombre que verá quien descargue. Saneado en el servicio: nunca lleva
        # separadores de ruta, porque viaja en `Content-Disposition`.
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("content_type", sa.Text, nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        # SHA-256 del contenido: identidad del objeto y verificación de que lo
        # que devuelve el almacén es lo que se guardó.
        sa.Column("sha256", sa.Text, nullable=False),
        sa.Column(
            "uploaded_by_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Opt-in por adjunto para el RAG. Por defecto `false`.
        sa.Column(
            "indexable",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("created_at", sa.Text, nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint(
            "char_length(filename) BETWEEN 1 AND 255",
            name="ck_pursuit_attachments_filename_length",
        ),
        # El tope duro vive aquí además de en el servicio: una ruta nueva que
        # olvide validar no puede meter un objeto de 2 GB en el bucket.
        sa.CheckConstraint(
            "size_bytes > 0 AND size_bytes <= 26214400",
            name="ck_pursuit_attachments_size",
        ),
        sa.CheckConstraint(
            "char_length(sha256) = 64",
            name="ck_pursuit_attachments_sha256",
        ),
        sa.UniqueConstraint("blob_key", name="uq_pursuit_attachments_blob_key"),
    )
    # El listado de la pestaña Expediente: los de una oportunidad, recientes
    # primero.
    op.create_index(
        "idx_pursuit_attachments_pursuit",
        "pursuit_attachments",
        ["pursuit_id", "id"],
    )
    # La purga por organización (borrado de organización, ADR-030 §D) y el
    # inventario de ocupación por cliente.
    op.create_index(
        "idx_pursuit_attachments_org",
        "pursuit_attachments",
        ["organization_id", "created_at"],
    )
    _protect_table("pursuit_attachments")


def downgrade() -> None:
    if not _is_postgres():
        return
    # Solo la fila: los objetos del almacén los borra `purge_keys`, y hacerlo
    # desde una migración dejaría el bucket a merced de un `downgrade` mal
    # tecleado.
    op.drop_index("idx_pursuit_attachments_org", table_name="pursuit_attachments")
    op.drop_index("idx_pursuit_attachments_pursuit", table_name="pursuit_attachments")
    op.drop_table("pursuit_attachments")
