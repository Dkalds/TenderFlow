"""v85: ``procedimiento``, ``tramitacion`` y ``peso_precio_pct`` en ``licitaciones``.

Revision ID: v85_lic_procedimiento_tramitacion
Revises: v84_lic_universo_cpv_index
Create Date: 2026-08-18

El modelo de baja llegó a su techo con las columnas que había. Los tres
drivers que de verdad mueven la baja en contratación pública española --el
tipo de procedimiento (un menor y un abierto no compiten igual), la
tramitación (urgente acorta el plazo y espanta licitadores) y cuánto pesa el
precio frente al juicio de valor-- viajan en el CODICE de PLACSP desde
siempre, pero el parser los tiraba: no había dónde ponerlos. El RFC de modelos
predictivos (2026-06-11, §Restricciones de datos) ya anotó el gap. Estas tres
columnas lo cierran por el lado de la persistencia.

Tipos, y por qué
----------------
``procedimiento`` y ``tramitacion`` son **TEXT y guardan el código CODICE
crudo**, no una etiqueta. CODICE los publica como valores de listas
controladas versionadas (``listURI`` apunta al ``.gc`` de la Plataforma);
traducirlos en ingesta obligaría a congelar una copia de esas listas, que
envejece en silencio y convierte un código nuevo en una etiqueta plausible
pero falsa. TEXT además es lo coherente con la tabla: v83 dejó dicho que en
``licitaciones`` la coherencia de tipos con el resto del esquema manda sobre
la pureza (allí, fechas como TEXT), y aquí los enumerados vecinos
--``tipo_contrato``, ``estado``, ``duracion_unidad``, ``nuts_code``-- ya son
todos texto libre sin CHECK ni ENUM.

``peso_precio_pct`` es ``sa.Float`` (el tipo de los demás importes y
probabilidades de la tabla) y va en porcentaje sobre 100. Solo se rellena
cuando la suma de los pesos publicados declara su escala; si no, queda NULL.
Ver ``scraper.codice_parser.parse_peso_precio``.

Por qué esto NO es v68
----------------------
v68 añadió una **columna generada** a esta misma tabla y Postgres reescribió
1,6M filas con lock exclusivo durante media hora, tumbando la app. Aquí las
tres columnas son **nullable y sin default**, así que ``ADD COLUMN`` toca solo
el catálogo: es metadata-only, instantáneo y sin reescritura (mismo patrón que
v83). No hay columna generada, ni ``SET NOT NULL``, ni default volátil, ni
backfill dentro de la migración.

El backfill de lo ya ingerido queda **fuera** de esta revisión a propósito: es
un reproceso de los ZIP mensuales cacheados, por lotes y con su propia medida
de cobertura por campo. Meterlo aquí sería repetir el error de v68 por otra
vía --un UPDATE masivo bajo el lock de la migración-- sobre una tabla que la
app está sirviendo.

Las tres columnas nacen NULL en todas las filas existentes, y eso es correcto:
NULL significa "este expediente se ingirió antes de que el parser supiera
leer el dato", que es exactamente el caso. Ninguna consulta actual las
menciona, así que el despliegue del esquema es independiente del despliegue
del parser.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v85_lic_procedimiento_tramitacion"
down_revision: str | Sequence[str] | None = "v84_lic_universo_cpv_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.add_column("licitaciones", sa.Column("procedimiento", sa.Text, nullable=True))
    op.add_column("licitaciones", sa.Column("tramitacion", sa.Text, nullable=True))
    op.add_column("licitaciones", sa.Column("peso_precio_pct", sa.Float, nullable=True))


def downgrade() -> None:
    if not _is_postgres():
        return
    op.drop_column("licitaciones", "peso_precio_pct")
    op.drop_column("licitaciones", "tramitacion")
    op.drop_column("licitaciones", "procedimiento")
