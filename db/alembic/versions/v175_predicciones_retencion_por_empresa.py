"""v175: ``predicciones_retencion`` pasa a una fila por expediente y empresa.

La PK era ``licitacion_id``, pero Renovaciones pinta una fila por adjudicatario
y las features del modelo dependen de la empresa (antigüedad de la relación,
cuota, contratos previos). En un expediente con varios adjudicatarios todos
veían el riesgo del primero (backlog P2 «ml-scoring», criterio «resolver la
clave antes de activar ``retencion_model``»). El batch ya escribe una fila por
``(expediente, empresa)`` (``services.ml.retencion_labels._vencimientos``).

Orden
-----
1. Se borran las filas sin ``empresa_id`` (el batch nunca las escribe: su
   población exige empresa) y la columna pasa a ``NOT NULL``, que una PK
   compuesta necesita. La tabla tiene unas 3.000 filas: el escaneo de
   ``SET NOT NULL`` son milisegundos.
2. Índice único ``(licitacion_id, empresa_id)`` ``CONCURRENTLY``.
3. Se retira la PK vieja (por tipo, como v140: el nombre no está garantizado)
   y la nueva se monta ``USING INDEX``, sin reconstruir nada. Las dos
   sentencias de catálogo van con ``lock_timeout``.

El código que escribe con el árbitro nuevo (``ON CONFLICT (licitacion_id,
empresa_id)``) va en el mismo cambio: con la PK vieja, ese árbitro no
encontraría índice.

Downgrade
---------
Conserva una fila por expediente (la de mayor riesgo) y restaura la PK. Es
materialización recalculable del batch.

DIALECT-GUARDED: solo actúa en Postgres.

Revision ID: v175_predicciones_retencion_por_empresa
Revises: v174_predicciones_baja_sombra
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v175_predicciones_retencion_por_empresa"
down_revision: str | Sequence[str] | None = "v174_predicciones_baja_sombra"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLA = "predicciones_retencion"
_UQ = "uq_pred_ret_licitacion_empresa"
_PK = "predicciones_retencion_pkey"

_DROP_PK = f"""
DO $$
DECLARE
    c_name text;
BEGIN
    SELECT conname INTO c_name
    FROM pg_constraint
    WHERE conrelid = '{_TABLA}'::regclass AND contype = 'p'
    LIMIT 1;
    IF c_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE {_TABLA} DROP CONSTRAINT %I', c_name);
    END IF;
END $$;
"""


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute(f"DELETE FROM {_TABLA} WHERE empresa_id IS NULL")
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(f"ALTER TABLE {_TABLA} ALTER COLUMN empresa_id SET NOT NULL")
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {_UQ} "
            f"ON {_TABLA} (licitacion_id, empresa_id)"
        )
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(_DROP_PK)
    op.execute(f"ALTER TABLE {_TABLA} ADD CONSTRAINT {_PK} PRIMARY KEY USING INDEX {_UQ}")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute(
        f"DELETE FROM {_TABLA} p USING {_TABLA} q "
        "WHERE p.licitacion_id = q.licitacion_id "
        "AND (p.riesgo_cambio, p.empresa_id) < (q.riesgo_cambio, q.empresa_id)"
    )
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(_DROP_PK)
    op.execute(f"ALTER TABLE {_TABLA} ADD CONSTRAINT {_PK} PRIMARY KEY (licitacion_id)")
    op.execute(f"ALTER TABLE {_TABLA} ALTER COLUMN empresa_id DROP NOT NULL")
