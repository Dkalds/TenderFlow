"""v142: índices cubrientes para la analítica de Mercado y autovacuum de ``licitaciones``.

Por qué
-------
``licitaciones`` pasó de ~47k filas a ~713k con la carga completa de PSCP, y
ocupa ~870 MB de heap en un Supabase Micro (``shared_buffers`` de 256 MB, E/S
limitada). Una agregación sin filtros que la recorre entera tarda ~15 s
(medido el 2026-09-25: ``geography_by_ccaa``, 87k páginas leídas de disco), y
las vistas de Mercado encadenan varias: ``/analytics/trends?group_by=month``
tardaba 20-72 s y ``/analytics/organos`` moría por ``statement_timeout``.

Esas agregaciones leen una docena de columnas estrechas de filas de ~1,2 KB.
Un índice que las lleve todas deja a Postgres responder con un Index Only
Scan, sin tocar el heap: es la tabla estrecha que la analítica necesita, sin
una segunda fuente que refrescar. Con índices hipotéticos (``hypopg``) sobre
producción el planificador ya elige ese camino para ``geography_by_ccaa``,
``trends_daily`` y las tres consultas de órganos, y con ``?tecnologia=SAP`` el
del índice de tecnología de abajo.

Qué crea
--------
- ``idx_lic_analitica``: ``(fecha_publicacion) INCLUDE (...)``. La fecha como
  clave sirve a los filtros de rango de fechas y a ``iso_guard``; las
  incluidas son :data:`COLUMNAS_CUBIERTAS`. Para toda la tabla, sin ``q`` ni
  módulos SAP (que leen ``titulo``).
- ``idx_lic_tecnologia_cubriente``: las mismas columnas para las ~10k filas
  con ``tecnologia``, con el predicado ``WHERE tecnologia IS NOT NULL`` que
  implica la guarda de :func:`db.sql_fragments.tecnologia_en_csv_sql`. Con
  ``?tecnologia=SAP`` la consulta ya va por ``idx_lic_tecnologia``, pero lee
  del heap una página por fila etiquetada, repartidas por toda la tabla: 4-7 s
  cuando no están en caché. Con este índice ya no lee el heap para cada fila.

``idx_lic_tecnologia`` **no se toca**: en producción es ``(tecnologia,
fecha_publicacion) WHERE tecnologia IS NOT NULL`` y la cadena de Alembic (v21)
lo crea como ``(tecnologia)``, así que un reemplazo no tendría un estado
anterior único al que volver. Queda como está; el planificador elige.

Autovacuum
----------
Un Index Only Scan solo se ahorra el heap en las páginas marcadas como
visibles para todos, y esa marca la pone ``VACUUM``. Con los valores por
defecto (20 % de filas muertas) el autovacuum de esta tabla salta cada varios
días: el 2026-09-25 el 13 % de las páginas estaban sin marcar, y el 62 % de las
filas etiquetadas, que son las que el scraper reescribe en cada pasada. Al 2 %
salta tras unas ~14k filas muertas o insertadas, del orden de una o dos pasadas
del scraper. El precio es más E/S de fondo: cada vacuum repasa los índices de la
tabla.

Cómo
----
``CONCURRENTLY`` porque el scraper escribe en la tabla mientras se construye, y
por eso dentro de ``autocommit_block``. ``statement_timeout = 0`` porque
construir sobre ~713k filas pasa de los 30 s del rol, como en ``v101``.

**Si un ``CREATE INDEX CONCURRENTLY`` falla a medias deja un índice
``INVALID``** que el ``IF NOT EXISTS`` de un reintento daría por bueno (ver
``v134``). Después de aplicar, comprobar ``pg_index.indisvalid`` de los dos
índices y su tamaño con ``pg_relation_size``.

``tests/test_v142_indices_analitica.py`` fija el DDL y comprueba que las
agregaciones sin filtros de Mercado no leen ninguna columna fuera de
:data:`COLUMNAS_CUBIERTAS`: una columna nueva en esas consultas devolvería el
plan al Seq Scan sin que fallara nada.

DIALECT-GUARDED: solo actúa en Postgres.

Revision ID: v142_lic_indices_analitica
Revises: v141_tasas_anulacion_organo
Create Date: 2026-09-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v142_lic_indices_analitica"
down_revision: str | Sequence[str] | None = "v141_tasas_anulacion_organo"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDICE_ANALITICA = "idx_lic_analitica"
INDICE_TECNOLOGIA = "idx_lic_tecnologia_cubriente"

#: Columnas que las agregaciones de Mercado leen además de la clave. Se congelan
#: aquí, como toda revisión, en vez de derivarse de las consultas.
COLUMNAS_CUBIERTAS: tuple[str, ...] = (
    "importe",
    "estado",
    "ccaa",
    "provincia",
    "cpv",
    "tipo_contrato",
    "organo_id",
    "organo_contratacion",
    "tecnologia",
)

#: Umbrales de autovacuum de la tabla (fracción de filas).
AUTOVACUUM: dict[str, str] = {
    "autovacuum_vacuum_scale_factor": "0.02",
    "autovacuum_vacuum_insert_scale_factor": "0.02",
}


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    incluidas = ", ".join(COLUMNAS_CUBIERTAS)
    # `tecnologia` ya es clave del segundo índice: no se repite en el INCLUDE.
    incluidas_tecnologia = ", ".join(c for c in COLUMNAS_CUBIERTAS if c != "tecnologia")
    ajustes = ", ".join(f"{k} = {v}" for k, v in AUTOVACUUM.items())
    with op.get_context().autocommit_block():
        op.execute("SET statement_timeout = 0")
        op.execute("SET lock_timeout = '30s'")
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDICE_ANALITICA} "
            f"ON licitaciones (fecha_publicacion) INCLUDE ({incluidas})"
        )
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDICE_TECNOLOGIA} "
            f"ON licitaciones (tecnologia, fecha_publicacion) INCLUDE ({incluidas_tecnologia}) "
            "WHERE tecnologia IS NOT NULL"
        )
        op.execute(f"ALTER TABLE licitaciones SET ({ajustes})")


def downgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '30s'")
        op.execute(f"ALTER TABLE licitaciones RESET ({', '.join(AUTOVACUUM)})")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDICE_TECNOLOGIA}")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDICE_ANALITICA}")
