"""v181: ``watchlist_*``, ``follows`` y ``pending_digests`` se identifican por ``user_id``.

Revision ID: v181_user_id_watchlist_follows
Revises: v180_contrato_modificaciones
Create Date: 2026-11-10

ADR-030 fase 3, cuarta tanda: las tablas que v165 dejó para después.

Qué corrige
-----------
Las seis tablas llevan ``user_id`` desde v129 (o v130, ``follows``) y se leen
por identidad dual, pero quien las llama tiene que seguir pasando ``user_key``:
la necesita el ``INSERT`` (columna ``NOT NULL``) y el predicado dual, que la
compara con la de la sesión. Y tres de ellas siguen siendo únicas solo por la
clave derivada del correo:

* ``watchlist_items``    → ``UNIQUE (user_key, id_externo)``
* ``watchlist_empresas`` → ``UNIQUE (user_key, empresa_id)``
* ``follows``            → ``uq_follows_user_target (user_key, target_type, target_id, kind)``

Tras un cambio de correo, ``follows.registrar`` con la clave nueva no choca con
la fila antigua y la duplica: el usuario sigue lo mismo dos veces.

Lo que hace
-----------
1. **Backfill** de ``user_id`` por ``user_key`` en las seis, con la derivación
   SQL de v129 (repetida: una migración no importa de otra). Recoge lo escrito
   sin id desde v129.
2. **Fusiona** los ``follows`` repetidos por ``(user_id, target_type,
   target_id, kind)``: ``follows`` es todavía la copia de sus tres tablas de
   origen (ADR-031 §B, fase aditiva), y dos copias del mismo seguimiento bajo
   dos claves dicen lo mismo. Se conserva la de ``id`` mayor, la última escrita.
3. **Falla con ruido** si ``watchlist_items`` o ``watchlist_empresas`` tienen
   dos filas del mismo ``user_id`` sobre el mismo expediente o empresa: la nota
   personal o la frecuencia pueden diferir y cuál se conserva es decisión
   humana. Desde v129 ``add_item`` y ``add_entry`` buscan por identidad dual
   antes de insertar, así que no debería haber ninguna. Va antes del primer DDL.
4. ``UNIQUE INDEX uq_<tabla>_user_id (user_id, …) WHERE user_id IS NOT NULL``
   en las tres. Parcial por lo mismo que v162 y v165: las filas sin id siguen
   tecleadas por la clave, cuyo ``UNIQUE`` **se conserva** (árbitro del
   ``ON CONFLICT`` del código anterior durante el despliegue).
5. Crea ``clave_legada_de_usuario(user_id)``: la clave que
   ``shared.identity.user_key_from_email`` daría al usuario con su correo
   actual, calculada en la base. Con ella ``db/`` escribe la columna y resuelve
   la mitad legacy del predicado dual sin que ningún llamador tenga que
   conocer la clave: es lo que saca a rutas, servicios y jobs del ratchet de
   ``user_key``. ``STABLE``: comparada con un argumento constante se evalúa
   una vez por sentencia; en un filtro sin índice, por fila, pero el predicado
   solo la alcanza en filas con ``user_id IS NULL``. ``SECURITY INVOKER`` (por
   defecto): quien no puede leer ``users`` no obtiene nada de ella. ``EXECUTE``
   explícito para ``tenderflow_app`` (v59 lo quitó a ``PUBLIC``).

Queda para una revisión **posterior** al despliegue: convertir los ``UNIQUE``
por ``user_key`` en parciales ``WHERE user_id IS NULL``. Mientras sigan
enteros, quien registra el correo que otro usuario dejó y sigue lo mismo que
él choca con la fila ajena (500 en favoritos, 503 en follows). Antes de esta
revisión era peor y en silencio: recibía la fila del otro. No puede ir aquí
porque el código anterior arbitra su ``ON CONFLICT`` por esos ``UNIQUE``.

Lo que NO hace
--------------
* No pone ``user_id NOT NULL``: las filas que GDPR anonimiza en
  ``watchlist_cpv`` y ``watchlist_rules`` quedan con ``user_key = 'DELETED'`` y
  ``user_id`` nulo a propósito, y una veintena de tests siembran filas solo con
  clave. Es el paso siguiente, junto con dejar de escribir la columna.
* No deja de escribir ``user_key``: la leen el enlace de baja de las alertas
  (``pending_digests.user_key``), el payload de ``watchlist_rule.matched``
  (pendiente del RFC del 2026-09-18) y la paridad de ``follows``. Retirar la
  columna es irreversible y va por RFC (AGENTS.md §5).
* No toca ``pending_digests`` más allá del backfill: su ``UNIQUE`` es
  ``(entry_id, licitacion_id)``, sin usuario.

Orden de despliegue
-------------------
**Antes del código.** El código nuevo llama a ``clave_legada_de_usuario`` y
arbitra ``follows`` por el índice nuevo. El orden inverso (código viejo sobre
este esquema) funciona: escribe las dos columnas y sus árbitros siguen.

Antes del ``apply`` en producción: ``sql_duplicados(tabla)`` a mano para saber
si el ``RAISE`` va a saltar.

Downgrade: quita los índices y la función. El backfill no se deshace: un
``user_id`` correcto no estorba a la revisión anterior.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v181_user_id_watchlist_follows"
down_revision: str | Sequence[str] | None = "v180_contrato_modificaciones"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Las seis tablas cuyo ``user_id`` se rellena.
TABLAS_BACKFILL: tuple[str, ...] = (
    "watchlist_cpv",
    "watchlist_items",
    "watchlist_empresas",
    "watchlist_rules",
    "follows",
    "pending_digests",
)

#: ``tabla → columnas`` que acompañan a la identidad en su clave de unicidad.
TABLAS_UNICAS: dict[str, str] = {
    "watchlist_items": "id_externo",
    "watchlist_empresas": "empresa_id",
    "follows": "target_type, target_id, kind",
}

#: Tablas cuyos duplicados por la identidad nueva se fusionan solos (punto 2).
SE_DEDUPLICAN: frozenset[str] = frozenset({"follows"})

FUNCION = "clave_legada_de_usuario"

#: Derivación de ``user_key`` en SQL sobre la fila ``u`` de ``users``: la
#: misma transcripción de ``shared.identity.user_key_from_email`` que v129.
CLAVE_SQL = (
    "substr(encode(sha256(convert_to(lower(btrim("
    "COALESCE(NULLIF(u.email, ''), 'user:' || u.id::text), E' \\t\\r\\n')), 'UTF8')), "
    "'hex'), 1, 16)"
)

SQL_FUNCION = (
    f"CREATE OR REPLACE FUNCTION public.{FUNCION}(p_user_id integer) "
    "RETURNS text LANGUAGE sql STABLE AS $$ "
    f"SELECT {CLAVE_SQL} FROM users u WHERE u.id = p_user_id "
    "$$"
)

#: Permisos de la función. v59 quitó a ``PUBLIC`` el ``EXECUTE`` por defecto de
#: las funciones nuevas, así que el rol de la app (``tenderflow_app``, el de
#: ``scripts/setup_pg_roles.sql``) lo necesita explícito, como las tablas de
#: v104; sin él toda lectura de watchlist, reglas y follows falla con
#: ``permission denied for function``. Los roles de la Data API de Supabase no
#: la ejecutan (como v52 con el resto).
_PERMISOS = (
    "DO $$ BEGIN "
    f"REVOKE EXECUTE ON FUNCTION public.{FUNCION}(integer) FROM PUBLIC; "
    "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tenderflow_app') THEN "
    f"GRANT EXECUTE ON FUNCTION public.{FUNCION}(integer) TO tenderflow_app; END IF; "
    "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN "
    f"REVOKE EXECUTE ON FUNCTION public.{FUNCION}(integer) FROM anon; END IF; "
    "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN "
    f"REVOKE EXECUTE ON FUNCTION public.{FUNCION}(integer) FROM authenticated; END IF; "
    "END $$"
)

_CREAR_CLAVES = (
    "CREATE TEMPORARY TABLE v181_claves ("
    "user_key TEXT PRIMARY KEY, user_id INTEGER NOT NULL) ON COMMIT DROP"
)

_SEMBRAR_CLAVES = (
    "INSERT INTO v181_claves (user_key, user_id) "
    f"SELECT {CLAVE_SQL}, u.id FROM users u "
    "ON CONFLICT (user_key) DO NOTHING"
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def indice(tabla: str) -> str:
    """Nombre del índice único parcial por ``user_id`` de ``tabla``."""
    return f"uq_{tabla}_user_id"


def sql_backfill(tabla: str) -> str:
    """``UPDATE`` que resuelve ``user_id`` por ``user_key`` (igual que v129)."""
    return (
        f"UPDATE {tabla} AS x SET user_id = k.user_id "
        "FROM v181_claves AS k "
        "WHERE x.user_id IS NULL AND x.user_key = k.user_key"
    )


def sql_deduplicar_follows() -> str:
    """Borra las copias repetidas por identidad nueva; se queda la de ``id`` mayor."""
    return (
        "DELETE FROM follows AS a USING follows AS b "
        "WHERE a.user_id IS NOT NULL AND a.user_id = b.user_id "
        "AND a.target_type = b.target_type AND a.target_id = b.target_id "
        "AND a.kind = b.kind AND a.id < b.id"
    )


def sql_duplicados(tabla: str) -> str:
    """Grupos que violarían el índice único de ``tabla``. Dos ``NULL`` no chocan."""
    lista = f"user_id, {TABLAS_UNICAS[tabla]}"
    return (
        f"SELECT {lista}, count(*) FROM {tabla} "
        "WHERE user_id IS NOT NULL "
        f"GROUP BY {lista} HAVING count(*) > 1"
    )


def _exigir_vacio(consulta: str, que: str) -> str:
    """Bloque ``DO`` que aborta la migración si ``consulta`` devuelve filas."""
    literal = consulta.replace("'", "''")
    return (
        "DO $$ DECLARE n bigint; BEGIN "
        f"SELECT count(*) INTO n FROM ({consulta}) AS q; "
        "IF n > 0 THEN RAISE EXCEPTION "
        f"'v181: % {que}. Nada se ha modificado. Revísalas con: {literal}', n; "
        "END IF; END $$"
    )


def _presentes(tablas: Sequence[str]) -> list[str]:
    existentes = set(sa.inspect(op.get_bind()).get_table_names())
    return [t for t in tablas if t in existentes]


def upgrade() -> None:
    if not _is_postgres():
        return

    op.execute(SQL_FUNCION)
    op.execute(_PERMISOS)

    backfill = _presentes(TABLAS_BACKFILL)
    if backfill:
        op.execute(_CREAR_CLAVES)
        op.execute(_SEMBRAR_CLAVES)
        for tabla in backfill:
            op.execute(sql_backfill(tabla))

    unicas = _presentes(list(TABLAS_UNICAS))
    if "follows" in unicas:
        op.execute(sql_deduplicar_follows())
    # Todas las comprobaciones antes del primer índice: si una salta, nada
    # queda a medias.
    for tabla in unicas:
        if tabla not in SE_DEDUPLICAN:
            op.execute(
                _exigir_vacio(
                    sql_duplicados(tabla),
                    f"identidad(es) duplicada(s) en {tabla} por user_id",
                )
            )
    for tabla in unicas:
        op.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {indice(tabla)} "
            f"ON {tabla} (user_id, {TABLAS_UNICAS[tabla]}) WHERE user_id IS NOT NULL"
        )


def downgrade() -> None:
    if not _is_postgres():
        return
    for tabla in TABLAS_UNICAS:
        op.execute(f"DROP INDEX IF EXISTS {indice(tabla)}")
    op.execute(f"DROP FUNCTION IF EXISTS public.{FUNCION}(integer)")
