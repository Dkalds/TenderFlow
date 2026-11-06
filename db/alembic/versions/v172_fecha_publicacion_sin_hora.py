"""v172: ``licitaciones.fecha_publicacion`` sin hora en las filas que la llevan.

Revision ID: v172_fecha_publicacion_sin_hora
Revises: v171_access_grants_revoked_by
Create Date: 2026-11-06

Qué resuelve
------------
Todos los conectores escriben ``fecha_publicacion`` como ``YYYY-MM-DD``, pero
en producción quedan 307 filas de ``placsp`` (medido el 2026-11-06; publicadas
entre 2018-07 y 2026-04, ninguna re-ingerida desde el 2026-09-04) con el
instante entero: ``2026-04-16T19:30:59.268+02:00``. La columna es texto, así
que ``fecha_publicacion <= '2026-04-16'`` las deja fuera de su propio día en
cualquier filtro «hasta». El código de los filtros pasa a una cota exclusiva al
día siguiente en el mismo cambio; esta revisión deja además el dato con la
forma que tiene el resto, para que ordenar o agrupar por la columna no tenga
que saber de la excepción.

Se queda con los diez primeros caracteres: la fecha **del propio texto**, que
es la del calendario de quien la publicó (la de ``+02:00``), y no la UTC.

La sombra ``fecha_publicacion_ts`` (``v133``) no tiene trigger en
``licitaciones`` —la escribe la ingesta—, así que se recalcula aquí con la
misma ``nucleo_iso_a_timestamptz`` para que texto y sombra no discrepen.

Coste: un ``UPDATE`` de unas 300 filas por un filtro sobre la propia columna.
Sin DDL, sin bloqueo de tabla.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v172_fecha_publicacion_sin_hora"
down_revision: str | Sequence[str] | None = "v171_access_grants_revoked_by"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Un instante ISO completo (``YYYY-MM-DDT…``); deja en paz lo que no lo sea.
_CON_HORA = r"^\d{4}-\d{2}-\d{2}T"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute(
        "UPDATE licitaciones "
        "SET fecha_publicacion = left(fecha_publicacion, 10), "
        "    fecha_publicacion_ts = nucleo_iso_a_timestamptz(left(fecha_publicacion, 10)) "
        f"WHERE fecha_publicacion ~ '{_CON_HORA}'"
    )


def downgrade() -> None:
    """No hay vuelta atrás, y se dice.

    La hora que se quita no se guardó en ningún otro sitio. Bajar de v172 deja
    las fechas sin hora, que es como las escriben todos los conectores.
    """
    return
