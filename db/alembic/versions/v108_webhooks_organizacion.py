"""v108: los webhooks dejan de ser un recurso global del administrador.

Plan de arquitectura 2026-09 v2, S4.2 y S4.3. Hasta aquí ``webhooks`` no tenía
dueño: todas sus rutas exigían ``require_admin`` porque cualquier fila era
visible para cualquier integración registrada. Un equipo que quisiera su propio
canal tenía que pedírselo al administrador de la instancia.

- ``organization_id`` y ``created_by`` dan dueño a la fila. Nullable a
  propósito: las filas anteriores a esta revisión no pertenecen a ninguna
  organización y convertirlas a la fuerza sería inventarse un propietario. El
  código las trata como **globales** —solo visibles desde la vista de ``/ops``—
  y las nuevas nacen siempre con organización.
- ``formato`` implementa D13: plantillas de payload sobre el webhook genérico
  (``json``, ``slack_blocks``, ``teams_adaptive_card``), no integraciones OAuth
  por plataforma. ``json`` de defecto, que es exactamente lo que reciben hoy
  los receptores existentes: su cuerpo no cambia.

El ``CHECK`` sobre ``formato`` es deliberado y va contra el criterio de v93
para ``banda`` (allí el vocabulario era de producto y podía cambiar). Aquí los
tres valores son los tres renderers que existen en ``shared/events.py``: un
cuarto valor en la columna sería un webhook que no se sabe serializar.

Revision ID: v108_webhooks_organizacion
Revises: v107_domain_events_organizacion
Create Date: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v108_webhooks_organizacion"
down_revision: str | Sequence[str] | None = "v107_domain_events_organizacion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FORMATOS = ("json", "slack_blocks", "teams_adaptive_card")


def upgrade() -> None:
    op.execute("ALTER TABLE webhooks ADD COLUMN IF NOT EXISTS organization_id INTEGER")
    op.execute("ALTER TABLE webhooks ADD COLUMN IF NOT EXISTS created_by INTEGER")
    op.execute("ALTER TABLE webhooks ADD COLUMN IF NOT EXISTS formato TEXT NOT NULL DEFAULT 'json'")

    valores = ", ".join(f"'{f}'" for f in _FORMATOS)
    # `DROP` + `ADD` y no un `ADD ... IF NOT EXISTS` (que Postgres no tiene
    # para constraints): así la revisión es reentrante sin depender del
    # catálogo del sistema.
    op.execute("ALTER TABLE webhooks DROP CONSTRAINT IF EXISTS ck_webhooks_formato")
    op.execute(
        f"ALTER TABLE webhooks ADD CONSTRAINT ck_webhooks_formato CHECK (formato IN ({valores}))"
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_webhooks_organizacion "
        "ON webhooks(organization_id) WHERE organization_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_webhooks_organizacion")
    op.execute("ALTER TABLE webhooks DROP CONSTRAINT IF EXISTS ck_webhooks_formato")
    op.execute("ALTER TABLE webhooks DROP COLUMN IF EXISTS formato")
    op.execute("ALTER TABLE webhooks DROP COLUMN IF EXISTS created_by")
    op.execute("ALTER TABLE webhooks DROP COLUMN IF EXISTS organization_id")
