"""v89: tabla ``solicitudes_acceso`` (peticiones de acceso desde la landing).

Revision ID: v89_solicitudes_acceso
Revises: v88_documentos_source_hash
Create Date: 2026-08-23

El CTA "Solicita acceso" de la landing moría en un ``mailto:``: sin registro,
sin cola y sin forma de saber cuántas solicitudes llegan ni qué pasó con ellas.
Si el visitante no tenía cliente de correo configurado —lo normal en un
escritorio corporativo con webmail— el enlace no hacía nada en absoluto.

Esta tabla es la cola. **No cambia cómo se concede el acceso**: la allowlist
sigue viviendo en ``OAUTH_ALLOWED_EMAILS``/``OAUTH_ALLOWED_DOMAINS``
(``shared/auth_core.py``), así que aprobar sigue siendo editar variables de
entorno y redesplegar. Mover esa allowlist a base de datos es otro cambio, con
su propio análisis de seguridad: aquí sólo se deja de perder la petición.

``estado`` como texto libre con CHECK y no como enum de Postgres: los enum
nativos obligan a una migración para añadir un valor, y el conjunto de estados
de una cola de revisión manual es exactamente lo que se retoca sobre la marcha.

**Sin IP ni user-agent.** El rate limiting opera en memoria sobre la IP y no
necesita persistirla; guardarla aquí sería recoger un dato personal que nadie
va a consultar, justo lo contrario del principio de minimización. Lo único
personal que se guarda es lo que la persona escribe a sabiendas, más la marca
temporal de su consentimiento explícito.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v89_solicitudes_acceso"
down_revision: str | Sequence[str] | None = "v88_documentos_source_hash"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("NOW()")

ESTADOS = ("pendiente", "atendida", "descartada")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _protect_table(table: str) -> None:
    """Cierra Data API y conserva acceso del rol runtime de la aplicación.

    Mismo tratamiento que las tablas per-user de v61/v76: sin esto, la tabla
    queda expuesta a los roles ``anon``/``authenticated`` de Supabase — y ésta
    contiene datos de contacto de personas que han escrito desde una página
    pública, así que el descuido sería peor que en las otras.
    """
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN "
        f"REVOKE ALL ON TABLE {table} FROM anon; "
        "END IF; "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN "
        f"REVOKE ALL ON TABLE {table} FROM authenticated; "
        "END IF; "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tenderflow_app') THEN "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO tenderflow_app; "
        f"CREATE POLICY tenderflow_app_full_access ON {table} "
        "FOR ALL TO tenderflow_app USING (true) WITH CHECK (true); "
        "END IF; END $$"
    )


def upgrade() -> None:
    if not _is_postgres():
        return

    estados_sql = ", ".join(f"'{e}'" for e in ESTADOS)
    op.create_table(
        "solicitudes_acceso",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("empresa", sa.Text, nullable=True),
        sa.Column("mensaje", sa.Text, nullable=True),
        # De qué CTA vino. La misma atribución que ya viajaba en el `utm_content`
        # de la landing, aquí sin depender de que el navegador ejecute nada.
        sa.Column("origen", sa.Text, nullable=True),
        sa.Column("estado", sa.Text, nullable=False, server_default="pendiente"),
        # Marca temporal del consentimiento explícito: la casilla es obligatoria
        # en el formulario y sin ella el endpoint rechaza el envío.
        sa.Column("consentimiento_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.CheckConstraint(f"estado IN ({estados_sql})", name="ck_solicitudes_acceso_estado"),
    )
    # La única lectura es el panel: pendientes primero, más recientes arriba.
    op.create_index(
        "ix_solicitudes_acceso_estado_created",
        "solicitudes_acceso",
        ["estado", sa.text("created_at DESC")],
    )
    _protect_table("solicitudes_acceso")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.drop_index("ix_solicitudes_acceso_estado_created", table_name="solicitudes_acceso")
    op.drop_table("solicitudes_acceso")
