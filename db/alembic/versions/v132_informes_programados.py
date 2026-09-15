"""v132: preferencia de informe programado por organización (T6).

Revision ID: v132_informes_programados
Revises: v131_borrado_logico_pursuit_hijas
Create Date: 2026-09-15

Qué falta hoy
-------------
El producto sabe calcular el cuadro de Dirección —embudo, win rate por
tecnología y por órgano, vencimientos, actividad del equipo— y sabe enviar
correo, pero nadie ha dicho nunca **cuándo** quiere una organización recibir
todo eso junto. Las únicas preferencias que existen son
``notification_preferences`` (por usuario, tipo y canal) y ``user_event_prefs``
(por usuario y evento): las dos responden «¿me avisas de esto?», ninguna
responde «los lunes a las siete, a estas tres direcciones».

Por eso la preferencia es **de la organización** y no del usuario: el informe
de pipeline habla del trabajo del equipo, y quién lo recibe y qué día lo decide
quien dirige ese equipo, no cada miembro por su cuenta. Lo que sí es del
usuario es el **opt-out**, y ése ya existe: ``notification_preferences`` con
``tipo='informe_semanal'`` y ``canal='email'`` puesto a ``off``. No se duplica
aquí.

Qué crea
--------
``organization_report_schedules``, una fila por organización y tipo de informe:

* ``dia_semana`` 0-6 con **0 = lunes** (``EXTRACT(ISODOW)`` menos uno), no el
  domingo del ``DOW`` de Postgres. Se elige el lunes porque un informe de
  pipeline semanal se lee al empezar la semana, y porque mezclar las dos
  numeraciones en un proyecto es garantía de un informe enviado con seis días
  de desfase.
* ``hora_utc`` 0-23. **UTC y no la hora local de nadie**: la alternativa es
  guardar una zona horaria por organización y arrastrarla hasta el scheduler,
  y el plano de cron (ADR-033) razona en UTC de punta a punta. La interfaz
  puede traducirla al enseñarla.
* ``destinatarios_json``: lista de correos, o ``NULL`` para «los owner y admin
  de la organización». El ``NULL`` no es pereza: es lo que hace que dar de alta
  a un administrador nuevo no exija acordarse de editar el informe.
* ``ultimo_envio_at`` / ``ultimo_estado``: lo que hace la ejecución
  **idempotente**. El paso corre en cada pasada de la pipeline, no una vez al
  día, así que sin esta marca el informe saldría una vez por pasada durante
  toda la hora programada.

``activo`` nace en ``false``. Un informe que empieza a enviarse solo, a una
lista deducida, el día que se despliega la migración, es correo que nadie pidió.

RLS
---
Lleva ``organization_id``, así que nace con la protección de v128 puesta, igual
que ``follows`` en v130: cada migración protege las tablas que crea.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v132_informes_programados"
down_revision: str | Sequence[str] | None = "v131_borrado_logico_pursuit_hijas"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Tablas corporativas que crea esta revisión (ver cabecera §RLS).
TABLAS_CORPORATIVAS: tuple[str, ...] = ("organization_report_schedules",)

#: Vocabulario cerrado de informes. Hoy uno; la columna existe para que el
#: segundo no sea una migración.
TIPOS: tuple[str, ...] = ("pipeline_semanal",)

_PREDICADO_TENANT = (
    "NULLIF(current_setting('app.organization_id', true), '') IS NULL "
    "OR organization_id IS NULL "
    "OR organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer"
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _tablas() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if not _is_postgres() or "organizations" not in _tablas():
        return

    tipos = ", ".join(f"'{t}'" for t in TIPOS)
    op.execute(
        "CREATE TABLE IF NOT EXISTS organization_report_schedules ("
        " id SERIAL PRIMARY KEY,"
        " organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,"
        f" tipo TEXT NOT NULL DEFAULT 'pipeline_semanal' CHECK (tipo IN ({tipos})),"
        # Apagado al nacer: ver la cabecera.
        " activo BOOLEAN NOT NULL DEFAULT false,"
        " dia_semana SMALLINT NOT NULL DEFAULT 0 CHECK (dia_semana BETWEEN 0 AND 6),"
        " hora_utc SMALLINT NOT NULL DEFAULT 7 CHECK (hora_utc BETWEEN 0 AND 23),"
        " destinatarios_json TEXT,"
        " ultimo_envio_at TIMESTAMPTZ,"
        " ultimo_estado TEXT,"
        " created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
        " updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
        " CONSTRAINT uq_report_schedule_org_tipo UNIQUE (organization_id, tipo)"
        ")"
    )
    # El índice de la consulta del job: «qué toca ahora». Parcial sobre
    # `activo` porque la inmensa mayoría de las filas estará apagada mientras
    # el informe sea opcional, y son justo las que nunca se consultan por aquí.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_report_schedules_pendientes "
        "ON organization_report_schedules (dia_semana, hora_utc) WHERE activo"
    )

    op.execute("ALTER TABLE organization_report_schedules ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE organization_report_schedules FORCE ROW LEVEL SECURITY")
    for nombre, modo in (("tenant_scope", "PERMISSIVE"), ("tenant_guard", "RESTRICTIVE")):
        politica = f"{nombre}_organization_report_schedules"
        op.execute(f"DROP POLICY IF EXISTS {politica} ON organization_report_schedules")
        op.execute(
            f"CREATE POLICY {politica} ON organization_report_schedules AS {modo} FOR ALL "
            f"USING ({_PREDICADO_TENANT}) WITH CHECK ({_PREDICADO_TENANT})"
        )


def downgrade() -> None:
    """Tira la tabla. Se pierden las programaciones, no el dato del informe.

    El informe se calcula en cada envío a partir de `pursuits` y `licitaciones`;
    aquí sólo viven el día, la hora y la lista de destinatarios. Volver a
    ponerlos es un formulario, no una recuperación.
    """
    if not _is_postgres():
        return
    op.execute("DROP TABLE IF EXISTS organization_report_schedules")
