"""v112: el importe dice de qué base es (C1.1, ADR-032, D21).

Qué corrige
-----------
``scraper/codice_parser.py`` toma ``cbc:TaxExclusiveAmount`` y, si falta, cae a
``cbc:TotalAmount``. El primero es la base **sin** IVA; el segundo lo
**incluye**. La fila guardaba un número en ``licitaciones.importe`` y **no
guardaba cuál de los dos fue**.

La consecuencia no es de precisión, es de significado:
``services/competitive/bajas.py`` calcula ``(importe - adjudicado) / importe``
sobre una población en la que unas filas llevan IVA y otras no. Una baja del
21 % puede ser exactamente el IVA. Los escenarios de precio y el scoring por
banda heredan el mismo defecto.

Además ``cbc:EstimatedOverallContractAmount`` —el valor estimado del contrato,
que incluye prórrogas y modificaciones y es lo que la Ley 9/2017 usa para
determinar el procedimiento— no se extraía en absoluto.

Qué añade
---------
============================ ======================================= ==========
Columna                      Origen CODICE                           Tipo
============================ ======================================= ==========
``importe_base_sin_iva``     ``cbc:TaxExclusiveAmount``              ``double``
``importe_con_iva``          ``cbc:TotalAmount``                     ``double``
``valor_estimado``           ``cbc:EstimatedOverallContractAmount``  ``double``
``importe_tipo``             derivada                                ``text``
============================ ======================================= ==========

**``importe`` se conserva** como alias de la base sin IVA. No se renombra ni se
borra: lo consumen el frontend, los exports, el scoring y varias vistas
materializadas, y romperlo a cambio de un nombre mejor no compra nada.

Por qué el histórico queda en ``desconocido``
---------------------------------------------
``importe_tipo ∈ {sin_iva, con_iva, desconocido}``. Las filas ya ingeridas **no
se pueden reinterpretar**: el parser guardó el número y tiró la información de
qué elemento CODICE lo produjo, así que no hay forma de deducirlo sin volver a
parsear el XML original. Marcarlas ``desconocido`` es lo único honesto; el
backfill real lo hace la re-ingesta, que sí sabe de dónde viene cada valor.

Ese es el motivo de que el umbral de ``audit_domain_truth`` sea sobre **filas
nuevas** y no sobre el total: exigir 0 ``desconocido`` hoy sería exigir que el
pasado se reescriba solo.

Riesgo
------
Cuatro columnas en la tabla núcleo (~706k filas medidas el 2026-09-06). Las
cuatro son aditivas y nullable, así que el ``ALTER`` no reescribe la tabla en
Postgres 11+; el ``UPDATE`` del ``importe_tipo`` sí la recorre entera y por eso
va con ``statement_timeout`` desactivado, igual que ``v100``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v112_lic_semantica_del_importe"
down_revision: str | Sequence[str] | None = "v102_mv_canonicas_clave_inmutable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Las tres columnas de importe, con el elemento CODICE del que salen.
COLUMNAS_IMPORTE = (
    "importe_base_sin_iva",
    "importe_con_iva",
    "valor_estimado",
)

COLUMNA_TIPO = "importe_tipo"

#: Vocabulario cerrado. `desconocido` no es un valor de relleno: es la respuesta
#: correcta para una fila cuyo origen ya no se puede determinar.
TIPOS_VALIDOS = ("sin_iva", "con_iva", "desconocido")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return

    for columna in COLUMNAS_IMPORTE:
        op.add_column("licitaciones", sa.Column(columna, sa.Float, nullable=True))
    op.add_column("licitaciones", sa.Column(COLUMNA_TIPO, sa.Text, nullable=True))

    # El CHECK acepta NULL a propósito: una fila que todavía no ha pasado por el
    # parser nuevo no tiene tipo, y eso es distinto de tener uno inválido.
    valores = ", ".join(f"'{t}'" for t in TIPOS_VALIDOS)
    op.execute(
        "ALTER TABLE licitaciones ADD CONSTRAINT ck_licitaciones_importe_tipo "
        f"CHECK ({COLUMNA_TIPO} IS NULL OR {COLUMNA_TIPO} IN ({valores}))"
    )

    op.execute("SET statement_timeout = 0")

    # El histórico: `importe` existe pero no se sabe de qué base es.
    #
    # No se copia a `importe_base_sin_iva`. Copiarlo afirmaría que es la base
    # sin IVA, que es justo lo que no se sabe — y `bajas`/`pricing` leen esa
    # columna precisamente porque significa eso. Un dato que miente en la
    # columna correcta es peor que un hueco.
    op.execute(
        "UPDATE licitaciones SET importe_tipo = 'desconocido' "
        "WHERE importe IS NOT NULL AND importe_tipo IS NULL"
    )

    # Índice parcial sobre las filas que SÍ tienen base declarada: es la
    # población sobre la que `bajas` y `pricing` van a filtrar en cada consulta,
    # y arranca vacía (se llena con la re-ingesta), así que crearlo ahora es
    # gratis y evita el `CREATE INDEX` sobre una tabla ya poblada más adelante.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_lic_importe_base_sin_iva "
        "ON licitaciones (importe_base_sin_iva) "
        "WHERE importe_base_sin_iva IS NOT NULL"
    )
    op.execute("ANALYZE licitaciones")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP INDEX IF EXISTS idx_lic_importe_base_sin_iva")
    op.execute("ALTER TABLE licitaciones DROP CONSTRAINT IF EXISTS ck_licitaciones_importe_tipo")
    op.drop_column("licitaciones", COLUMNA_TIPO)
    for columna in reversed(COLUMNAS_IMPORTE):
        op.drop_column("licitaciones", columna)
