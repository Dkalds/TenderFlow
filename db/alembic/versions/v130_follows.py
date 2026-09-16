"""v130: seguimiento unificado en una tabla ``follows`` (ADR-031, fase aditiva).

Revision ID: v130_follows
Revises: v129_user_id_fase2
Create Date: 2026-09-14

Qué corrige
-----------
«Seguir algo» está implementado tres veces y media, con tres tablas y tres
juegos de endpoints: ``watchlist_items`` (expedientes), ``watchlist_empresas``
(empresas) y ``radar_dismissals`` (expedientes descartados, que es seguir con
signo negativo). Las consecuencias, según ADR-031: seguir un órgano o un CPV
no existe porque haría falta una cuarta tabla; el usuario aprende tres
controles que hacen lo mismo; y cada canal de notificación nuevo tiene que
enumerar las tres para saber a quién avisar.

Esta revisión hace **solo la mitad aditiva** de ADR-031 §B: crea la tabla y la
rellena desde las tres. No borra ni una fila, no toca los endpoints y no retira
nada. La lectura dual y la paridad medida contra producción son el paso
siguiente, y la retirada de los endpoints antiguos va por RFC con fecha. El
orden importa: retirar antes de medir la paridad convierte un bug de backfill
en pérdida de datos del usuario.

Qué NO viaja a ``follows``, y por qué
-------------------------------------
Los campos que decoran cada seguimiento se quedan en su tabla durante la
ventana de lectura dual — que es precisamente para lo que existe la ventana:

* ``watchlist_items.nota`` — la nota personal de un favorito (ADR-030 §D).
* ``watchlist_empresas.frequency`` / ``email`` / ``last_notified_at`` — la
  cadencia del digest. Su sitio natural es ``channels_json``, pero el
  vocabulario de esa columna lo fija C2.7 del plan complementario y ADR-031 lo
  deja explícitamente sin decidir. Inventarlo aquí sería fijar por la puerta de
  atrás un contrato que otro stream tiene que escribir: la columna se crea,
  vacía.
* ``radar_dismissals.score`` / ``banda`` / ``accion`` — la foto del radar en el
  momento del descarte, no el puntero.

La excepción es ``hasta``: un descarte con caducidad **deja de ser** un
seguimiento en una fecha. Eso no decora el puntero, lo define, y sin la columna
``follows`` presentaría como permanentes descartes que no lo son.

Identidad
---------
``user_key`` y ``user_id`` juntos, como el resto de tablas de usuario tras
v129: ``user_key`` es ``NOT NULL`` porque es la clave que llevan las tres
tablas de origen y la que sostiene el ``UNIQUE``; ``user_id`` se rellena con
el mismo backfill por correo de v129 y es lo que sobrevive a un cambio de
correo. La retirada de ``user_key`` es la fase 3 de ADR-030, no ésta.

RLS
---
``follows`` es dato corporativo y nace con la protección de v128 puesta —
``FORCE ROW LEVEL SECURITY`` y las dos políticas ``tenant_scope_`` /
``tenant_guard_``—, no con una segunda revisión que se acuerde después. La
lista de v128 no se amplía: cada migración protege las tablas que crea, que es
la única versión de la regla que no se olvida. ``tests/test_rls_tenant_scope_
integration.py::test_toda_tabla_con_organization_id_tiene_decision_rls`` une
las listas de todas las revisiones y falla si alguna tabla se queda sin
decisión.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v130_follows"
down_revision: str | Sequence[str] | None = "v129_user_id_fase2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Tablas corporativas que crea esta revisión. Ver la cabecera §RLS.
TABLAS_CORPORATIVAS: tuple[str, ...] = ("follows",)

#: Enumeración cerrada de ADR-031 §A. ``lote`` y ``cpv`` no tienen origen que
#: migrar: entran aquí para que la primera fila de un tipo nuevo sea un INSERT
#: y no una migración.
TARGET_TYPES: tuple[str, ...] = ("licitacion", "lote", "empresa", "organo", "cpv")

#: Descartar es seguir con signo negativo, no otro concepto (ADR-031 §A).
KINDS: tuple[str, ...] = ("seguir", "descartar")

VISIBILITIES: tuple[str, ...] = ("private", "organization")

_PREDICADO_TENANT = (
    "NULLIF(current_setting('app.organization_id', true), '') IS NULL "
    "OR organization_id IS NULL "
    "OR organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer"
)


#: ``created_at`` es ``text`` en las tablas de origen más viejas (se escribió
#: con ``now_utc_iso()``). El cast directo reventaría la revisión entera ante
#: una sola fila con basura, así que se comprueba la forma antes: lo que no
#: parezca una fecha ISO entra con ``now()`` y se pierde el instante original,
#: que es infinitamente preferible a no poder migrar.
def _fecha(col: str) -> str:
    return (
        f"CASE WHEN {col}::text ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}' "
        f"THEN {col}::text::timestamptz ELSE now() END"
    )


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _tablas() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _lista(valores: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in valores)


def upgrade() -> None:
    if not _is_postgres():
        return

    op.execute(
        "CREATE TABLE IF NOT EXISTS follows ("
        " id SERIAL PRIMARY KEY,"
        " organization_id INTEGER REFERENCES organizations(id) ON DELETE CASCADE,"
        # `SET NULL` y no `CASCADE`, como en v129: el dato personal se anonimiza
        # por GDPR, no desaparece porque desaparezca la fila de `users`.
        " user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,"
        " user_key TEXT NOT NULL,"
        f" target_type TEXT NOT NULL CHECK (target_type IN ({_lista(TARGET_TYPES)})),"
        " target_id TEXT NOT NULL,"
        f" kind TEXT NOT NULL DEFAULT 'seguir' CHECK (kind IN ({_lista(KINDS)})),"
        f" visibility TEXT NOT NULL DEFAULT 'private' CHECK (visibility IN ({_lista(VISIBILITIES)})),"
        # Vocabulario pendiente de C2.7 (ver cabecera). Nace vacía a propósito.
        " channels_json TEXT,"
        " hasta TIMESTAMPTZ,"
        " created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
        # Un usuario sigue un objetivo una vez por signo. Poder seguir y
        # descartar el mismo expediente es deliberado: el radar descarta, la
        # lista de favoritos sigue, y son dos gestos distintos del usuario.
        " CONSTRAINT uq_follows_user_target UNIQUE (user_key, target_type, target_id, kind)"
        ")"
    )

    # El índice que hace posible ADR-031 §D: «¿quién sigue esto?» es la pregunta
    # del despachador de eventos, y sin este índice sería un seq scan por evento.
    op.execute("CREATE INDEX IF NOT EXISTS idx_follows_target ON follows (target_type, target_id)")
    # Las tres lecturas de la interfaz: mis seguimientos, los de mi organización
    # y, tras el cambio de correo, los míos por id.
    op.execute("CREATE INDEX IF NOT EXISTS idx_follows_user ON follows (user_key, target_type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_follows_user_id ON follows (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_follows_organization ON follows (organization_id)")
    # Los descartes con caducidad se barren por fecha; parcial porque son una
    # minoría de las filas y el índice completo sería casi todo NULL.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_follows_hasta ON follows (hasta) WHERE hasta IS NOT NULL"
    )

    _backfill()
    _proteger("follows")


def _backfill() -> None:
    """Rellena ``follows`` desde las tres tablas de origen.

    ``ON CONFLICT DO NOTHING`` en las tres: la revisión tiene que poder
    reejecutarse a mano sobre una base a medias sin duplicar nada, que es la
    forma en que estos backfills se terminan aplicando de verdad.
    """
    tablas = _tablas()

    if "watchlist_items" in tablas:
        op.execute(
            "INSERT INTO follows "
            " (organization_id, user_id, user_key, target_type, target_id, kind,"
            "  visibility, created_at) "
            "SELECT organization_id, user_id, user_key, 'licitacion', id_externo, 'seguir',"
            f" COALESCE(NULLIF(visibility, ''), 'private'), {_fecha('created_at')} "
            "FROM watchlist_items "
            "ON CONFLICT ON CONSTRAINT uq_follows_user_target DO NOTHING"
        )

    if "watchlist_empresas" in tablas:
        # `empresa_id` es un entero; `target_id` es texto porque el tipo de
        # objetivo es polimórfico (ADR-031 §Riesgo: por eso no puede llevar FK).
        op.execute(
            "INSERT INTO follows "
            " (organization_id, user_key, target_type, target_id, kind,"
            "  visibility, created_at) "
            "SELECT organization_id, user_key, 'empresa', empresa_id::text, 'seguir',"
            f" COALESCE(NULLIF(visibility, ''), 'private'), {_fecha('created_at')} "
            "FROM watchlist_empresas "
            "ON CONFLICT ON CONSTRAINT uq_follows_user_target DO NOTHING"
        )

    if "radar_dismissals" in tablas:
        # `visibility` no existe en origen: un descarte siempre fue personal, y
        # lo sigue siendo. El día que se comparta será una decisión, no una
        # herencia del backfill.
        op.execute(
            "INSERT INTO follows "
            " (organization_id, user_key, target_type, target_id, kind,"
            "  visibility, hasta, created_at) "
            "SELECT organization_id, user_key, 'licitacion', id_externo, 'descartar',"
            f" 'private', hasta, {_fecha('created_at')} "
            "FROM radar_dismissals "
            "ON CONFLICT ON CONSTRAINT uq_follows_user_target DO NOTHING"
        )

    # `user_id` de las dos tablas que no lo tenían, con la misma derivación que
    # v129: `user_key = substr(sha256(lower(trim(email))), 1, 16)`.
    if "users" in tablas:
        op.execute(
            "UPDATE follows f SET user_id = u.id "
            "FROM users u "
            "WHERE f.user_id IS NULL AND f.user_key = substr("
            " encode(sha256(convert_to(lower(btrim("
            "  COALESCE(NULLIF(u.email, ''), 'user:' || u.id)"
            " )), 'UTF8')), 'hex'), 1, 16)"
        )


def _proteger(table: str) -> None:
    """Misma protección que v128, aplicada a la tabla que crea esta revisión."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_scope_{table} ON {table}")
    op.execute(
        f"CREATE POLICY tenant_scope_{table} ON {table} AS PERMISSIVE FOR ALL "
        f"USING ({_PREDICADO_TENANT}) WITH CHECK ({_PREDICADO_TENANT})"
    )
    op.execute(f"DROP POLICY IF EXISTS tenant_guard_{table} ON {table}")
    op.execute(
        f"CREATE POLICY tenant_guard_{table} ON {table} AS RESTRICTIVE FOR ALL "
        f"USING ({_PREDICADO_TENANT}) WITH CHECK ({_PREDICADO_TENANT})"
    )


def downgrade() -> None:
    """Tira la tabla entera.

    Se puede, y sin pérdida: mientras dure la fase aditiva ``follows`` es una
    copia y las tres tablas de origen siguen siendo la fuente de verdad. Deja
    de poderse el día que la lectura pase a ser solo de aquí — y ese día lo
    dirá otra revisión.
    """
    if not _is_postgres():
        return
    op.execute("DROP TABLE IF EXISTS follows")
