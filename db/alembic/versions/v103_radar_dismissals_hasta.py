"""v103: ``hasta``, ``accion`` y ``organization_id`` en ``radar_dismissals``.

Revision ID: v103_radar_dismissals_hasta
Revises: v102_mv_canonicas_clave_inmutable
Create Date: 2026-09-06

F5.6 del plan de funcionalidades 2026-09. ``v76`` creó la tabla con una sola
semántica: descartado **para siempre**, hasta que el usuario lo deshaga a
mano. Quien tría a diario no quiere eso la mayoría de las veces: quiere «esto
no me interesa este trimestre» y «recuérdamelo cuando salga el pliego».
Sin esas dos, el usuario elige entre dejar la señal ocupando sitio en la
bandeja o descartarla para siempre y olvidarla.

Las dos columnas
----------------
``hasta`` (TIMESTAMPTZ, NULL): cuándo deja de aplicar el descarte. ``NULL``
significa «para siempre», que es exactamente lo que hay hoy — por eso las
filas existentes quedan correctas sin backfill y el comportamiento actual no
cambia para nadie.

``accion`` (TEXT, NULL): ``'silenciar'`` o ``'posponer'``. Las dos ocultan la
señal hasta ``hasta``; sólo ``'posponer'`` genera además un recordatorio ese
día. Se guardan por separado de ``hasta`` porque son intenciones distintas y
la telemetría (``radar_triaje.accion``) las distingue: silenciar mide desinterés,
posponer mide trabajo aplazado, y colapsarlas en «tiene fecha» perdería eso.
``NULL`` en las filas antiguas = descarte permanente, sin acción declarada.

``organization_id`` (INTEGER, NULL): la organización desde la que se pospuso.
Sin ella el recordatorio no se puede entregar — ``user_notifications`` se lee
siempre con ámbito de organización, así que una alerta escrita sin ella queda
invisible (el mismo fallo que `services/deadline_reminders.py` documenta en
`_get_watchlist_items`). Se guarda en el descarte y no se deduce después
porque «la organización activa del usuario» es una propiedad del momento en
que decidió, no del momento en que vence el aplazamiento: entre una cosa y la
otra pueden pasar treinta días y un cambio de organización. Queda ``NULL``
para las filas de v76 y para los clientes que descartan por API key sin
sesión; el job los cuenta y no los avisa, en vez de escribir una alerta que
nadie vería.

Por qué no es una tabla nueva
-----------------------------
Silenciar es un descarte con caducidad, no otra cosa. Una tabla aparte
obligaría a cada lectura del Radar a consultar dos sitios y a resolver el
solapamiento (¿qué gana si un expediente está descartado y silenciado?). La
clave primaria ``(user_key, id_externo)`` de v76 ya expresa la regla real: un
usuario tiene **una** decisión por expediente, y la última manda.

Índice
------
``(user_key, hasta)`` parcial sobre las filas con fecha: la consulta caliente
es «los descartes vigentes de este usuario», y las permanentes —que son la
mayoría y no tienen fecha— ya las cubre la PK. Un índice sobre toda la tabla
duplicaría la PK para nada.

Ambas columnas son nullable y sin default, así que ``ADD COLUMN`` es
metadata-only: sin reescritura de filas ni lock largo (mismo razonamiento que
v83 y v85, y el contraejemplo sigue siendo v68).

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v103_radar_dismissals_hasta"
down_revision: str | Sequence[str] | None = "v102_mv_canonicas_clave_inmutable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.add_column(
        "radar_dismissals", sa.Column("hasta", sa.TIMESTAMP(timezone=True), nullable=True)
    )
    op.add_column("radar_dismissals", sa.Column("accion", sa.Text, nullable=True))
    # Sin FK a `organizations`: la tabla no la tiene para `user_key` tampoco, y
    # una organización borrada no debe bloquear el borrado ni resucitar aquí.
    # El job comprueba la vigencia por su cuenta.
    op.add_column("radar_dismissals", sa.Column("organization_id", sa.Integer, nullable=True))
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_radar_dismissals_user_hasta "
        "ON radar_dismissals (user_key, hasta) WHERE hasta IS NOT NULL"
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP INDEX IF EXISTS idx_radar_dismissals_user_hasta")
    op.drop_column("radar_dismissals", "organization_id")
    op.drop_column("radar_dismissals", "accion")
    op.drop_column("radar_dismissals", "hasta")
