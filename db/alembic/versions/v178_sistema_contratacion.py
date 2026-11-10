"""v178: ``sistema_contratacion`` y ``marco_ref`` en ``licitaciones`` — marcos y SDA.

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
El dato sí viene en las fuentes y no se leía: ``cbc:ContractingSystemCode`` de
CODICE, ``framework-agreement-lot`` / ``dps-usage-lot`` de eForms (TED) y la
columna ``racionalitzacio_contractacio`` de PSCP.

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

Sin índice sobre ``sistema_contratacion``: lo único que la lee es la ficha de un
expediente, por su clave primaria, y el listado de renovaciones, que la
proyecta sin filtrar por ella.

``marco_ref`` es el marco del que cuelga un contrato basado, escrito como el
``id_externo`` que tendría el expediente del marco (``ted:649072-2024``). No es
clave ajena: el marco puede no estar en ``licitaciones`` (no es de TI, o es
anterior a lo ingerido), y la referencia vale igual para cuando llegue. Solo la
rellena la fuente que publica el enlace como dato. Medido el 2026-11-10: TED lo
trae en ``framework-notice-id`` (257 de 259 adjudicaciones basadas en un
acuerdo marco); PLACSP no lo trae (ninguna etiqueta de enlace entre las 158 del
feed, solo el título lo nombra) y ahí queda ``NULL``, sin deducirlo; PSCP lo
trae en el JSON de cada fase, que el conector aún no lee.

Su índice es parcial —casi todas las filas son ``NULL``— y sirve la única
consulta que filtra por ella: los basados de un marco. Se crea
``CONCURRENTLY`` para no bloquear las escrituras de la ingesta.

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
_IDX = "idx_lic_marco_ref"
# Congelados aquí, no importados de `shared.sistema_contratacion`: una
# migración describe el esquema del día en que se escribió.
_VALORES = ("ninguno", "marco", "sda", "basado_marco", "basado_sda")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.add_column("licitaciones", sa.Column("sistema_contratacion", sa.Text, nullable=True))
    op.add_column("licitaciones", sa.Column("marco_ref", sa.Text, nullable=True))
    valores = ", ".join(f"'{v}'" for v in _VALORES)
    op.execute(
        f"ALTER TABLE licitaciones ADD CONSTRAINT {_CHECK} "
        f"CHECK (sistema_contratacion IN ({valores})) NOT VALID"
    )
    with op.get_context().autocommit_block():
        # SHARE UPDATE EXCLUSIVE: la ingesta y la API siguen leyendo y escribiendo.
        op.execute(f"ALTER TABLE licitaciones VALIDATE CONSTRAINT {_CHECK}")
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_IDX} "
            "ON licitaciones (marco_ref) WHERE marco_ref IS NOT NULL"
        )


def downgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_IDX}")
    op.execute(f"ALTER TABLE licitaciones DROP CONSTRAINT IF EXISTS {_CHECK}")
    op.drop_column("licitaciones", "marco_ref")
    op.drop_column("licitaciones", "sistema_contratacion")
