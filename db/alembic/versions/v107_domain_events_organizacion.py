"""v107: ``domain_events`` pasa a ser el outbox del producto.

Plan de arquitectura 2026-09 v2, S4.1. Hasta aquí la tabla existía como log
append-only y solo la escribían ``services/tech_signal.py`` y la invalidación
de caché: no era el backbone de nada. Esta revisión le añade lo que le falta
para serlo.

- ``organization_id``: el evento es de alguien. Sin esta columna el
  despachador no podría decidir a qué webhooks de qué organización sale un
  ``pursuit.created``, y el aislamiento entre organizaciones se resolvería
  releyendo la tabla origen de cada evento.
- ``dispatched_at``: la marca de «ya repartido». ``NULL`` es la cola, y el
  índice parcial la hace barata de leer aunque la tabla crezca sin límite (es
  append-only: nunca se purga por diseño).
- ``domain_event_dispatches``: el único por ``(event_id, canal)`` es la
  idempotencia del abanico. El despachador reclama el par antes de entregar,
  así que interrumpirlo a mitad y reintentar el evento entero no duplica las
  entregas ya hechas.
- ``user_event_prefs``: la preferencia de correo por usuario y tipo de evento
  (S4.6, ``immediate | daily | off``). Vive en su tabla y no en un JSON de
  ``users`` porque el despachador la consulta por ``(user_key, event_type)``
  en el camino caliente de cada entrega.

Aditiva y reentrante: todo va con ``IF NOT EXISTS``, así que aplicarla sobre
una base que ya tenga alguna de las piezas no falla.

Revision ID: v107_domain_events_organizacion
Revises: v106_jobs
Create Date: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v107_domain_events_organizacion"
down_revision: str | Sequence[str] | None = "v106_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE domain_events ADD COLUMN IF NOT EXISTS organization_id INTEGER")
    op.execute("ALTER TABLE domain_events ADD COLUMN IF NOT EXISTS dispatched_at TEXT")

    # Índice PARCIAL: lo que se consulta en caliente es la cola (``NULL``), que
    # en régimen permanente son decenas de filas sobre una tabla que solo
    # crece. Un índice completo sobre `dispatched_at` indexaría sobre todo lo
    # ya despachado, que nadie vuelve a mirar.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_domain_events_pendientes "
        "ON domain_events(id) WHERE dispatched_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_domain_events_organizacion "
        "ON domain_events(organization_id, id) WHERE organization_id IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS domain_event_dispatches (
            id         SERIAL PRIMARY KEY,
            event_id   INTEGER NOT NULL,
            canal      TEXT    NOT NULL,
            created_at TEXT    NOT NULL,
            UNIQUE (event_id, canal)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_domain_event_dispatches_evento "
        "ON domain_event_dispatches(event_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_event_prefs (
            id         SERIAL PRIMARY KEY,
            user_key   TEXT NOT NULL,
            event_type TEXT NOT NULL,
            modo       TEXT NOT NULL DEFAULT 'immediate',
            updated_at TEXT NOT NULL,
            UNIQUE (user_key, event_type)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_event_prefs")
    op.execute("DROP INDEX IF EXISTS idx_domain_event_dispatches_evento")
    op.execute("DROP TABLE IF EXISTS domain_event_dispatches")
    op.execute("DROP INDEX IF EXISTS idx_domain_events_organizacion")
    op.execute("DROP INDEX IF EXISTS idx_domain_events_pendientes")
    op.execute("ALTER TABLE domain_events DROP COLUMN IF EXISTS dispatched_at")
    op.execute("ALTER TABLE domain_events DROP COLUMN IF EXISTS organization_id")
