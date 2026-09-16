"""v131: ``deleted_at`` en comentarios, tareas y adjuntos de la oportunidad.

Revision ID: v131_borrado_logico_pursuit_hijas
Revises: v130_follows
Create Date: 2026-09-14

Qué corrige
-----------
Las tres tablas hijas de una oportunidad se borraban con ``DELETE``. En un
espacio **compartido** —que es lo que la oportunidad es desde la tenencia por
organización— eso significa que cualquier miembro puede hacer desaparecer el
trabajo de otro sin dejar rastro y sin vuelta atrás:

* ``pursuit_comments`` — el hilo del equipo. Un comentario borrado se lleva la
  razón por la que se decidió lo que se decidió.
* ``pursuit_tasks`` — un compañero borra tu tarea y no queda quién ni cuándo.
* ``pursuit_attachments`` — el pliego anotado que alguien subió.

La asimetría era además llamativa: la oportunidad **sí** lleva su ledger
(``pursuit_events``, v61) y sus hijas no, de modo que el registro de actividad
podía decir «Ana comentó» sin que el comentario existiera ya.

Qué hace
--------
``deleted_at TIMESTAMPTZ NULL`` en las tres, más el índice parcial que las
lecturas necesitan. Nada más: no se borra ni se mueve una fila, y las que hoy
existen siguen con ``deleted_at IS NULL``, que es exactamente «viva».

Lo que va con esto, en los repositorios (``db/repositories/pursuit_*.py``):
``delete`` pasa a ser ``UPDATE ... SET deleted_at = now()`` y **toda** lectura
añade ``deleted_at IS NULL``. Si una lectura se olvida, el usuario ve
reaparecer lo que borró: ``tests/test_pursuit_borrado_logico.py`` recorre las
tres tablas para que ese olvido falle en CI y no en producción.

Índice parcial y no columna en el índice existente
--------------------------------------------------
``WHERE deleted_at IS NULL`` sobre ``(organization_id, pursuit_id)`` cubre la
consulta caliente —listar un hilo— sin indexar las filas muertas, que es la
mayoría de lo que crecerá con el tiempo y lo que nunca se consulta por ahí. El
día que haga falta una papelera («ver borrados»), esa consulta es rara y un
seq scan acotado por organización le vale.

Lo que esta revisión NO hace
----------------------------
- **No caduca nada.** Una fila borrada se queda. La retención por política es
  otra decisión (``scheduler/retention.py``) y no la toma una migración.
- **No borra el blob del adjunto.** Un adjunto marcado como borrado conserva su
  ``blob_key``: es lo que permite deshacer. Quien limpia el almacén de objetos
  es el barrido de huérfanos, y hasta que no exista, borrar el blob aquí haría
  irreversible justo lo que esta revisión viene a hacer reversible.
- **No añade un endpoint de restauración.** La fila está; la UI de papelera es
  producto, no esquema.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v131_borrado_logico_pursuit_hijas"
down_revision: str | Sequence[str] | None = "v130_follows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: ``(tabla, columnas del índice parcial)``. Las tres hijas de la oportunidad.
TABLAS: tuple[tuple[str, str], ...] = (
    ("pursuit_comments", "organization_id, pursuit_id"),
    ("pursuit_tasks", "organization_id, pursuit_id"),
    ("pursuit_attachments", "organization_id, pursuit_id"),
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _existentes() -> list[tuple[str, str]]:
    """Solo las tablas que existen: la revisión debe aplicarse a una base a medias."""
    presentes = set(sa.inspect(op.get_bind()).get_table_names())
    return [(t, cols) for t, cols in TABLAS if t in presentes]


def upgrade() -> None:
    if not _is_postgres():
        return
    for tabla, columnas in _existentes():
        op.execute(f"ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ")
        op.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{tabla}_vivas ON {tabla} ({columnas}) "
            "WHERE deleted_at IS NULL"
        )


def downgrade() -> None:
    """Quita la columna — y con ella la marca de lo borrado.

    Es una pérdida real y por eso se dice: bajar de v131 resucita todo lo que
    se había borrado desde que se aplicó, porque la única señal de que estaba
    muerto era esta columna.
    """
    if not _is_postgres():
        return
    for tabla, _ in _existentes():
        op.execute(f"DROP INDEX IF EXISTS idx_{tabla}_vivas")
        op.execute(f"ALTER TABLE {tabla} DROP COLUMN IF EXISTS deleted_at")
