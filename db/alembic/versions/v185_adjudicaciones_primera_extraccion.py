"""v185: ``adjudicaciones.primera_extraccion`` — la alerta de competidor deja de repetirse.

Revision ID: v185_adjudicaciones_primera_extraccion
Revises: v184_primera_extraccion_relleno
Create Date: 2026-11-16

Qué corrige
-----------
``db/watchlist_empresas.nuevas_adjudicaciones_de_empresa`` decidía «nueva» por
``adjudicaciones.fecha_extraccion``, y ``db/upsert.replace_adjudicaciones*``
borra e inserta todas las adjudicaciones de la licitación en cada reingesta, así
que la re-sella: cada reingesta de un expediente ya avisado volvía a mandar la
misma adjudicación como novedad a quien vigila a esa empresa (y re-calculaba
``ccaa_nueva``/``cpv_nuevo`` contra un historial que también se movía).

Esta revisión crea ``primera_extraccion``: desde cuándo la vigilancia de la
empresa puede ver la fila. El upsert la conserva de la fila borrada con la
misma clave de deduplicado (licitación, lote, NIF, importe), junto con su
``empresa_id``. Una fila nueva entra sin empresa y con la hora del parseo, y al
enlazarla ``db.empresas`` le pone la hora del enlace. Si una alerta corre entre
la ingesta y el enlace, la fila sigue saliendo en la siguiente.
Como en ``licitaciones`` (``v100``), es ``text`` en el formato de
``now_utc_iso()``; ``fecha_extraccion`` de ``adjudicaciones`` no tiene sombra
``_ts`` (``v159``), así que esta tampoco.

El relleno, y por qué no re-notifica
------------------------------------
Las filas existentes se rellenan con su ``fecha_extraccion``: no hay un dato
mejor (la tabla no tiene historia) y es exactamente el valor con el que la
alerta ya las comparó. Una fila que ya se avisó se avisó por esa fecha, y el
``last_notified_at`` de la vigilancia está por encima; seguir con el mismo
valor no la vuelve a emitir.

La columna se queda anulable: ``NOT NULL`` exigiría un barrido de la tabla bajo
lock exclusivo. Una fila que la traiga a ``NULL`` (la que escriba el código
anterior entre esta migración y su despliegue, que va **después**: el upsert
nuevo ya inserta la columna) se lee como ``COALESCE(primera_extraccion,
fecha_extraccion)``, en la alerta y al conservarla en la siguiente reingesta:
se comporta como antes de esta revisión hasta que se reingiere una vez.

Lo que aún avisa una vez más: la conservación casa por la clave exacta. Una
fila guardada cuya clave ya no coincide con la que da el parseo actual se trata
como nueva en su próxima reingesta: pierde el enlace y, al volver a enlazarse,
recibe la hora del enlace. Pasa con importes de
``real`` promovidos por ``v156`` y no reingeridos (11 782 155,0 frente a
11 782 154,55), adjudicatarios compuestos partidos con importe ``NULL`` que el
parser ahora reparte, ``lote_id`` resuelto después (cambia la clave de tres a
cuatro campos) o un importe que corrige la fuente. Avisa una vez y, desde ahí,
la clave ya coincide; antes de esta revisión avisaba en cada reingesta.

Coste
-----
``ADD COLUMN`` anulable sin default es solo de catálogo, pero ``env.py`` corre
la revisión en una transacción, así que su lock ``ACCESS EXCLUSIVE`` sigue
tomado durante todo el ``UPDATE``: las lecturas de la API y la ingesta sobre
``adjudicaciones`` esperan hasta el commit. Es el patrón de ``v100``; con unas
80 000 filas (130 MB según ``v156``) se esperan segundos, no minutos.
``statement_timeout = 0`` porque puede pasar de los 30 s del rol, y
``lock_timeout`` para no esperar detrás de una ingesta. Idempotente: solo toca
las filas a ``NULL``.

Downgrade: borra la columna.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "v185_adjudicaciones_primera_extraccion"
down_revision: str | None = "v184_primera_extraccion_relleno"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

COLUMNA = "primera_extraccion"

RELLENAR = (
    "UPDATE adjudicaciones SET primera_extraccion = fecha_extraccion "
    "WHERE primera_extraccion IS NULL"
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute("SET lock_timeout = '30s'")
    op.add_column("adjudicaciones", sa.Column(COLUMNA, sa.Text, nullable=True))
    op.execute("SET statement_timeout = 0")
    op.execute(RELLENAR)
    op.execute("RESET statement_timeout")
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.drop_column("adjudicaciones", COLUMNA)
