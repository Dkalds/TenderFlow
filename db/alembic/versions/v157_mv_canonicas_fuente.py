"""v157: la vista de canónicas cuenta el bulk como PLACSP y pone TED al final.

Revision ID: v157_mv_canonicas_fuente
Revises: v156_importes_double_precision
Create Date: 2026-10-23

Qué falla hoy
-------------
El primer criterio de canónica de ``licitaciones_canonicas`` (``v102``) es
``fuente <> 'placsp'``, y tiene dos defectos:

* **El bulk no cuenta como PLACSP.** El upsert reescribe ``fuente`` con la
  etiqueta del carril que refrescó la fila, y el carril de ZIP mensuales escribe
  ``bulk_YYYYMM``. Una fila de PLACSP que pasó por el bulk competía como una
  fuente cualquiera: con PSCP o un RSS autonómico más antiguo, la vista se
  quedaba con la otra.
* **TED no pierde frente al resto.** TED republica en el DOUE lo que el
  comprador ya publicó en su plataforma, con menos detalle. Si un par colapsa
  por clave sin referencia explícita, ganaba la más antigua, y TED suele serlo.

El dedupe por referencia (ADR-026) ya aplicaba las dos reglas; la vista no.

Qué hace
--------
Reconstruye la vista con el criterio de ``db.sql_fragments.rango_de_fuente_sql``:
PLACSP (``placsp`` o ``bulk_*``) → el resto → TED, y detrás los mismos
desempates de ``v102``. El gemelo Python (``services.dedupe._rango_canonico``)
cambia en el mismo commit; ``tests/test_canonica_orden_pg.py`` ejecuta los dos
sobre las mismas filas.

Va después de ``v155``/``v156`` y no antes a propósito: así se puede subir hasta
``v156`` (los importes) sin mover ninguna URL, medir el delta de esta y aplicarla
cuando el propietario lo haya revisado.

Cómo: construir y permutar, idéntico a ``v98``/``v99``/``v102``. ``DROP`` +
``CREATE`` dejaría la superficie pública sin vista mientras se construye.

Qué cambia en las cifras
------------------------
El conjunto de contratos publicables no cambia (el ``WHERE`` es el de ``v102``),
pero **qué fila representa a cada contrato** sí, y con ella su URL en el
sitemap. Antes de aplicarla en producción hay que medir cuántas canónicas
cambian de fila, sin aplicar nada::

    ENV=dev python scripts/medir_delta_canonicas.py

(``db.repositories.canonicas_delta``: solo lectura, compara el criterio de
``v102`` con el vigente sobre la tabla viva). Las fichas que cambien de URL no
desaparecen: la fila que deja de ser canónica sigue respondiendo en su ficha.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from alembic import op

revision: str = "v157_mv_canonicas_fuente"
down_revision: str | None = "v156_importes_double_precision"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

VISTA = "licitaciones_canonicas"
#: Nombre transitorio mientras se construye la vista nueva junto a la vieja.
VISTA_NUEVA = f"{VISTA}_v157"

# Cuerpo congelado, compuesto desde ``db/repositories/publico.py`` y
# ``db/sql_fragments.py`` al escribir la revisión. La única diferencia con
# ``v102`` es el primer criterio del ``ORDER BY`` tras la clave.
_CUERPO = (
    "SELECT DISTINCT ON "
    "(coalesce(md5(nullif(lower(translate(btrim(coalesce(l.organo_contratacion, '')), "
    "'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ', "
    "'aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC')), '') || chr(31) || CASE WHEN "
    "l.cpv ~ '^[0-9]{4}' THEN substr(l.cpv, 1, 4) ELSE '' END || chr(31) || "
    "substr(coalesce(l.fecha_publicacion, l.primera_extraccion, l.fecha_extraccion, "
    "''), 1, 7) || chr(31) || lower(btrim(l.titulo))), 'r:' || l.id_externo)) "
    "l.id_externo, l.titulo, l.ccaa, l.cpv, l.fecha_publicacion, l.fecha_extraccion "
    "FROM licitaciones l WHERE l.titulo IS NOT NULL AND length(trim(l.titulo)) >= 25 "
    "AND (l.importe IS NOT NULL OR length(coalesce(l.descripcion, '')) >= 200) AND "
    "l.id_externo NOT IN (SELECT licitacion_id FROM licitaciones_duplicados WHERE "
    "status = 'confirmed') AND "
    "(COALESCE(l.analysis_universe, 'technology_observed') = 'technology_observed' OR "
    "l.analysis_universe IN "
    "('galicia_rss_recent_technology_observed', "
    "'euskadi_rss_recent_technology_observed') OR (l.tecnologia IS NOT NULL AND "
    "l.tecnologia <> '') OR (l.ml_tecnologias IS NOT NULL AND l.ml_tecnologias <> '')) "
    "ORDER BY "
    "coalesce(md5(nullif(lower(translate(btrim(coalesce(l.organo_contratacion, '')), "
    "'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ', "
    "'aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC')), '') || chr(31) || CASE WHEN "
    "l.cpv ~ '^[0-9]{4}' THEN substr(l.cpv, 1, 4) ELSE '' END || chr(31) || "
    "substr(coalesce(l.fecha_publicacion, l.primera_extraccion, l.fecha_extraccion, "
    "''), 1, 7) || chr(31) || lower(btrim(l.titulo))), 'r:' || l.id_externo), CASE "
    "WHEN l.fuente = 'placsp' OR left(l.fuente, 5) = 'bulk_' THEN 0 WHEN l.fuente = "
    "'ted' THEN 2 ELSE 1 END, coalesce(l.fecha_publicacion, '9999'), "
    "coalesce(l.primera_extraccion, l.fecha_extraccion, '9999'), l.id_externo"
)

# El de ``v102``, copiado literalmente: es lo que restaura el downgrade.
_CUERPO_ANTERIOR = (
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


def _indices_secundarios() -> None:
    """Los mismos tres que puso v94, sobre el nombre definitivo."""
    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{VISTA}_fecha_pub "
        f"ON {VISTA} (fecha_publicacion DESC NULLS LAST, id_externo)"
    )
    op.execute(f"CREATE INDEX IF NOT EXISTS idx_{VISTA}_ccaa ON {VISTA} (ccaa)")
    op.execute(f"CREATE INDEX IF NOT EXISTS idx_{VISTA}_cpv ON {VISTA} (cpv)")


def _permutar(cuerpo: str) -> None:
    """Construye la vista con ``cuerpo`` al lado de la actual y la sustituye."""
    # Construir recorre y ordena las filas publicables: por encima del límite
    # del rol de la API, dentro de lo que un despliegue espera una vez.
    op.execute("SET statement_timeout = 0")
    op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {VISTA_NUEVA}")
    op.execute(f"CREATE MATERIALIZED VIEW {VISTA_NUEVA} AS {cuerpo}")
    # ÚNICO y no a secas: es el requisito de `REFRESH ... CONCURRENTLY`.
    op.execute(f"CREATE UNIQUE INDEX uq_{VISTA_NUEVA}_id_externo ON {VISTA_NUEVA} (id_externo)")
    # La permuta: de aquí al final son milisegundos.
    op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {VISTA}")
    op.execute(f"ALTER MATERIALIZED VIEW {VISTA_NUEVA} RENAME TO {VISTA}")
    op.execute(f"ALTER INDEX uq_{VISTA_NUEVA}_id_externo RENAME TO uq_{VISTA}_id_externo")
    _indices_secundarios()
    op.execute(f"ANALYZE {VISTA}")
    op.execute("RESET statement_timeout")


def upgrade() -> None:
    if not _is_postgres():
        return
    _permutar(_CUERPO)


def downgrade() -> None:
    if not _is_postgres():
        return
    _permutar(_CUERPO_ANTERIOR)
