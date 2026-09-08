"""v118: ``notification_preferences`` — dónde vive «no me mandes esto» (C2.7).

Qué corrige
-----------
Ninguna tabla ni servicio modela las preferencias de notificación (hecho 13 del
plan complementario). El despachador de eventos de v2 S4.6 las necesita —
`immediate | daily | off` por usuario y tipo— y aquel plan no dice dónde viven.

Sin esta tabla, «respetar la preferencia del usuario» no tiene sujeto: cada
canal acabaría inventando su propio sitio, que es como se llega a tener el
mismo ajuste en tres pantallas con tres valores distintos.

La forma
--------
``(user_id, organization_id, tipo, canal)`` → ``frecuencia``.

- **`organization_id` nullable**: una preferencia sin organización es la del
  usuario en todas partes; con ella, la de ese usuario en ese equipo. Alguien
  que quiere el digest diario de su consultora y nada de su cooperativa no
  puede expresarlo con una sola fila.
- **`tipo`** es un evento del catálogo de ADR-027 (`pursuit.assigned`,
  `licitacion.cambiada`…). No se valida con un `CHECK`: el catálogo vive en
  `shared/events.py` y una enumeración duplicada en el schema divergiría en el
  primer evento nuevo.
- **`canal`** ∈ `email`, `in_app`, `webhook`.
- **`frecuencia`** ∈ `immediate`, `daily`, `off`. Sí lleva `CHECK`: es un
  vocabulario cerrado que no crece con el producto.

Lo que NO define esta revisión
------------------------------
El **valor por defecto** cuando no hay fila. Eso es contrato, no schema: vive en
el DTO (`shared/dto.py`) para que el frontend y el despachador lean el mismo
default en vez de que cada uno elija el suyo. Una fila ausente significa «el
default», no «off» — apagar por omisión es la clase de decisión que hace que
nadie se entere de nada y nadie sepa por qué.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v118_notification_preferences"
down_revision: str | Sequence[str] | None = "v117_client_errors"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("CURRENT_TIMESTAMP")

FRECUENCIAS = ("immediate", "daily", "off")
CANALES = ("email", "in_app", "webhook")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    if "notification_preferences" in set(sa.inspect(op.get_bind()).get_table_names()):
        return

    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Nullable = la preferencia del usuario en todas sus organizaciones.
        sa.Column("organization_id", sa.Integer, nullable=True),
        sa.Column("tipo", sa.Text, nullable=False),
        sa.Column("canal", sa.Text, nullable=False),
        sa.Column("frecuencia", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.Text, nullable=False, server_default=_NOW),
    )
    valores = ", ".join(f"'{f}'" for f in FRECUENCIAS)
    op.execute(
        "ALTER TABLE notification_preferences ADD CONSTRAINT ck_notif_pref_frecuencia "
        f"CHECK (frecuencia IN ({valores}))"
    )
    canales = ", ".join(f"'{c}'" for c in CANALES)
    op.execute(
        "ALTER TABLE notification_preferences ADD CONSTRAINT ck_notif_pref_canal "
        f"CHECK (canal IN ({canales}))"
    )
    # `COALESCE(organization_id, 0)` en el único: en Postgres dos filas con NULL
    # no colisionan, así que sin esto un usuario podría tener dos preferencias
    # globales contradictorias para el mismo (tipo, canal) y ganaría la que el
    # planificador devolviera primero.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_notif_pref_uniq "
        "ON notification_preferences "
        "(user_id, COALESCE(organization_id, 0), tipo, canal)"
    )
    op.create_index("idx_notif_pref_user", "notification_preferences", ["user_id"])


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP TABLE IF EXISTS notification_preferences CASCADE")
