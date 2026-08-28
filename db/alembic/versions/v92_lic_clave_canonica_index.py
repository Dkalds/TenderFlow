"""Migración v92 — índice funcional sobre la clave canónica de ``licitaciones``.

Cierra la deuda que #226 contrajo y no pagó. Aquel PR metió el anti-join de
:func:`db.sql_fragments.fila_canonica_sql` en el ``WHERE`` de las seis
superficies públicas —listado, ``contar``, ``ultima_incorporacion``, los dos
hubs y el sitemap— y su propio comentario en ``db/repositories/publico.py`` lo
dejaba escrito: *"El arreglo de verdad es un índice funcional sobre la clave
(o una vista materializada), y eso exige una migración"*. La migración nunca se
escribió.

Lo que costó: el 2026-08-28 la superficie pública entera devolvía 500. Sin
índice, el anti-join calcula cuatro expresiones a los dos lados sobre ~692k
filas y cruza el ``statement_timeout`` de 30 s del rol de la API, así que
psycopg levantaba ``QueryCanceled`` y FastAPI lo traducía a 500. De rebote
tumbaba el build de Vercel, que prerenderiza el sitemap contra esta API y está
escrito para fallar antes que publicar un sitemap truncado.

Por qué un md5 y no un índice compuesto de cuatro expresiones
-------------------------------------------------------------
Una entrada de btree no puede pasar de ~2704 bytes y ``titulo`` no tiene cota
superior —``_sustancia_sql`` solo le pone un suelo de 25 caracteres—, así que un
índice sobre ``lower(btrim(titulo))`` no falla al planificar sino al **crearse**,
en cuanto el corpus trae un título largo. Con ``CONCURRENTLY`` eso además deja
un índice inválido que hay que ir a tirar a mano. El md5 mide siempre 32
caracteres, así que ese modo de fallo no existe.

El hash es un predicado *redundante*: las cuatro igualdades exactas siguen en el
anti-join, así que una colisión no puede colapsar dos contratos distintos. Ver
:func:`db.sql_fragments.clave_canonica_sql` para las tres decisiones que lo
hacen equivalente (incluida la propagación de NULL, que no es cosmética).

La expresión va congelada aquí en vez de importarse de ``db/``, por la misma
razón que v91 y porque ninguna migración de este linaje importa del árbol de la
app. El precio —que se separe de su gemela sin que nadie se entere, dejando el
índice muerto y el timeout de vuelta— lo cubre
``tests/test_clave_canonica_index.py``, que compara las dos cadenas.

``ANALYZE`` al final, y no es opcional
--------------------------------------
v91 reescribió ``estado`` en ~645k filas justo antes de esto, así que las
estadísticas de ``licitaciones`` están obsoletas y con ellas el planificador
puede seguir prefiriendo el hash anti-join aunque el índice exista. ``ANALYZE``
es barato y no bloquea.

Lo que esta revisión **no** hace es ``VACUUM``: no puede correr dentro de una
migración y el bloat que dejó el ``UPDATE`` de v91 sigue ahí. Si tras aplicar
esto los tiempos siguen altos, el siguiente paso es un ``VACUUM (ANALYZE)
licitaciones`` desde el panel, fuera de Alembic.

DIALECT-GUARDED: solo actúa en Postgres.

Revision ID: v92_lic_clave_canonica_index
Revises: v91_normaliza_estado_licitaciones
Create Date: 2026-08-28
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v92_lic_clave_canonica_index"
down_revision: str | Sequence[str] | None = "v91_normaliza_estado_licitaciones"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDICE = "idx_lic_clave_canonica"

#: Gemela congelada de ``db.sql_fragments.clave_canonica_sql("l")``, con el
#: alias ya resuelto a la tabla. Si las dos dejan de coincidir el índice deja de
#: usarse en silencio; ``tests/test_clave_canonica_index.py`` lo impide.
_CLAVE_CANONICA_SQL = (
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


def upgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        # `statement_timeout = 0`: construir este índice sobre ~692k filas pasa
        # de largo los 30 s del rol, que es justo el timeout que esta migración
        # existe para dejar de cruzar.
        op.execute("SET statement_timeout = 0")
        op.execute("SET lock_timeout = '30s'")
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDICE} "
            f"ON licitaciones (({_CLAVE_CANONICA_SQL}))"
        )
        op.execute("ANALYZE licitaciones")


def downgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '30s'")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDICE}")
