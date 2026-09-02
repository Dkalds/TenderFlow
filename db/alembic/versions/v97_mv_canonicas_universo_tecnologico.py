"""v97: la vista de canónicas publicables se acota al universo tecnológico.

Qué corrige
-----------
Medido contra producción el 2026-09-01: la superficie pública servía 415.868
expedientes, 396.583 de Cataluña, y los CPV más frecuentes eran reactivos de
laboratorio, servicios a empresas y material sanitario. Dos causas: el conector
PSCP persiste la plataforma catalana entera con ``analysis_universe =
'pscp_observed'`` (sólo etiqueta ``tecnologia`` cuando el título casa con el
diccionario), y ``_publicable_sql`` filtraba por sustancia y duplicados pero no
por universo. La landing prometía «un radar tecnológico, no un censo de toda la
contratación pública» y los hubs eran exactamente ese censo.

La definición de «qué es tecnología» ya existía para la analítica y el ML
(``TECHNOLOGY_OBSERVED_SQL``); esta revisión hace que la superficie pública la
comparta vía ``db.sql_fragments.universo_tecnologico_sql``: entra un universo
filtrado en ingesta (PLACSP/TED y los RSS autonómicos) o una fila con
``tecnologia`` no vacía (el expediente de PSCP que sí casó con el diccionario).

Cómo: construir y permutar, no tirar y reconstruir
--------------------------------------------------
Una vista materializada no admite ``ALTER`` de su cuerpo. La vía obvia —``DROP``
y ``CREATE``— dejaría la superficie pública sin vista durante los ~10 s de
construcción: seis endpoints devolviendo 500 justo donde rastrea Googlebot. En
su lugar se construye la vista nueva con otro nombre (sin tocar la vieja, que
sigue sirviendo), se le pone el índice único que exige ``REFRESH …
CONCURRENTLY``, y sólo entonces se permuta: ``DROP`` de la vieja y ``RENAME``
de la nueva, dos sentencias de milisegundos. Los índices secundarios se crean
ya sobre el nombre definitivo: con ~20k filas tardan menos que el ``RENAME``.

Los nombres de los índices se conservan (``uq_…``, ``idx_…``): son los que
``v94`` dejó y los que ``refrescar_vista_canonicas`` da por hecho.

``tests/test_mv_canonicas_definicion.py`` lee ``_CUERPO`` de esta revisión: es
el fichero que impide que la vista y el código se separen en silencio. El
``downgrade`` reconstruye la vista de ``v94`` (``_CUERPO_ANTERIOR``) con la misma
permuta.

DIALECT-GUARDED: solo actúa en Postgres.

Revision ID: v97_mv_canonicas_universo_tecnologico
Revises: v96_password_reset_tokens
Create Date: 2026-09-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v97_mv_canonicas_universo_tecnologico"
down_revision: str | Sequence[str] | None = "v96_password_reset_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VISTA = "licitaciones_canonicas"
#: Nombre transitorio mientras se construye la vista nueva junto a la vieja.
VISTA_NUEVA = f"{VISTA}_v97"

# Cuerpo congelado: ``SELECT DISTINCT ON (clave) … WHERE {_publicable_sql('l')}
# ORDER BY …``, compuesto desde ``db/repositories/publico.py`` y
# ``db/sql_fragments.py`` en el momento de escribir la revisión. La única
# diferencia con v94 es el tercer término del WHERE: el universo tecnológico.
_CUERPO = (
    "SELECT DISTINCT ON "
    "(coalesce(md5(nullif(lower(translate(btrim(coalesce(l.organo_contratacion, "
    "'')), 'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ', "
    "'aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC')), '') || chr(31) || CASE "
    "WHEN l.cpv ~ '^[0-9]{4}' THEN substr(l.cpv, 1, 4) ELSE '' END || chr(31) || "
    "substr(coalesce(l.fecha_publicacion, l.fecha_extraccion, ''), 1, 7) || "
    "chr(31) || lower(btrim(l.titulo))), 'r:' || l.id_externo)) l.id_externo, "
    "l.titulo, l.ccaa, l.cpv, l.fecha_publicacion, l.fecha_extraccion FROM "
    "licitaciones l WHERE l.titulo IS NOT NULL AND length(trim(l.titulo)) >= 25 "
    "AND (l.importe IS NOT NULL OR length(coalesce(l.descripcion, '')) >= 200) "
    "AND l.id_externo NOT IN (SELECT licitacion_id FROM licitaciones_duplicados "
    "WHERE status = 'confirmed') AND (COALESCE(l.analysis_universe, 'technology_observed') = 'technology_observed' OR l.analysis_universe IN "
    "('galicia_rss_recent_technology_observed', "
    "'euskadi_rss_recent_technology_observed') OR (l.tecnologia IS NOT NULL AND "
    "l.tecnologia <> '')) ORDER BY "
    "coalesce(md5(nullif(lower(translate(btrim(coalesce(l.organo_contratacion, "
    "'')), 'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ', "
    "'aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC')), '') || chr(31) || CASE "
    "WHEN l.cpv ~ '^[0-9]{4}' THEN substr(l.cpv, 1, 4) ELSE '' END || chr(31) || "
    "substr(coalesce(l.fecha_publicacion, l.fecha_extraccion, ''), 1, 7) || "
    "chr(31) || lower(btrim(l.titulo))), 'r:' || l.id_externo), (l.fuente <> "
    "'placsp'), coalesce(l.fecha_publicacion, '9999'), "
    "coalesce(l.fecha_extraccion, '9999'), l.id_externo"
)

# El cuerpo de v94, tal cual, para poder volver atrás.
_CUERPO_ANTERIOR = (
    "SELECT DISTINCT ON "
    "(coalesce(md5(nullif(lower(translate(btrim(coalesce(l.organo_contratacion, "
    "'')), 'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ', "
    "'aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC')), '') || chr(31) || CASE "
    "WHEN l.cpv ~ '^[0-9]{4}' THEN substr(l.cpv, 1, 4) ELSE '' END || chr(31) || "
    "substr(coalesce(l.fecha_publicacion, l.fecha_extraccion, ''), 1, 7) || "
    "chr(31) || lower(btrim(l.titulo))), 'r:' || l.id_externo)) l.id_externo, "
    "l.titulo, l.ccaa, l.cpv, l.fecha_publicacion, l.fecha_extraccion FROM "
    "licitaciones l WHERE l.titulo IS NOT NULL AND length(trim(l.titulo)) >= 25 "
    "AND (l.importe IS NOT NULL OR length(coalesce(l.descripcion, '')) >= 200) "
    "AND l.id_externo NOT IN (SELECT licitacion_id FROM licitaciones_duplicados "
    "WHERE status = 'confirmed') ORDER BY "
    "coalesce(md5(nullif(lower(translate(btrim(coalesce(l.organo_contratacion, "
    "'')), 'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ', "
    "'aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC')), '') || chr(31) || CASE "
    "WHEN l.cpv ~ '^[0-9]{4}' THEN substr(l.cpv, 1, 4) ELSE '' END || chr(31) || "
    "substr(coalesce(l.fecha_publicacion, l.fecha_extraccion, ''), 1, 7) || "
    "chr(31) || lower(btrim(l.titulo))), 'r:' || l.id_externo), (l.fuente <> "
    "'placsp'), coalesce(l.fecha_publicacion, '9999'), "
    "coalesce(l.fecha_extraccion, '9999'), l.id_externo"
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
