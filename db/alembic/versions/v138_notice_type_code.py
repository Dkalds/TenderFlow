"""v138: ``tipos_anuncio`` en ``licitaciones`` — el ``NoticeTypeCode`` de CODICE.

Revision ID: v138_notice_type_code
Revises: v132_informes_programados
Create Date: 2026-09-18

Qué falta hoy
-------------
Cada ``cac-place-ext:ValidNoticeInfo`` de un expediente PLACSP lleva un
``cbc-place-ext:NoticeTypeCode`` que dice **qué anuncio** es: ``DOC_CN``
(licitación), ``DOC_CD`` (pliegos), ``DOC_PIN_RTL`` (información previa)…
El parser leía la ``IssueDate`` de esos bloques y tiraba el código, así que
desde la BD no se puede saber si un expediente pasó por un anuncio previo. El
spike T5 (``docs/plans/2026-09-spike-planes-anuales-placsp.md``, §3 y «Lo
barato que sí sale de aquí») lo midió en el 4,35 % del feed y dejó anotado que
es el único dato del spike que hoy se pierde.

Forma, y por qué
----------------
``TEXT`` con los códigos **crudos**, distintos y ordenados, separados por coma
(``"DOC_CD,DOC_CN,DOC_PIN_RTL"``). Crudos por el mismo motivo que
``procedimiento``/``tramitacion`` en v85: la lista de códigos está versionada
por la Plataforma (``TenderingNoticeTypeCode-2.11.gc``, treinta códigos) y
traducirlos en ingesta congelaría una copia que envejece en silencio. Una
lista y no un código porque un expediente acumula varios anuncios. CSV y no
array porque es la convención de la tabla (``tecnologia``, ``ml_tecnologias``).

Nullable y sin default: ``ADD COLUMN`` es metadata-only y no reescribe la tabla
(la lección de v68). NULL significa «ingerido antes de que el parser leyera el
dato», que es exactamente el caso de todo lo existente; no hay backfill aquí.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v138_notice_type_code"
down_revision: str | Sequence[str] | None = "v132_informes_programados"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.add_column("licitaciones", sa.Column("tipos_anuncio", sa.Text, nullable=True))


def downgrade() -> None:
    if not _is_postgres():
        return
    op.drop_column("licitaciones", "tipos_anuncio")
