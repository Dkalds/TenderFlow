"""v155: los importes de ``licitaciones`` y ``adjudicaciones`` pasan de ``real`` a ``double precision``.

Revision ID: v155_importes_double_precision
Revises: v154_importe_tipo_galicia_desconocido
Create Date: 2026-10-23

Qué falla hoy
-------------
En producción ``licitaciones.importe`` y ``duracion_valor`` y los cuatro
importes de ``adjudicaciones`` (``importe_adjudicado``, ``importe_pagable``,
``oferta_minima``, ``oferta_maxima``) son ``real`` (float4, ~7 cifras
significativas): lo heredaron del esquema SQLite anterior a ADR-021. Un
bootstrap nuevo los crea ``double precision`` (``sa.Float`` de
``baseline002_pg_core_genesis``), así que CI y los tests nunca vieron el
defecto. Los conectores escriben ``float`` de Python (float8) y lo que vuelve
del ``SELECT`` no es lo que se escribió:

* 11 782 154,55 € se guarda como 11 782 155. El detector de diffs de
  ``db/upsert.py`` marcaba «importe cambió» en cada reingesta de un expediente
  intacto, y hoy lo tapa ``shared.numeric.FLOAT_REL_TOL``, ciego a cambios
  reales por debajo del 0,001 %.
* ``db.repositories.reproceso_lotes`` empareja la adjudicación guardada con la
  publicada por igualdad de ``importe_adjudicado``: un ``real`` promovido a
  float8 no es igual al float8 del conector en cuanto el importe lleva céntimos
  que float4 no representa. Medido el 2026-10-23: de las 121 adjudicaciones de
  expedientes multilote que siguen sin lote, 113 tienen un importe así (en las
  que sí lo tienen, menos de la mitad).

Inventario de dependencias (``pg_depend``, en producción el 2026-10-23 y en
una base recién migrada): de esas seis columnas solo dependen índices —que el
``ALTER`` reconstruye solo— y la vista materializada ``licitaciones_canonicas``
(su ``WHERE`` de publicabilidad lee ``importe``). Ninguna vista más, ningún
``CHECK``, ``DEFAULT``, trigger ni función. Un ``ALTER COLUMN ... TYPE`` falla
con una vista dependiente, así que la vista se tira y se rehace **en esta misma
revisión** con su cuerpo vigente, el de ``v102`` (copiado a mano: una migración
no importa otra; ``tests/test_v155_importes_double_precision_migration.py``
comprueba que son idénticos).

Qué no arregla
--------------
La precisión que float4 ya perdió no vuelve: el ``ALTER`` convierte cada valor
guardado a float8 tal cual (11 782 155,0). El importe exacto llega con la
siguiente reingesta de cada expediente, que ``replace_adjudicaciones``
reescribe entera y el upsert de ``licitaciones`` sobrescribe. La sombra exacta
``importe_num numeric(14,2)`` (``v133``) **se conserva**: para filas antiguas
sigue siendo la única fuente con céntimos que no sean ruido, y retirarla es
decisión de otra tanda, cuando la verificación de la ventana del núcleo tipado
diga que ``importe`` y ``importe_num`` coinciden. ``FLOAT_REL_TOL`` tampoco se
toca aquí: se baja después de verificar el tipo en producción (criterio del
ítem del backlog).

Coste y ventana
---------------
Cambiar el tipo **reescribe** ``licitaciones`` y ``adjudicaciones`` enteras y
reconstruye todos sus índices, con ``ACCESS EXCLUSIVE`` sobre las dos tablas
mientras dura: la ingesta, la API y la superficie pública esperan (o caen por
``statement_timeout``) hasta el ``COMMIT``. Tamaños en producción el
2026-10-23: ``licitaciones`` 873 MB de tabla + 1,15 GB de índices (~89 k filas
vivas: la reescritura además compacta la hinchazón), ``adjudicaciones`` 130 MB
+ 150 MB (~80 k filas). Estimación sin medir: de uno a pocos minutos, dominados
por los índices GIN de búsqueda; ``v68`` tardó más de 30 min, pero sobre una
tabla de ~1,3 M filas. Las dos tablas van en un solo ``ALTER TABLE`` cada una
para que cada tabla se reescriba **una** vez. Se aplica por ``migrate.yml``
(``workflow_dispatch``) en una ventana con la ingesta parada, nunca por un
despliegue normal.

``lock_timeout = 30s``: si una consulta larga retiene la tabla, la revisión
falla limpia en vez de quedarse encolada bloqueando todo lo que llegue detrás.
``statement_timeout = 0`` porque la reescritura pasa de los límites del rol.

Downgrade
---------
Simétrico: tira la vista, vuelve las seis columnas a ``real`` y la rehace.
**Pierde precisión** (todo valor escrito después de la subida se redondea a
float4) y en una base recién migrada deja ``real`` donde el baseline creó
``double precision``: es el estado de producción que esta revisión corrige, no
el del baseline.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from alembic import op

revision: str = "v155_importes_double_precision"
down_revision: str | None = "v154_importe_tipo_galicia_desconocido"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

#: Columnas que cambian de tipo, por tabla. Cada tabla en un solo ``ALTER``.
COLUMNAS: dict[str, tuple[str, ...]] = {
    "licitaciones": ("importe", "duracion_valor"),
    "adjudicaciones": ("importe_adjudicado", "importe_pagable", "oferta_minima", "oferta_maxima"),
}

VISTA = "licitaciones_canonicas"

# Cuerpo vigente de la vista, copiado literalmente de ``v102`` (la revisión que
# la definió por última vez antes de esta). No cambia nada: solo se rehace
# porque el ``ALTER`` no admite una vista que dependa de la columna.
_CUERPO = (
    "SELECT DISTINCT ON "
    "(coalesce(md5(nullif(lower(translate(btrim(coalesce(l.organo_contratacion, '')), "
    "'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ', "
    "'aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC')), '') || chr(31) || CASE WHEN l.cpv "
    "~ '^[0-9]{4}' THEN substr(l.cpv, 1, 4) ELSE '' END || chr(31) || "
    "substr(coalesce(l.fecha_publicacion, l.primera_extraccion, l.fecha_extraccion, ''), "
    "1, 7) || chr(31) || lower(btrim(l.titulo))), 'r:' || l.id_externo)) l.id_externo, "
    "l.titulo, l.ccaa, l.cpv, l.fecha_publicacion, l.fecha_extraccion FROM licitaciones l "
    "WHERE l.titulo IS NOT NULL AND length(trim(l.titulo)) >= 25 AND (l.importe IS NOT "
    "NULL OR length(coalesce(l.descripcion, '')) >= 200) AND l.id_externo NOT IN (SELECT "
    "licitacion_id FROM licitaciones_duplicados WHERE status = 'confirmed') AND "
    "(COALESCE(l.analysis_universe, 'technology_observed') = 'technology_observed' OR "
    "l.analysis_universe IN ('galicia_rss_recent_technology_observed', "
    "'euskadi_rss_recent_technology_observed') OR (l.tecnologia IS NOT NULL AND "
    "l.tecnologia <> '') OR (l.ml_tecnologias IS NOT NULL AND l.ml_tecnologias <> '')) "
    "ORDER BY coalesce(md5(nullif(lower(translate(btrim(coalesce(l.organo_contratacion, "
    "'')), 'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ', "
    "'aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC')), '') || chr(31) || CASE WHEN l.cpv "
    "~ '^[0-9]{4}' THEN substr(l.cpv, 1, 4) ELSE '' END || chr(31) || "
    "substr(coalesce(l.fecha_publicacion, l.primera_extraccion, l.fecha_extraccion, ''), "
    "1, 7) || chr(31) || lower(btrim(l.titulo))), 'r:' || l.id_externo), (l.fuente <> "
    "'placsp'), coalesce(l.fecha_publicacion, '9999'), coalesce(l.primera_extraccion, "
    "l.fecha_extraccion, '9999'), l.id_externo"
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _alter(tabla: str, tipo: str) -> str:
    cambios = ", ".join(f"ALTER COLUMN {c} TYPE {tipo}" for c in COLUMNAS[tabla])
    return f"ALTER TABLE {tabla} {cambios}"


def _rehacer_vista() -> None:
    """La vista con su cuerpo vigente y los cuatro índices de ``v94``/``v102``."""
    op.execute(f"CREATE MATERIALIZED VIEW {VISTA} AS {_CUERPO}")
    # ÚNICO: lo exige `REFRESH ... CONCURRENTLY` (ver `refrescar_vista_canonicas`).
    op.execute(f"CREATE UNIQUE INDEX uq_{VISTA}_id_externo ON {VISTA} (id_externo)")
    op.execute(
        f"CREATE INDEX idx_{VISTA}_fecha_pub ON {VISTA} (fecha_publicacion DESC NULLS LAST, id_externo)"
    )
    op.execute(f"CREATE INDEX idx_{VISTA}_ccaa ON {VISTA} (ccaa)")
    op.execute(f"CREATE INDEX idx_{VISTA}_cpv ON {VISTA} (cpv)")
    op.execute(f"ANALYZE {VISTA}")


def _cambiar_tipo(tipo: str) -> None:
    op.execute("SET statement_timeout = 0")
    op.execute("SET lock_timeout = '30s'")
    op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {VISTA}")
    for tabla, columnas in COLUMNAS.items():
        op.execute(_alter(tabla, tipo))
        # El cambio de tipo borra las estadísticas de la columna: sin esto el
        # planificador estima a ciegas los filtros por importe hasta el próximo
        # autoanalyze.
        op.execute(f"ANALYZE {tabla} ({', '.join(columnas)})")
    _rehacer_vista()
    # Alembic puede aplicar varias revisiones en la misma transacción.
    op.execute("RESET lock_timeout")
    op.execute("RESET statement_timeout")


def upgrade() -> None:
    if not _is_postgres():
        return
    _cambiar_tipo("double precision")


def downgrade() -> None:
    if not _is_postgres():
        return
    _cambiar_tipo("real")
