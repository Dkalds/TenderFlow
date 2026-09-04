"""v101: el índice de la clave canónica se rehace con la componente inmutable.

``v100`` cambió la componente temporal de la clave: el año-mes sale ahora de
``coalesce(fecha_publicacion, primera_extraccion, fecha_extraccion)`` y no de
``coalesce(fecha_publicacion, fecha_extraccion)``. Un índice funcional sólo lo
usa el planificador cuando su expresión coincide **carácter a carácter** con la
del ``WHERE``, así que el índice de ``v92`` acaba de quedarse muerto: no falla
nada, simplemente el anti-join de ``fila_canonica_sql`` vuelve al escaneo
completo de ~692k filas y la superficie pública vuelve a morir por
``statement_timeout``. Es exactamente el incidente del 2026-08-28, y la única
diferencia sería que esta vez lo habríamos provocado nosotros.

Va en revisión aparte de ``v100`` por lo mismo que ``v92`` fue aparte de ``v91``:
``CREATE INDEX CONCURRENTLY`` no puede correr dentro de una transacción, y el
``UPDATE`` del backfill sí tiene que ir en una.

Construir y luego tirar, no al revés
------------------------------------
El índice nuevo se crea con **otro nombre** y sólo cuando existe se tira el
viejo. Reutilizar el nombre obligaría a ``DROP`` + ``CREATE``, y entre las dos
sentencias —minutos, porque construir este índice sobre ~692k filas los tarda—
la superficie pública se quedaría sin índice, que es el estado que tumbó
producción. El coste es tener los dos a la vez un rato: espacio en disco, y
escrituras del scraper manteniendo dos índices. Barato al lado de la
alternativa.

El nombre nuevo (``idx_lic_clave_canonica_v101``) no lo da por hecho ningún
código: ``fila_canonica_sql`` no nombra índices, sólo escribe la expresión que
éste indexa. Quien busque "el índice de la clave canónica" tiene que mirar la
revisión más reciente, y por eso ``tests/test_clave_canonica_index.py`` apunta
aquí y no a ``v92``.

La expresión va congelada, como en ``v92``, en vez de importarse del árbol de la
app: ninguna migración de este linaje importa de ``db/``. El precio —que se
separe de su gemela sin que nadie se entere— lo cubre ese mismo test.

DIALECT-GUARDED: solo actúa en Postgres.

Revision ID: v101_lic_clave_canonica_index_inmutable
Revises: v100_lic_primera_extraccion
Create Date: 2026-09-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v101_lic_clave_canonica_index_inmutable"
down_revision: str | Sequence[str] | None = "v100_lic_primera_extraccion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDICE_NUEVO = "idx_lic_clave_canonica_v101"
_INDICE_VIEJO = "idx_lic_clave_canonica"

#: Gemela congelada de ``db.sql_fragments.clave_canonica_sql("licitaciones")``.
#: La única diferencia con la de ``v92`` es el ``primera_extraccion`` del
#: ``coalesce`` temporal, que es de lo que va esta revisión.
_CLAVE_CANONICA_SQL = (
    "md5(nullif(lower(translate(btrim(coalesce(licitaciones.organo_contratacion, '')), "
    "'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ', "
    "'aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC')), '') "
    "|| chr(31) || CASE WHEN licitaciones.cpv ~ '^[0-9]{4}' "
    "THEN substr(licitaciones.cpv, 1, 4) ELSE '' END "
    "|| chr(31) || substr(coalesce(licitaciones.fecha_publicacion, "
    "licitaciones.primera_extraccion, licitaciones.fecha_extraccion, ''), 1, 7) "
    "|| chr(31) || lower(btrim(licitaciones.titulo)))"
)

#: La de ``v92``, para poder volver atrás dejando la base como estaba.
_CLAVE_CANONICA_SQL_V92 = (
    "md5(nullif(lower(translate(btrim(coalesce(licitaciones.organo_contratacion, '')), "
    "'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ', "
    "'aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC')), '') "
    "|| chr(31) || CASE WHEN licitaciones.cpv ~ '^[0-9]{4}' "
    "THEN substr(licitaciones.cpv, 1, 4) ELSE '' END "
    "|| chr(31) || substr(coalesce(licitaciones.fecha_publicacion, "
    "licitaciones.fecha_extraccion, ''), 1, 7) "
    "|| chr(31) || lower(btrim(licitaciones.titulo)))"
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _permutar_indice(*, crear: str, expresion: str, tirar: str) -> None:
    """Crea ``crear`` sobre ``expresion`` y sólo entonces tira ``tirar``."""
    with op.get_context().autocommit_block():
        # `statement_timeout = 0`: construir este índice sobre ~692k filas pasa
        # de largo los 30 s del rol, que es justo el timeout que este índice
        # existe para no cruzar.
        op.execute("SET statement_timeout = 0")
        op.execute("SET lock_timeout = '30s'")
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {crear} ON licitaciones (({expresion}))"
        )
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {tirar}")
        op.execute("ANALYZE licitaciones")


def upgrade() -> None:
    if not _is_postgres():
        return
    _permutar_indice(crear=_INDICE_NUEVO, expresion=_CLAVE_CANONICA_SQL, tirar=_INDICE_VIEJO)


def downgrade() -> None:
    if not _is_postgres():
        return
    _permutar_indice(crear=_INDICE_VIEJO, expresion=_CLAVE_CANONICA_SQL_V92, tirar=_INDICE_NUEVO)
