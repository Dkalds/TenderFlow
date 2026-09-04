"""v102: la vista de canónicas agrupa por la clave inmutable de ``v100``.

``v100`` creó ``licitaciones.primera_extraccion`` y movió a ella la componente
temporal de la clave canónica y su criterio de desempate; ``v101`` rehízo el
índice funcional que sostiene el anti-join. Falta la tercera pieza: la vista
materializada ``licitaciones_canonicas`` **congeló** su cuerpo en ``v99`` con la
clave vieja, y una vista materializada no admite ``ALTER`` de su cuerpo.

Mientras no se rehaga, la superficie pública sigue agrupando por
``coalesce(fecha_publicacion, fecha_extraccion)`` mientras el resto del código
—``fila_canonica_sql``, el detector de republicaciones, el índice de ``v101``—
usa ``primera_extraccion``. Nada falla; simplemente la vista y su definición
dicen cosas distintas, que es el modo de fallo que
``tests/test_mv_canonicas_definicion.py`` existe para hacer visible. Ese test
apunta a esta revisión desde aquí.

Por qué no se fusionó con ``v99``
---------------------------------
``v99`` no podía escribir este cuerpo: nombra ``primera_extraccion``, y esa
columna la crea ``v100``, que va después. Reordenar (columna, luego una sola
reconstrucción de la vista con los dos cambios) habría ahorrado una permuta,
pero las dos revisiones responden a preguntas distintas —qué se publica frente a
cómo se agrupa lo que se publica— y separadas se pueden revertir por separado.
El precio son ~10 s extra de construcción, una vez, en el despliegue.

Cómo: construir y permutar, no tirar y reconstruir
--------------------------------------------------
Idéntico a ``v98`` y ``v99``. ``DROP`` + ``CREATE`` dejaría la superficie pública
sin vista durante la construcción: seis endpoints devolviendo 500 justo donde
rastrea Googlebot. Se construye la nueva al lado, se le pone el índice único que
exige ``REFRESH ... CONCURRENTLY``, y sólo entonces se permuta. Los nombres de
los índices se conservan: son los que ``v94`` dejó y los que
``refrescar_vista_canonicas`` da por hecho.

Qué cambia en las cifras
------------------------
El conjunto de contratos publicables no cambia —el ``WHERE`` es el mismo que en
``v99``—, pero **qué fila representa a cada contrato** sí puede cambiar, y con
ella su URL. Es un cambio de una sola vez y en la dirección correcta: a partir de
aquí la elección deja de depender de un valor que el scraper reescribe. Las URLs
que se muevan en este despliegue son las que se estaban moviendo solas antes.

DIALECT-GUARDED: solo actúa en Postgres.

Revision ID: v102_mv_canonicas_clave_inmutable
Revises: v101_lic_clave_canonica_index_inmutable
Create Date: 2026-09-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v102_mv_canonicas_clave_inmutable"
down_revision: str | Sequence[str] | None = "v101_lic_clave_canonica_index_inmutable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VISTA = "licitaciones_canonicas"
#: Nombre transitorio mientras se construye la vista nueva junto a la vieja.
VISTA_NUEVA = f"{VISTA}_v102"

# Cuerpo congelado, compuesto desde ``db/repositories/publico.py`` y
# ``db/sql_fragments.py`` en el momento de escribir la revisión. La única
# diferencia con v99 es el ``primera_extraccion`` de la clave y del orden.
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

_CUERPO_ANTERIOR = (
    "SELECT DISTINCT ON "
    "(coalesce(md5(nullif(lower(translate(btrim(coalesce(l.organo_contratacion, '')), "
    "'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ', "
    "'aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC')), '') || chr(31) || CASE WHEN l.cpv "
    "~ '^[0-9]{4}' THEN substr(l.cpv, 1, 4) ELSE '' END || chr(31) || "
    "substr(coalesce(l.fecha_publicacion, l.fecha_extraccion, ''), 1, 7) || chr(31) || "
    "lower(btrim(l.titulo))), 'r:' || l.id_externo)) l.id_externo, l.titulo, l.ccaa, "
    "l.cpv, l.fecha_publicacion, l.fecha_extraccion FROM licitaciones l WHERE l.titulo IS "
    "NOT NULL AND length(trim(l.titulo)) >= 25 AND (l.importe IS NOT NULL OR "
    "length(coalesce(l.descripcion, '')) >= 200) AND l.id_externo NOT IN (SELECT "
    "licitacion_id FROM licitaciones_duplicados WHERE status = 'confirmed') AND "
    "(COALESCE(l.analysis_universe, 'technology_observed') = 'technology_observed' OR "
    "l.analysis_universe IN ('galicia_rss_recent_technology_observed', "
    "'euskadi_rss_recent_technology_observed') OR (l.tecnologia IS NOT NULL AND "
    "l.tecnologia <> '') OR (l.ml_tecnologias IS NOT NULL AND l.ml_tecnologias <> '')) "
    "ORDER BY coalesce(md5(nullif(lower(translate(btrim(coalesce(l.organo_contratacion, "
    "'')), 'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ', "
    "'aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC')), '') || chr(31) || CASE WHEN l.cpv "
    "~ '^[0-9]{4}' THEN substr(l.cpv, 1, 4) ELSE '' END || chr(31) || "
    "substr(coalesce(l.fecha_publicacion, l.fecha_extraccion, ''), 1, 7) || chr(31) || "
    "lower(btrim(l.titulo))), 'r:' || l.id_externo), (l.fuente <> 'placsp'), "
    "coalesce(l.fecha_publicacion, '9999'), coalesce(l.fecha_extraccion, '9999'), "
    "l.id_externo"
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
    # `statement_timeout = 0`: construir la vista recorre y ordena las filas
    # publicables (~10 s medidos en v94), por encima de los 30 s del rol de la
    # API pero dentro de lo que un despliegue puede esperar una sola vez.
    op.execute("SET statement_timeout = 0")
    op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {VISTA_NUEVA}")
    op.execute(f"CREATE MATERIALIZED VIEW {VISTA_NUEVA} AS {cuerpo}")
    # ÚNICO y no a secas: es el requisito de `REFRESH ... CONCURRENTLY`, sin el
    # cual cada refresco bloquearía la superficie pública mientras dura.
    op.execute(f"CREATE UNIQUE INDEX uq_{VISTA_NUEVA}_id_externo ON {VISTA_NUEVA} (id_externo)")
    # La permuta: de aquí al final son milisegundos.
    op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {VISTA}")
    op.execute(f"ALTER MATERIALIZED VIEW {VISTA_NUEVA} RENAME TO {VISTA}")
    op.execute(f"ALTER INDEX uq_{VISTA_NUEVA}_id_externo RENAME TO uq_{VISTA}_id_externo")
    _indices_secundarios()
    op.execute(f"ANALYZE {VISTA}")


def upgrade() -> None:
    if not _is_postgres():
        return
    _permutar(_CUERPO)


def downgrade() -> None:
    if not _is_postgres():
        return
    _permutar(_CUERPO_ANTERIOR)
