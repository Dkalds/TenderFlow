"""v125: el diccionario de tecnologías deja de ser un deploy (C5.6, D28).

Revision ID: v125_tecnologias_keywords
Revises: v124_retirar_extracciones
Create Date: 2026-09-07

Qué corrige
-----------
`config/keywords.py` es **código**: añadir «SAP BTP» a la lista exige un commit,
una revisión, un merge y un despliegue. El diccionario decide qué entra en el
universo tecnológico —o sea, qué ve el producto entero— así que la latencia
entre «hemos detectado un término nuevo» y «el radar lo recoge» es la latencia
de un ciclo de release completo, por una lista de palabras.

Qué NO cambia
-------------
`filter_version` sigue siendo **el hash del contenido** (`scraper/lineage.py`),
no un número de fila ni un `updated_at`. Esa era ya la propiedad correcta y es
la que hace auditable el cambio: dos filas ingeridas con el mismo hash se
filtraron con el mismo diccionario, viniera de la semilla o de la tabla.

`config/keywords.py` **se queda** como semilla. Un arranque limpio —un entorno
nuevo, un test, la primera migración— tiene diccionario sin que nadie lo
rellene, y `tests/test_c5_diccionario.py` comprueba que semilla y tabla
coinciden cuando la tabla se siembra desde ella.

Por qué `activa` y no borrar la fila
------------------------------------
Retirar una keyword es una decisión reversible que cambia el universo observado,
y su rastro importa tanto como el de añadirla: con `DELETE`, «esta keyword se
quitó el martes» deja de ser una pregunta contestable. La fila se desactiva y el
`filter_version` cambia igual, porque el diccionario efectivo solo mira las
activas.

`origen` distingue lo que vino de la semilla de lo que añadió una persona: sin
él, una resiembra no sabría qué puede pisar.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v125_tecnologias_keywords"
down_revision: str | Sequence[str] | None = "v124_retirar_extracciones"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
        # Etiqueta de tecnología (`SAP`, `SALESFORCE`, …). En mayúsculas, como
        # en la semilla: son las claves con las que el resto del sistema ya
        # trabaja y renombrarlas aquí obligaría a traducir en cada consumidor.
        sa.Column("tecnologia", sa.Text, nullable=False),
        sa.Column("keyword", sa.Text, nullable=False),
        sa.Column("activa", sa.Boolean, nullable=False, server_default=sa.text("true")),
        # `semilla` | `manual`. Distingue lo que puede pisar una resiembra.
        sa.Column("origen", sa.Text, nullable=False, server_default="semilla"),
        sa.Column(
            "created_by_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.Text, nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.Text, nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint(
            "char_length(keyword) BETWEEN 2 AND 120", name="ck_tecnologias_keywords_len"
        ),
        sa.CheckConstraint(
            "origen IN ('semilla', 'manual')", name="ck_tecnologias_keywords_origen"
        ),
    )
    # La identidad es (tecnología, keyword plegada): «SAP HANA» y «sap hana» son
    # la misma entrada, y tenerlas dos veces duplicaría la keyword en el regex
    # sin cambiar lo que casa — pero sí el hash, y con él el `filter_version` de
    # todas las filas nuevas, por nada.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_tecnologias_keywords "
        "ON tecnologias_keywords (tecnologia, lower(keyword))"
    )
    # La consulta del diccionario efectivo: todas las activas, en un solo barrido.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tecnologias_keywords_activas "
        "ON tecnologias_keywords (tecnologia) WHERE activa"
    )
    op.execute("ALTER TABLE tecnologias_keywords ENABLE ROW LEVEL SECURITY")
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN "
        "REVOKE ALL ON TABLE tecnologias_keywords FROM anon; "
        "END IF; "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN "
        "REVOKE ALL ON TABLE tecnologias_keywords FROM authenticated; "
        "END IF; "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tenderflow_app') THEN "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE tecnologias_keywords "
        "TO tenderflow_app; "
        "GRANT USAGE, SELECT ON SEQUENCE tecnologias_keywords_id_seq TO tenderflow_app; "
        "CREATE POLICY tenderflow_app_full_access ON tecnologias_keywords "
        "FOR ALL TO tenderflow_app USING (true) WITH CHECK (true); "
        "END IF; END $$"
    )

    # **La siembra no va aquí.** Meter las ~200 keywords de `config/keywords.py`
    # en la migración congelaría en el historial de esquema una copia del
    # diccionario que envejece sola: la semilla cambia con el código y la
    # migración no se vuelve a ejecutar. La siembra la hace
    # `services/tecnologias_diccionario.sembrar_desde_semilla()`, que es
    # idempotente y se puede repetir tras cada cambio de la semilla.


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP TABLE IF EXISTS tecnologias_keywords CASCADE")
