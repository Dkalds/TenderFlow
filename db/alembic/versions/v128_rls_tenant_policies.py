"""v128: RLS por tenant con variable de transacción (defensa en profundidad).

Revision ID: v128_rls_tenant_policies
Revises: v127_pursuit_attachments
Create Date: 2026-09-14

Qué cierra
----------
Hasta aquí el aislamiento entre organizaciones vivía **solo** en la capa de
aplicación: ``api/tenancy.py`` resuelve la organización y cada repositorio
filtra por ``organization_id``. Un ``WHERE`` olvidado en un repositorio nuevo
devolvía las filas de otro cliente sin que nada lo detectara. La RLS de
``v52`` no ayudaba: se habilitó sin ``FORCE`` y sin políticas, así que el rol
dueño la bypassa y el rol runtime (``tenderflow_app``) tiene
``tenderflow_app_full_access USING (true)`` en cada tabla — cierra la Data API
de Supabase, no separa tenants.

Esta revisión añade la segunda capa (ADR-034): dentro de una petición con
organización fijada, las filas de otras organizaciones **no existen** para la
base de datos, y un INSERT/UPDATE que las produzca falla. La aplicación sigue
siendo el control primario; esto es el respaldo.

Cómo
----
``db/connection.py`` emite ``SET LOCAL app.organization_id = '<id>'`` como
primera sentencia de cada transacción cuando ``shared.tenant_context`` tiene
organización. Las políticas leen ese GUC::

    NULLIF(current_setting('app.organization_id', true), '') IS NULL
    OR organization_id IS NULL
    OR organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer

El primer término es el **paso franco sin ámbito**: scheduler, scripts,
migraciones, backups y tests sin scope siguen viendo todo. El ``NULLIF`` con
cadena vacía no es adorno: cuando un GUC placeholder se fijó alguna vez con
``SET LOCAL`` en una sesión, al cerrar la transacción vuelve a ``''``, no a
NULL, y una conexión del pool reutilizada lo trae así. Y va **dentro del
cast**, no como un ``OR ... = ''`` aparte, porque Postgres no garantiza el
orden de evaluación de los operandos de ``OR``: el planificador evaluó primero
``''::integer`` y la lectura sin ámbito reventaba con ``invalid input syntax
for type integer`` (lo fija ``test_sin_ambito_se_ve_todo_incluso_tras_una_transaccion_acotada``).
El segundo término conserva visibles las filas legadas con ``organization_id
NULL`` que ``db/tenancy_backfill.py`` inventaría y ``claim_legacy_rows`` va
adjudicando.

Dos políticas por tabla, y por qué no basta una
-----------------------------------------------
- ``tenant_scope_<tabla>`` — **permisiva**. Es la que *concede* acceso, con
  el predicado, al rol dueño (sujeto a RLS por el ``FORCE`` de abajo) y a
  cualquier rol que no tenga otra política.
- ``tenant_guard_<tabla>`` — **restrictiva**, mismo predicado. Las permisivas
  se combinan con OR: sobre ``tenderflow_app``, que ya tiene
  ``tenderflow_app_full_access USING (true)``, una permisiva más sería
  ``true OR predicado`` y no cerraría nada. Las restrictivas se combinan con
  AND, así que esta sí acota al rol runtime de producción. No puede ir sola:
  una restrictiva nunca concede acceso, y el dueño bajo ``FORCE`` sin
  ninguna permisiva quedaría en deny-all.

``FORCE ROW LEVEL SECURITY`` somete también al dueño de la tabla. Los
superusuarios y los roles ``BYPASSRLS`` siguen exentos por diseño de Postgres:
en la suite de tests el rol es superusuario, por eso
``tests/test_rls_tenant_scope_integration.py`` prueba las políticas con un rol
sonda que emula a ``tenderflow_app``.

Qué tablas
----------
Las **corporativas** con ``organization_id``: el dato acompaña a la
organización (ADR-030 §D). Quedan fuera, a propósito, ``organizations``,
``organization_memberships`` y ``organization_invitations`` (resolver una
membresía exige ver todas las organizaciones del usuario), ``domain_events`` y
``jobs`` (el outbox y la cola los consume el worker sin ámbito) y las tablas
de auditoría. Una tabla nueva con ``organization_id`` no queda cubierta por
arte de magia: su migración debe añadir ``FORCE`` y las dos políticas, o
declararse excluida en el test estructural que enumera ``information_schema``.

Reversible: ``downgrade`` borra las políticas y quita ``FORCE``. El ``ENABLE``
de ``v52`` se conserva.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v128_rls_tenant_policies"
down_revision: str | Sequence[str] | None = "v127_pursuit_attachments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Tablas corporativas con ``organization_id`` a la fecha de esta revisión.
#: Misma lista que ``tests/test_rls_tenant_scope_integration.py`` contrasta
#: contra ``information_schema``.
TABLAS_CORPORATIVAS: tuple[str, ...] = (
    "pursuits",
    "pursuit_tasks",
    "pursuit_comments",
    "pursuit_attachments",
    "pursuit_events",
    "go_no_go_scores",
    "go_no_go_weights",
    "cuentas_objetivo",
    "etiquetas",
    "etiquetas_aplicadas",
    "contratos_cartera",
    "plantillas_organizacion",
    "plantillas_aplicadas",
    "organization_nifs",
    "organization_certifications",
    "organization_references",
    "organization_revenues",
    "organization_team_profiles",
    "webhooks",
    "watchlist_items",
    "watchlist_rules",
    "watchlist_cpv",
    "watchlist_empresas",
    "saved_filters",
    "radar_dismissals",
    "user_notifications",
    "user_profiles",
    "notification_preferences",
    "api_keys",
)

#: Predicado compartido por USING y WITH CHECK. Ver la cabecera: el ``NULLIF``
#: va dentro del cast porque el orden de evaluación del ``OR`` no está
#: garantizado.
PREDICADO_TENANT = (
    "NULLIF(current_setting('app.organization_id', true), '') IS NULL "
    "OR organization_id IS NULL "
    "OR organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer"
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _tablas_presentes() -> list[str]:
    """Solo las que existen: la revisión debe poder aplicarse a una base a medias."""
    existentes = set(sa.inspect(op.get_bind()).get_table_names())
    return [t for t in TABLAS_CORPORATIVAS if t in existentes]


def _proteger(table: str) -> None:
    # Los nombres salen de la constante de arriba, nunca de entrada externa.
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_scope_{table} ON {table}")
    op.execute(
        f"CREATE POLICY tenant_scope_{table} ON {table} AS PERMISSIVE FOR ALL "
        f"USING ({PREDICADO_TENANT}) WITH CHECK ({PREDICADO_TENANT})"
    )
    op.execute(f"DROP POLICY IF EXISTS tenant_guard_{table} ON {table}")
    op.execute(
        f"CREATE POLICY tenant_guard_{table} ON {table} AS RESTRICTIVE FOR ALL "
        f"USING ({PREDICADO_TENANT}) WITH CHECK ({PREDICADO_TENANT})"
    )


def _desproteger(table: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_guard_{table} ON {table}")
    op.execute(f"DROP POLICY IF EXISTS tenant_scope_{table} ON {table}")
    op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    if not _is_postgres():
        return
    for table in _tablas_presentes():
        _proteger(table)


def downgrade() -> None:
    if not _is_postgres():
        return
    for table in _tablas_presentes():
        _desproteger(table)
