"""v147: tipo de documento en ``organization_certifications``.

Revision ID: v147_documentacion_tipo
Revises: v146_lic_organo_norm_index
Create Date: 2026-10-12

Qué falta hoy
-------------
``organization_certifications`` (v112) guarda las certificaciones técnicas que
el checklist contrasta con el pliego —ISO 9001, ISO/IEC 27001, ENS— con su
``vigente_hasta``. Pero lo que caduca y deja a una empresa fuera de una
licitación es sobre todo la **documentación administrativa**: el certificado
de estar al corriente con la AEAT, el de la Seguridad Social, la inscripción
en el ROLECE, la clasificación empresarial. Sin distinguir el tipo no se puede
avisar con el texto correcto, ni separar lo que el go/no-go trata como
certificación de lo que es papeleo de solvencia.

Forma, y por qué
----------------
``tipo TEXT NOT NULL DEFAULT 'certificacion_tecnica'`` con un ``CHECK`` del
vocabulario cerrado. El defecto es lo que hace la columna **retrocompatible**:
todo lo guardado hasta hoy se declaró en una pantalla que pedía «ISO, ENS,
partner de fabricante, títulos del equipo», o sea certificaciones técnicas, y
así queda sin backfill. Con un defecto constante, ``ADD COLUMN`` es
metadata-only desde Postgres 11 y no reescribe la tabla. El ``CHECK`` sí la
recorre para validarla, y la tabla es pequeña (una fila por documento y
organización).

Una columna y no una tabla aparte: un documento administrativo tiene las
mismas tres cosas que una certificación —nombre, quién lo acredita y hasta
cuándo vale— y el perfil se reemplaza entero en cada ``PUT``
(``db/repositories/organization_capabilities.py``), así que dos tablas serían
dos ``DELETE`` + ``INSERT`` por el mismo concepto.

El vocabulario vive también en ``shared/dto.py``
(``OrganizationDocumentType``); este ``CHECK`` va congelado a propósito, como
el resto del linaje, que no importa del árbol de la app.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v147_documentacion_tipo"
down_revision: str | Sequence[str] | None = "v146_lic_organo_norm_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLA = "organization_certifications"
_CHECK = "ck_organization_certifications_tipo"
_TIPOS = (
    "certificacion_tecnica",
    "corriente_aeat",
    "corriente_seguridad_social",
    "rolece",
    "clasificacion_empresarial",
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.add_column(
        _TABLA,
        sa.Column(
            "tipo",
            sa.Text,
            nullable=False,
            server_default=sa.text("'certificacion_tecnica'"),
        ),
    )
    valores = ", ".join(f"'{tipo}'" for tipo in _TIPOS)
    op.create_check_constraint(_CHECK, _TABLA, f"tipo IN ({valores})")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.drop_constraint(_CHECK, _TABLA, type_="check")
    op.drop_column(_TABLA, "tipo")
