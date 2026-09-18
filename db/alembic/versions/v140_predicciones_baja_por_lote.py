"""v140: ``predicciones_baja`` admite una fila por lote además de la agregada.

v86 abrió la puerta sin cruzarla: añadió ``lote_id`` y un índice único
``(licitacion_id, COALESCE(lote_id, -1))``, pero dejó viva la PK sobre
``licitacion_id`` para no romper el ``ON CONFLICT (licitacion_id)`` del batch.
Con esa PK dos filas del mismo expediente son imposibles, así que ningún
modelo por lote podía materializarse (backlog P2 «Modelo de baja por lote»; la
corrección del 2026-09-08 en el ítem S3 lo comprobó: el único escritor nunca
rellenó la columna). Esta revisión cruza la puerta.

La identidad del lote es ``lote_numero``, no ``lote_id``
---------------------------------------------------------
El enunciado pide unicidad ``(licitacion_id, lote_id)``, y v86 dejó la FK
``lote_id → lotes(id) ON DELETE CASCADE``. Esa combinación **no sobrevive a la
re-ingesta**, por la misma razón que v110 documentó para ``pursuits``:
``db/upsert.py::replace_lotes`` hace ``DELETE`` + ``INSERT`` de los lotes del
expediente en cada pasada del scraper, así que cada re-ingesta les da ids
nuevos y el CASCADE borraría todas las predicciones por lote del expediente.

Para el serving eso sería una molestia (la fila vuelve con el batch
siguiente), pero para la **calibración** es fatal: el par
predicción↔realidad solo existe si la predicción sigue ahí cuando el
expediente se adjudica, y la adjudicación llega precisamente por una
re-ingesta — la que borraría la predicción. La medida de ``mae_p50`` por lote
que condiciona el cambio de granularidad (``services.ml.calibration``) no
vería nunca una predicción propia del lote.

La clave de negocio estable del lote es ``(licitacion_id, numero)``, que
``uq_lotes_licitacion_numero`` (v65) protege y ``replace_lotes`` conserva por
construcción. Se persiste ``lote_numero`` y el ``lote_id`` se re-resuelve al
leer con un JOIN por esa clave (mismo contrato que v110): la API sigue
recibiendo y devolviendo ``lote_id``. Si el lote desaparece del pliego, la
predicción queda huérfana y simplemente no se sirve; la purga por antigüedad
(``PrediccionesRepository.purgar_cerradas``) se la lleva con el resto de filas
del expediente.

``lote_id`` se **elimina**: nunca tuvo un escritor (ver el ítem S3 del
backlog), así que todas sus filas son NULL y no se pierde nada. Dejarla sería
dejar dos columnas candidatas a identidad del lote, una de ellas con un CASCADE
que borra datos en cada re-ingesta.

Dos únicos parciales, patrón v65/v110
-------------------------------------
- ``uq_pred_baja_expediente`` (``WHERE lote_numero IS NULL``): como mucho una
  predicción agregada por expediente. Es la garantía de la PK que se retira,
  para exactamente las filas que existían (todas tienen ``lote_numero`` NULL).
- ``uq_pred_baja_lote`` (``WHERE lote_numero IS NOT NULL``): como mucho una
  predicción por lote.

Una ``UNIQUE (licitacion_id, lote_numero)`` a secas no protegería el caso
agregado (``NULL <> NULL``). El índice de expresión de v86 sí lo hacía, pero el
árbitro de ``ON CONFLICT`` sobre dos únicos parciales se escribe con el mismo
predicado que el índice (``ON CONFLICT (licitacion_id) WHERE lote_numero IS
NULL``), que es legible y no depende de repetir un centinela mágico (``-1``) en
cada escritor.

Orden y coste
-------------
1. ``ADD COLUMN lote_numero TEXT``: NULLable y sin DEFAULT, metadata-only (la
   lección de v68 que citan v83/v86/v110).
2. Los dos índices nuevos ``CONCURRENTLY`` **antes** de retirar nada: entre
   pasos la tabla está protegida por partida doble, nunca por ninguna.
3. ``DROP CONSTRAINT`` de la PK —una sentencia de catálogo, ACCESS EXCLUSIVE de
   milisegundos— con ``lock_timeout`` para que encole detrás del batch o de la
   API en vez de bloquear a media BD. Se localiza por tipo y no por nombre:
   v55 la creó con ``create_table`` y otras bases se bootstrapearon por otro
   camino.
4. Fuera el índice, la FK y la columna de v86. ``DROP COLUMN`` también es
   metadata-only en Postgres.

El despliegue tiene que llevar el código que escribe con el árbitro nuevo
**en el mismo cambio**: con la PK retirada, el ``ON CONFLICT (licitacion_id)``
anterior deja de encontrar un índice que lo respalde y el batch falla. Es el
switch que v86 anunció, y por eso vive en la misma rama que el cambio de
``db/repositories/predicciones.py``.

Downgrade
---------
Borra las filas por lote antes de restaurar la PK. Son una materialización
recalculable del batch —no dato humano como los pursuits de v110—, así que
perderlas en un rollback es el precio correcto: la alternativa sería un
downgrade que falla siempre que el batch por lote haya corrido una vez.

DIALECT-GUARDED: solo actúa en Postgres.

Revision ID: v140_predicciones_baja_por_lote
Revises: v132_informes_programados
Create Date: 2026-09-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v140_predicciones_baja_por_lote"
down_revision: str | Sequence[str] | None = "v132_informes_programados"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Único parcial del caso agregado: la garantía de la PK que se retira.
_UQ_EXPEDIENTE = "uq_pred_baja_expediente"
#: Único parcial por lote: la protección nueva.
_UQ_LOTE = "uq_pred_baja_lote"

# Objetos de v86 que se retiran.
_UQ_V86 = "uq_pred_baja_lic_lote"
_FK_V86 = "fk_pred_baja_lote"
_SENTINELA_V86 = -1

_PK_RESTAURADA = "predicciones_baja_pkey"

# La PK no tiene nombre garantizado en todos los entornos; se busca por tipo.
_DROP_PK = """
DO $$
DECLARE
    c_name text;
BEGIN
    SELECT conname INTO c_name
    FROM pg_constraint
    WHERE conrelid = 'predicciones_baja'::regclass AND contype = 'p'
    LIMIT 1;
    IF c_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE predicciones_baja DROP CONSTRAINT %I', c_name);
    END IF;
END $$;
"""


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return

    # 1. Metadata-only: NULLable y sin DEFAULT.
    op.execute("ALTER TABLE predicciones_baja ADD COLUMN IF NOT EXISTS lote_numero TEXT")

    # 2. Los únicos nuevos antes de retirar la PK.
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {_UQ_EXPEDIENTE} "
            "ON predicciones_baja (licitacion_id) WHERE lote_numero IS NULL"
        )
        op.execute(
            f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {_UQ_LOTE} "
            "ON predicciones_baja (licitacion_id, lote_numero) "
            "WHERE lote_numero IS NOT NULL"
        )

    # 3. La PK: catálogo puro, pero ACCESS EXCLUSIVE. Que encole, no que bloquee.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(_DROP_PK)

    # 4. Lo que v86 dejó preparado para una identidad que no sobrevive a la
    #    re-ingesta (ver docstring).
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_UQ_V86}")
    op.execute(f"ALTER TABLE predicciones_baja DROP CONSTRAINT IF EXISTS {_FK_V86}")
    op.execute("ALTER TABLE predicciones_baja DROP COLUMN IF EXISTS lote_id")


def downgrade() -> None:
    if not _is_postgres():
        return

    # Materialización recalculable: se sacrifica para poder volver a la PK.
    op.execute("DELETE FROM predicciones_baja WHERE lote_numero IS NOT NULL")

    op.add_column("predicciones_baja", sa.Column("lote_id", sa.Integer, nullable=True))
    op.execute(
        f"ALTER TABLE predicciones_baja ADD CONSTRAINT {_FK_V86} "
        "FOREIGN KEY (lote_id) REFERENCES lotes(id) ON DELETE CASCADE NOT VALID"
    )
    op.execute(
        f"ALTER TABLE predicciones_baja ADD CONSTRAINT {_PK_RESTAURADA} PRIMARY KEY (licitacion_id)"
    )
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TABLE predicciones_baja VALIDATE CONSTRAINT {_FK_V86}")
        op.execute(
            f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {_UQ_V86} "
            "ON predicciones_baja "
            f"(licitacion_id, COALESCE(lote_id, {_SENTINELA_V86}))"
        )
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_UQ_LOTE}")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_UQ_EXPEDIENTE}")
    op.execute("ALTER TABLE predicciones_baja DROP COLUMN IF EXISTS lote_numero")
