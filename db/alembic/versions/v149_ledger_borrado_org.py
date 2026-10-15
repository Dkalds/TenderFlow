"""v149: el ledger de oportunidades deja borrar la organización entera.

Revision ID: v149_ledger_borrado_org
Revises: v148_condiciones_oficiales_codice
Create Date: 2026-10-12

Qué falla hoy
-------------
``pursuit_events`` es un ledger: desde v61 un trigger rechaza cualquier
``UPDATE`` o ``DELETE``. También el que llega por ``ON DELETE CASCADE``, así
que ``POST /organizations/{id}/delete`` (C2.2) acababa en 500 —«pursuit_events
is append-only»— en cuanto la organización tenía una sola oportunidad con
historia, que es cualquier organización que se haya usado. Los tests del
borrado usaban dobles del repositorio y no lo veían; lo destapó el recorrido
de CU-26 (``tests/test_escenario_cuenta_y_acceso.py``).

Qué cambia
----------
El trigger deja pasar el ``DELETE`` de un evento cuya organización **ya no
existe**. Eso solo ocurre en la cascada del borrado de la organización: el
``ON DELETE CASCADE`` borra los hijos después de la fila padre, y el trigger,
que corre en la misma transacción, ya no la ve. Borrar un evento suelto, o una
oportunidad sola (cascada ``pursuits`` → ``pursuit_events``), sigue rechazado;
cualquier ``UPDATE`` también.

Es lo que ADR-030 §D pide: el dato corporativo muere con la organización, y el
ledger de sus oportunidades es dato corporativo. La identidad de una persona se
sigue anonimizando en ``users`` sin reescribir el ledger.

Sin ``SECURITY DEFINER``: la consulta corre con los permisos de quien borra, y
si un ámbito RLS le escondiera la organización también le escondería sus
eventos, así que no abre nada que ese mismo ámbito no viera.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v149_ledger_borrado_org"
down_revision: str | Sequence[str] | None = "v148_condiciones_oficiales_codice"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute(
        "CREATE OR REPLACE FUNCTION public.prevent_pursuit_event_mutation() "
        "RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN "
        "IF TG_OP = 'DELETE' AND NOT EXISTS "
        "(SELECT 1 FROM organizations WHERE id = OLD.organization_id) THEN "
        "RETURN OLD; "
        "END IF; "
        "RAISE EXCEPTION 'pursuit_events is append-only'; "
        "END; $$"
    )
    op.execute("REVOKE EXECUTE ON FUNCTION public.prevent_pursuit_event_mutation() FROM PUBLIC")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute(
        "CREATE OR REPLACE FUNCTION public.prevent_pursuit_event_mutation() "
        "RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN RAISE EXCEPTION 'pursuit_events is append-only'; END; $$"
    )
    op.execute("REVOKE EXECUTE ON FUNCTION public.prevent_pursuit_event_mutation() FROM PUBLIC")
