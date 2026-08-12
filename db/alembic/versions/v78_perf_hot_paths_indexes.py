"""v78: índices de los caminos calientes y limpieza de duplicados.

Revision ID: v78_perf_hot_paths_indexes
Revises: v77_lic_fecha_extraccion_index
Create Date: 2026-08-12

Continúa el trabajo de v77 sobre el mismo ``pg_stat_statements`` de producción.
Medido el 2026-08-12 (contadores desde el 2026-08-03, 1,64 M filas y 972 MB de
heap):

- ``fecha_actualizacion_fuente`` no tenía índice, así que el ``OR`` de
  ``LicitacionRepository.fetch_recent`` —una rama por ``fecha_extraccion``, otra
  por ``fecha_actualizacion_fuente``— no podía resolverse con un ``BitmapOr`` y
  caía a escaneo completo. Es la consulta con más tiempo acumulado de toda la
  base: 405 llamadas, 13,4 s de media, 110,9 s de pico, 5.430 s en total (15 %
  del tiempo de servidor). La sirve el SSE de ``/licitaciones/stream``, que la
  ejecuta por cada aviso de ingesta.
- ``fecha_limite`` tampoco lo tenía, y es por donde cortan dos de los tres
  contadores de ``overview_para_hoy`` (``calientes_hoy`` y ``vencen_48h``):
  ventanas de horas que ahora se resuelven por rango en vez de contando la
  tabla entera.

El índice es **parcial** en ambos casos: las dos columnas son mayormente NULL
—``fecha_actualizacion_fuente`` solo la rellenan las fuentes que publican
actualización, y 1,47 M de filas no tienen plazo propio— así que excluir los
NULL deja un índice mucho más pequeño sin perder ninguna fila que las consultas
puedan usar (``>= %s`` implica ``IS NOT NULL``).

Los otros dos reconcilian deriva entre el linaje de migraciones y la base real.
``pg_indexes`` en producción no los tenía pese a estar declarados desde v21:

- ``idx_lic_importe`` sirve a los rangos ``importe_min``/``importe_max`` de
  ``search_advanced`` y al ``ORDER BY importe DESC LIMIT n`` de
  ``resumen_top_licitaciones``, que hoy ordena 1,64 M filas para devolver diez.
- ``idx_lic_cursor`` **corrige** lo que declaraba v21. Aquel índice era
  ``(fecha_publicacion DESC, id_externo)``, y la paginación keyset de
  ``list_cursor`` ordena por ``fecha_publicacion DESC, id_externo DESC``: con la
  segunda columna en sentido contrario el btree no puede recorrerse en el orden
  pedido y el índice no se usaría. Se crea con los dos sentidos correctos y
  parcial por el filtro que ese endpoint siempre aplica, lo que además lo hace
  válido para el caso de uso de ``idx_lic_fecha_pub_tech`` (v19, tampoco
  presente en producción): misma columna líder y mismo predicado, así que no se
  recrea por separado.

Y se retiran dos índices duplicados de ``adjudicaciones`` creados a mano fuera
de Alembic, que el linter de Supabase reporta como ``duplicate_index``: son
idénticos byte a byte a los que conservan el nombre sin sufijo, y cada uno paga
su parte en cada INSERT del scraper. Por eso ``downgrade()`` no los recrea:
restaurar un duplicado exacto no restaura ninguna capacidad.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v78_perf_hot_paths_indexes"
down_revision: str | Sequence[str] | None = "v77_lic_fecha_extraccion_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _relax_timeouts() -> None:
    """Quita el techo de tiempo y acota la espera por el lock.

    ``migrate.yml`` ya exporta ``PGOPTIONS``, pero eso viaja como parámetro de
    arranque ``options`` de libpq, que es justo el camino que no está llegando
    a las conexiones de la API (ver ``db/connection.py::_make_pg_configure``).
    Si tampoco llega aquí, el valor que regiría es el default de sesión —2 min,
    por debajo de lo que tarda un ``CREATE INDEX CONCURRENTLY`` sobre 972 MB— y
    la migración moriría a medias. Un ``SET`` viaja como sentencia normal y sí
    llega; está verificado contra este pooler.

    ``lock_timeout`` acotado: el CONCURRENTLY solo necesita un lock breve al
    principio y al final, y con el scraper escribiendo cada 4 h es preferible
    fallar rápido y reintentar que encolarse detrás de una transacción larga.
    """
    op.execute("SET statement_timeout = 0")
    op.execute("SET lock_timeout = '30s'")


def upgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        _relax_timeouts()
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lic_fecha_act_fuente "
            "ON licitaciones (fecha_actualizacion_fuente) "
            "WHERE fecha_actualizacion_fuente IS NOT NULL"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lic_fecha_limite "
            "ON licitaciones (fecha_limite) "
            "WHERE fecha_limite IS NOT NULL"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lic_importe ON licitaciones (importe)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lic_cursor "
            "ON licitaciones (fecha_publicacion DESC, id_externo DESC) "
            "WHERE tecnologia IS NOT NULL AND tecnologia <> ''"
        )
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS adjudicaciones_importe_adjudicado_idx1")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS adjudicaciones_n_ofertas_recibidas_idx1")


def downgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        _relax_timeouts()
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_lic_cursor")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_lic_importe")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_lic_fecha_limite")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_lic_fecha_act_fuente")
