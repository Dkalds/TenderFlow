"""v76: tabla ``radar_dismissals`` (descarte de señales del Radar, por usuario).

Revision ID: v76_radar_dismissals
Revises: v75_users_admin_granted_by
Create Date: 2026-08-07

El descarte de señales del Radar vivía en ``React.useState``: el usuario triaba
las 24 señales de la bandeja, recargaba, y volvían las 24. Viola el invariante 2
de ``docs/frontend-data-invariants.md`` ("el estado de usuario es server-side"),
y ni siquiera llegaba a ``localStorage``, que ese documento ya considera
insuficiente.

Clave primaria compuesta ``(user_key, id_externo)``: un usuario descarta una
licitación como mucho una vez, así que el INSERT es idempotente por
construcción (``ON CONFLICT DO NOTHING``) y no hace falta una secuencia.

``user_key`` es la clave opaca por usuario que ya usan ``saved_filters`` y
``watchlist_favorites`` (email de sesión o hash de API key, ver
``api/routes/watchlist_items.py``), no ``users.id``: mantiene el mismo modelo de
tenencia que el resto de estado de usuario.

No lleva FK a ``licitaciones``: el Radar puede descartar una señal que después
se depure del corpus, y en ese caso el descarte deja de tener efecto por sí solo
(nadie lo consulta) sin bloquear el borrado de la licitación.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v76_radar_dismissals"
down_revision: str | Sequence[str] | None = "v75_users_admin_granted_by"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("NOW()")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _protect_table(table: str) -> None:
    """Cierra Data API y conserva acceso del rol runtime de la aplicación.

    Mismo tratamiento que las tablas per-user de v61: sin esto, la tabla queda
    expuesta a los roles ``anon``/``authenticated`` de Supabase.
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

    op.create_table(
        "radar_dismissals",
        sa.Column("user_key", sa.Text, nullable=False),
        sa.Column("id_externo", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.PrimaryKeyConstraint("user_key", "id_externo", name="pk_radar_dismissals"),
    )
    # La única consulta de lectura es "los descartes de este usuario"; la PK
    # compuesta ya la sirve por su prefijo, así que no hace falta índice extra.
    _protect_table("radar_dismissals")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.drop_table("radar_dismissals")
