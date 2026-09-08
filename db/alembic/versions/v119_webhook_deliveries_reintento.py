"""v119: reintento y re-entrega de webhooks (C2.4).

Qué corrige
-----------
``db/webhooks.py::_record_delivery`` cuenta fallos y **desactiva el webhook al
superar el umbral**. No hay backoff, no hay reintento y no hay re-entrega: cero
coincidencias de ``retry`` ni ``backoff`` en el módulo (hecho 10 del plan).

La consecuencia es que un endpoint que devuelve 503 durante un despliegue de
tres minutos pierde los eventos de esos tres minutos, y si el despliegue coincide
con tres eventos, además se queda desactivado. Al cliente le desaparecen los
avisos y nadie le dice por qué.

Columnas nuevas en ``webhook_deliveries``
-----------------------------------------
================== ==========================================================
``delivery_uid``   Identificador **estable entre reintentos**. Viaja en la
                   cabecera ``X-Webhook-Delivery``: es lo que permite al
                   receptor deduplicar. Si cambiara en cada intento, un
                   receptor idempotente procesaría el mismo evento seis veces.
``intentos``       Cuántas veces se ha intentado.
``proximo_intento``Cuándo toca el siguiente. ``NULL`` = no hay más.
``estado``         ``pending`` | ``delivered`` | ``failed``.
``payload_json``   El cuerpo, para poder reenviarlo. Sin él, «reintentar»
                   sería «mandar otra cosa».
``error_detail``   Por qué falló el último intento.
================== ==========================================================

Por qué se guarda el payload
----------------------------
Es la única columna cara de esta migración y no hay alternativa: reintentar sin
el cuerpo original obligaría a reconstruirlo desde el evento, y el evento pudo
cambiar de estado entre medias — se reenviaría un contenido distinto del que
falló, con la misma firma HMAC. La firma se recalcula sobre **el mismo cuerpo**,
que es lo que hace verificable el reintento.

La retención de ``webhook_deliveries`` (90 días) acota el coste.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v119_webhook_deliveries_reintento"
down_revision: str | Sequence[str] | None = "v118_notification_preferences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNAS = (
    ("delivery_uid", sa.Text),
    ("payload_json", sa.Text),
    ("error_detail", sa.Text),
    ("proximo_intento", sa.Text),
    ("estado", sa.Text),
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return

    inspector = sa.inspect(op.get_bind())
    if "webhook_deliveries" not in inspector.get_table_names():
        return
    existentes = {c["name"] for c in inspector.get_columns("webhook_deliveries")}

    for nombre, tipo in COLUMNAS:
        if nombre not in existentes:
            op.add_column("webhook_deliveries", sa.Column(nombre, tipo, nullable=True))
    if "intentos" not in existentes:
        op.add_column(
            "webhook_deliveries",
            sa.Column("intentos", sa.Integer, nullable=False, server_default="1"),
        )

    # Las filas ya escritas se marcan según su resultado. `success` es la única
    # información que tienen, y es suficiente: una entrega antigua sin reintento
    # o salió o no salió.
    op.execute(
        "UPDATE webhook_deliveries "
        "SET estado = CASE WHEN success = 1 THEN 'delivered' ELSE 'failed' END "
        "WHERE estado IS NULL"
    )
    op.execute(
        "ALTER TABLE webhook_deliveries ADD CONSTRAINT ck_wh_del_estado "
        "CHECK (estado IS NULL OR estado IN ('pending', 'delivered', 'failed'))"
    )

    # El índice del reintento: «qué toca reenviar ahora». Parcial sobre
    # `pending` porque las entregadas son la inmensa mayoría y el job nunca las
    # mira.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wh_del_reintento "
        "ON webhook_deliveries (proximo_intento) WHERE estado = 'pending'"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_wh_del_uid "
        "ON webhook_deliveries (delivery_uid) WHERE delivery_uid IS NOT NULL"
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP INDEX IF EXISTS idx_wh_del_uid")
    op.execute("DROP INDEX IF EXISTS idx_wh_del_reintento")
    op.execute("ALTER TABLE webhook_deliveries DROP CONSTRAINT IF EXISTS ck_wh_del_estado")
    for nombre, _ in COLUMNAS:
        op.execute(f"ALTER TABLE webhook_deliveries DROP COLUMN IF EXISTS {nombre}")
    op.execute("ALTER TABLE webhook_deliveries DROP COLUMN IF EXISTS intentos")
