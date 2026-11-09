"""v178: ``sistema_contratacion`` en ``licitaciones`` — marco, SDA, basado o ninguno.

Revision ID: v178_sistema_contratacion
Revises: v177_rss_autonomico_sin_tramitacion
Create Date: 2026-11-10

Qué falta hoy
-------------
Un acuerdo marco y un sistema dinámico de adquisición eran solo una etiqueta de
procedimiento (códigos ``7`` y ``12`` de ``shared/procedimientos.py``), y esa
etiqueta no los recoge: medido el 2026-11-10 sobre los 12 meses desde
2025-11-01, 494 expedientes de TI nombran un acuerdo marco o un sistema
dinámico en el título, 73 llevan el procedimiento ``7`` y ninguno el ``12``.
El dato sí viene en la fuente: ``cac:TenderingProcess/cbc:ContractingSystemCode``
de CODICE, que el parser no leía.

Forma, y por qué
----------------
``TEXT`` con un valor de ``shared.sistema_contratacion.SistemaContratacion``
(``ninguno``, ``marco``, ``sda``, ``basado_marco``, ``basado_sda``),
**normalizado** y no el código crudo, al revés que ``procedimiento`` en v85:
cada fuente lo publica con su lista, y «¿es un marco?» tiene que poder
preguntarse en SQL sin saber de qué fuente es la fila. El ``CHECK`` hace que un
valor nuevo pase por una migración en vez de colarse por un conector.

Nullable y sin default: ``ADD COLUMN`` es metadata-only (la lección de v68).
``NULL`` es «la fuente no lo dice», y es el caso de todo lo anterior a esta
revisión: no hay backfill aquí, el dato entra al reingerir. El ``CHECK`` se
añade ``NOT VALID`` y se valida aparte para no tener la tabla bloqueada
mientras se recorre.

Sin índice: lo único que lee la columna es la ficha de un expediente, por su
clave primaria, y el listado de renovaciones, que la proyecta sin filtrar por
ella.

No hay columna para el marco del que cuelga un basado: ninguna fuente lo
publica como dato (en el ATOM solo aparece nombrado en el título), y no se
deduce.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v178_sistema_contratacion"
down_revision: str | Sequence[str] | None = "v177_rss_autonomico_sin_tramitacion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "ck_lic_sistema_contratacion"
# Congelados aquí, no importados de `shared.sistema_contratacion`: una
# migración describe el esquema del día en que se escribió.
_VALORES = ("ninguno", "marco", "sda", "basado_marco", "basado_sda")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.add_column("licitaciones", sa.Column("sistema_contratacion", sa.Text, nullable=True))
    valores = ", ".join(f"'{v}'" for v in _VALORES)
    op.execute(
        f"ALTER TABLE licitaciones ADD CONSTRAINT {_CHECK} "
        f"CHECK (sistema_contratacion IN ({valores})) NOT VALID"
    )
    with op.get_context().autocommit_block():
        # SHARE UPDATE EXCLUSIVE: la ingesta y la API siguen leyendo y escribiendo.
        op.execute(f"ALTER TABLE licitaciones VALIDATE CONSTRAINT {_CHECK}")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute(f"ALTER TABLE licitaciones DROP CONSTRAINT IF EXISTS {_CHECK}")
    op.drop_column("licitaciones", "sistema_contratacion")
