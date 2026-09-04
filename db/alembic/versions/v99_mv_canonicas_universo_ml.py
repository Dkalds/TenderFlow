"""v99: el universo publicable admite la señal de ML, LLM y pliego.

Qué corrige
-----------
``v98`` acotó la superficie pública al universo tecnológico, y para decidir «esto
es tecnología» miraba dos cosas: el universo declarado en ingesta (PLACSP/TED y
los RSS autonómicos) o una etiqueta ``tecnologia`` no vacía. Esa etiqueta la
escribe **sólo** el regex de keywords del clasificador de ingesta.

Lo que quedaba fuera era todo lo que el producto sabe por otra vía. El
clasificador ML, el LLM y la extracción de pliegos escriben su resultado en
``licitaciones.ml_tecnologias`` (``db/repositories/tecnologia_pliego.py``
``merge_many_with_lock``), no en ``tecnologia``. O sea que un expediente de PSCP
que el LLM identificó como un contrato de integración de sistemas —con su
etiqueta, su probabilidad y su evidencia de pliego— no entraba al universo, y
por tanto no existía para la portada, los hubs ni el sitemap. La señal más cara
de calcular era la única que no llegaba al usuario.

Esta revisión añade el cuarto disyunto: ``ml_tecnologias`` no vacío. La
definición vive, como las otras tres, en
``db.sql_fragments.universo_tecnologico_sql``; aquí sólo se congela el cuerpo de
la vista que la aplica.

Regla de precedencia entre señales
----------------------------------
``tecnologia`` (keywords) → ``ml_tecnologias`` (clasificador) → LLM → pliego.
Los dos últimos no tienen columna propia: el merge los deja en
``ml_tecnologias``, así que entran por el disyunto nuevo. Para **pertenecer** al
universo basta una cualquiera —es un ``OR``, no una prioridad—; la precedencia
decide qué etiqueta se muestra, y ahí gana ``tecnologia`` por ser determinista y
auditable frente a una probabilidad.

Qué cambia en las cifras
------------------------
El universo **crece**: entran las filas cuya única señal técnica venía del
modelo, del LLM o del pliego. Cuánto sólo se puede medir contra la BD real
(``SELECT count(*) FROM licitaciones WHERE ml_tecnologias <> '' AND
coalesce(tecnologia, '') = '' AND coalesce(analysis_universe, '') = 'pscp_observed'``
es la cota superior del delta). La sesión que escribió esta revisión no tenía
Postgres delante y no lo midió.

Riesgo asumido: la señal de ML es probabilística, así que el universo hereda sus
falsos positivos. Se acepta porque el error caro de esta superficie es el
contrario —esconder un contrato que sí es del radar no es visible ni medible— y
porque el umbral de la señal ya lo aplica el merge antes de escribir la columna.

Cómo: construir y permutar, no tirar y reconstruir
--------------------------------------------------
Idéntico a ``v98``, y por el mismo motivo: una vista materializada no admite
``ALTER`` de su cuerpo, y ``DROP`` + ``CREATE`` dejaría la superficie pública sin
vista durante los ~10 s de construcción — seis endpoints devolviendo 500 justo
donde rastrea Googlebot. Se construye la nueva al lado, se le pone el índice
único que exige ``REFRESH ... CONCURRENTLY``, y sólo entonces se permuta.

Los nombres de los índices se conservan (``uq_...``, ``idx_...``): son los que
``v94`` dejó y los que ``refrescar_vista_canonicas`` da por hecho.

El cuerpo se congela como literal, igual que en v94 y v98: una revisión
aplicada describe la vista que existe en producción, no la que el código
quisiera. ``tests/test_unit_v99_mv_universo_ml.py`` fija el DDL que emite y
comprueba que la única diferencia con v98 es el disyunto nuevo.

**Este cuerpo NO es el que la vista tiene hoy**: ``v102`` vuelve a
reconstruirla para cambiar la componente temporal de la clave canónica
(``primera_extraccion``, columna que aquí todavía no existe — la crea ``v100``).
Por eso ``tests/test_mv_canonicas_definicion.py`` apunta a v102 y no a esta
revisión. Las dos permutas son ~10 s cada una y se pagan una vez, en el
despliegue.

DIALECT-GUARDED: solo actúa en Postgres.

Revision ID: v99_mv_canonicas_universo_ml
Revises: v98_mv_canonicas_universo_tecnologico
Create Date: 2026-09-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v99_mv_canonicas_universo_ml"
down_revision: str | Sequence[str] | None = "v98_mv_canonicas_universo_tecnologico"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VISTA = "licitaciones_canonicas"
#: Nombre transitorio mientras se construye la vista nueva junto a la vieja.
VISTA_NUEVA = f"{VISTA}_v99"

# Cuerpo congelado. Idéntico al de v98 salvo el cuarto disyunto del universo.
_CUERPO = (
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
    "l.tecnologia <> '')) ORDER BY "
    "coalesce(md5(nullif(lower(translate(btrim(coalesce(l.organo_contratacion, '')), "
    "'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ', "
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
