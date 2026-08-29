"""v94: vista materializada de contratos canónicos publicables.

La otra mitad del arreglo que ``v92`` dejó a medias, y la que el comentario de
``fila_canonica_sql`` nombraba desde el principio: *«El arreglo de verdad es un
índice funcional sobre la clave (o una vista materializada)»*.

Por qué no bastaba con el índice ni con agrupar
-----------------------------------------------
``v92`` puso el índice y arregló las consultas con ``LIMIT``. Para los agregados
—``contar``, los dos hubs, ``ultima_incorporacion``— se pasó después a resolver
la canónica agrupando, y medido una vez daba 9,1 s. **Ese número era el mejor
caso, no el caso.** El plan es paralelo y la instancia tiene
``max_worker_processes = 6`` en total, así que el worker no está garantizado:
medido contra producción el 2026-08-28, los mismos endpoints alternaban entre
18-22 s (con worker) y >30 s (sin él), o sea entre 200 y 500 según la suerte.
Un 500 intermitente en la superficie que rastrea Googlebot es peor que uno
limpio, porque no es diagnosticable.

Materializar mueve ese coste de **cada petición** a **una vez por pasada del
pipeline**: ~10 s de construcción, contra 415k filas leídas en milisegundos.

Las SEIS superficies pasan a leer de aquí, no sólo las cuatro que fallaban
--------------------------------------------------------------------------
Es lo que obliga la coherencia, no un afán de uniformidad. Si ``listar`` siguiera
en vivo y ``contar`` leyera la vista, un expediente recién ingerido aparecería en
el listado sin estar contado, y el hub paginaría hacia una página que no existe —
exactamente el error de cobertura de Search Console que el docstring de
``db/repositories/publico.py`` lleva advirtiendo desde el principio. La frescura
tiene que ser **uniforme** en toda la superficie, aunque sea menor.

El contrato de frescura, explícito
-----------------------------------
La vista va tan fresca como el último refresco, que corre al final de la pasada
de ingesta (cada 4 h). Es MENOS fresco que antes y hay que decirlo, pero encaja
con lo que ya había: la superficie pública se sirve con ISR cacheado una hora en
el CDN, así que el visitante nunca veía el instante actual de todos modos.

Lo que NO se degrada es la ficha individual: ``ficha`` no aplica el filtro de
canónica —asimetría deliberada y ya documentada— y sigue leyendo ``licitaciones``
en vivo. Un expediente nuevo tiene página desde el primer momento; lo que tarda
en aparecer es en los listados y en los recuentos.

``REFRESH ... CONCURRENTLY`` y por eso el índice único
------------------------------------------------------
Sin ``CONCURRENTLY`` el refresco toma un ``AccessExclusiveLock`` y la superficie
pública devuelve errores durante los ~10 s que dura. Con él, las lecturas siguen
sirviendo la versión anterior mientras se construye la nueva — que es justo el
comportamiento que hace aceptable refrescar sobre una BD viva. ``CONCURRENTLY``
exige un índice ÚNICO sobre la vista, y de ahí el de ``id_externo``, que además
es el que resuelve el ``ORDER BY id_externo LIMIT/OFFSET`` del sitemap.

DIALECT-GUARDED: solo actúa en Postgres.

Revision ID: v94_mv_licitaciones_canonicas
Revises: v93_decisiones_guardan_su_score
Create Date: 2026-08-29
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v94_mv_licitaciones_canonicas"
down_revision: str | Sequence[str] | None = "v93_decisiones_guardan_su_score"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VISTA = "licitaciones_canonicas"

#: Cuerpo congelado de la vista. Es la gemela literal de lo que compone
#: ``db/repositories/publico.py`` a partir de ``_BASE_WHERE``,
#: ``clave_canonica_agrupable_sql`` y ``orden_canonico_sql``.
#:
#: Se congela por el mismo criterio que v91 y v92 —una migración describe lo que
#: se le hizo a estos datos en esta fecha— y con el mismo precio: si se separa de
#: su gemela, la vista deja de describir lo que las consultas creen que describe
#: y la superficie serviría un conjunto distinto del que cuenta.
#: ``tests/test_mv_canonicas_definicion.py`` compara las dos cadenas.
_CUERPO = (
    "SELECT DISTINCT ON "
    "(coalesce(md5(nullif(lower(translate(btrim(coalesce(l.organo_contratacion, '')), "
    "'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ', "
    "'aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC')), '') || chr(31) || CASE WHEN l.cpv ~ "
    "'^[0-9]{4}' THEN substr(l.cpv, 1, 4) ELSE '' END || chr(31) || "
    "substr(coalesce(l.fecha_publicacion, l.fecha_extraccion, ''), 1, 7) || chr(31) || "
    "lower(btrim(l.titulo))), 'r:' || l.id_externo)) l.id_externo, l.titulo, l.ccaa, l.cpv, "
    "l.fecha_publicacion, l.fecha_extraccion FROM licitaciones l WHERE l.titulo IS NOT NULL "
    "AND length(trim(l.titulo)) >= 25 AND (l.importe IS NOT NULL OR "
    "length(coalesce(l.descripcion, '')) >= 200) AND l.id_externo NOT IN (SELECT "
    "licitacion_id FROM licitaciones_duplicados WHERE status = 'confirmed') ORDER BY "
    "coalesce(md5(nullif(lower(translate(btrim(coalesce(l.organo_contratacion, '')), "
    "'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ', "
    "'aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC')), '') || chr(31) || CASE WHEN l.cpv ~ "
    "'^[0-9]{4}' THEN substr(l.cpv, 1, 4) ELSE '' END || chr(31) || "
    "substr(coalesce(l.fecha_publicacion, l.fecha_extraccion, ''), 1, 7) || chr(31) || "
    "lower(btrim(l.titulo))), 'r:' || l.id_externo), (l.fuente <> 'placsp'), "
    "coalesce(l.fecha_publicacion, '9999'), coalesce(l.fecha_extraccion, '9999'), "
    "l.id_externo"
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    # `statement_timeout = 0`: construir la vista recorre y ordena ~590k filas
    # publicables (~10 s medidos), muy por encima de los 30 s del rol de la API
    # pero dentro de lo que un despliegue puede esperar una sola vez.
    op.execute("SET statement_timeout = 0")
    op.execute(f"CREATE MATERIALIZED VIEW IF NOT EXISTS {VISTA} AS {_CUERPO}")

    # ÚNICO y no a secas: es el requisito de `REFRESH ... CONCURRENTLY`, sin el
    # cual cada refresco bloquearía la superficie pública mientras dura.
    op.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{VISTA}_id_externo ON {VISTA} (id_externo)")
    # Sirve al `ORDER BY fecha_publicacion DESC NULLS LAST, id_externo` del
    # listado, que es su orden de portada.
    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{VISTA}_fecha_pub "
        f"ON {VISTA} (fecha_publicacion DESC NULLS LAST, id_externo)"
    )
    # Los dos hubs agrupan por estas columnas. Con 415k filas un escaneo ya es
    # barato, pero el índice deja el `GROUP BY` en un index-only scan.
    op.execute(f"CREATE INDEX IF NOT EXISTS idx_{VISTA}_ccaa ON {VISTA} (ccaa)")
    op.execute(f"CREATE INDEX IF NOT EXISTS idx_{VISTA}_cpv ON {VISTA} (cpv)")
    op.execute(f"ANALYZE {VISTA}")


def downgrade() -> None:
    if not _is_postgres():
        return
    # Los índices caen con la vista; no hace falta tirarlos uno a uno.
    op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {VISTA}")
