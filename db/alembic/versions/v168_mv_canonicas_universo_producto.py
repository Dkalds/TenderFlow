"""v168: la vista de canónicas admite lo que entra por su CPV, como el listado.

Revision ID: v168_mv_canonicas_universo_producto
Revises: v167_rekey_placsp_organo_reciente
Create Date: 2026-10-31

Qué falla hoy
-------------
El listado filtra desde el 2026-10-31 por
:func:`db.sql_fragments.universo_producto_sql`: el universo tecnológico más lo
que la ingesta guarda solo por su CPV (``inclusion_reason =
'cpv_ti_universe'``: divisiones 48, 72 y, desde el 2026-10-30, 32). La vista
``licitaciones_canonicas`` —superficie pública, sitemap y hubs— seguía con
:func:`db.sql_fragments.universo_tecnologico_sql`, así que un contrato de la
CPV 32 sin término del diccionario salía en el listado y no en su ficha pública.

Qué hace
--------
Reconstruye la vista con ``universo_producto_sql``. La única diferencia con
``v157`` es ese disyunto en el ``WHERE``; clave y orden de canónica no cambian.
En el mismo commit pasan al mismo predicado los KPIs del radar
(``db/kpi_precompute.py``) y la cobertura (``db/repositories/cobertura.py``).

Cómo: construir y permutar, idéntico a ``v157``. ``DROP`` + ``CREATE`` dejaría
la superficie pública sin vista mientras se construye.

Qué cambia en las cifras
------------------------
Entran contratos y ninguno sale: el predicado nuevo contiene al viejo. Lo que
ya era canónico sigue siéndolo salvo que una fila nueva de su mismo grupo gane
el orden de ``v157`` (PLACSP, más antigua). Las fichas que cambien de URL no
desaparecen: la fila que deja de ser canónica sigue respondiendo en su ficha.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from alembic import op

revision: str = "v168_mv_canonicas_universo_producto"
down_revision: str | None = "v167_rekey_placsp_organo_reciente"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

VISTA = "licitaciones_canonicas"
#: Nombre transitorio mientras se construye la vista nueva junto a la vieja.
VISTA_NUEVA = f"{VISTA}_v168"

# Cuerpo congelado, compuesto desde ``db/repositories/publico.py`` y
# ``db/sql_fragments.py`` al escribir la revisión. La única diferencia con
# ``v157`` es ``OR l.inclusion_reason = 'cpv_ti_universe'`` en el universo.
_CUERPO = (
    "SELECT DISTINCT ON "
    "(coalesce(md5(nullif(lower(translate(btrim(coalesce(l.organo_contratacion, '')), "
    "'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ', "
    "'aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC')), '') || chr(31) || CASE WHEN l.cpv "
    "~ '^[0-9]{4}' THEN substr(l.cpv, 1, 4) ELSE '' END || chr(31) || "
    "substr(coalesce(l.fecha_publicacion, l.primera_extraccion, l.fecha_extraccion, ''), "
    "1, 7) || chr(31) || lower(btrim(l.titulo))), 'r:' || l.id_externo)) l.id_externo, "
    "l.titulo, l.ccaa, l.cpv, l.fecha_publicacion, l.fecha_extraccion FROM licitaciones l"
    " WHERE l.titulo IS NOT NULL AND length(trim(l.titulo)) >= 25 AND (l.importe IS NOT "
    "NULL OR length(coalesce(l.descripcion, '')) >= 200) AND l.id_externo NOT IN (SELECT "
    "licitacion_id FROM licitaciones_duplicados WHERE status = 'confirmed') AND "
    "((COALESCE(l.analysis_universe, 'technology_observed') = 'technology_observed' OR "
    "l.analysis_universe IN ('galicia_rss_recent_technology_observed', "
    "'euskadi_rss_recent_technology_observed') OR (l.tecnologia IS NOT NULL AND "
    "l.tecnologia <> '') OR (l.ml_tecnologias IS NOT NULL AND l.ml_tecnologias <> '')) OR"
    " l.inclusion_reason = 'cpv_ti_universe') ORDER BY "
    "coalesce(md5(nullif(lower(translate(btrim(coalesce(l.organo_contratacion, '')), "
    "'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ', "
    "'aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC')), '') || chr(31) || CASE WHEN l.cpv "
    "~ '^[0-9]{4}' THEN substr(l.cpv, 1, 4) ELSE '' END || chr(31) || "
    "substr(coalesce(l.fecha_publicacion, l.primera_extraccion, l.fecha_extraccion, ''), "
    "1, 7) || chr(31) || lower(btrim(l.titulo))), 'r:' || l.id_externo), CASE WHEN "
    "l.fuente = 'placsp' OR left(l.fuente, 5) = 'bulk_' THEN 0 WHEN l.fuente = 'ted' THEN"
    " 2 ELSE 1 END, coalesce(l.fecha_publicacion, '9999'), coalesce(l.primera_extraccion,"
    " l.fecha_extraccion, '9999'), l.id_externo"
)

# El de ``v157``, copiado literalmente: es lo que restaura el downgrade.
_CUERPO_ANTERIOR = (
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
