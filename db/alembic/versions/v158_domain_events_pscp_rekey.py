"""v158: los eventos de licitaciones PSCP que v153 dejó apuntando a la clave vieja.

Revision ID: v158_domain_events_pscp_rekey
Revises: v157_mv_canonicas_fuente
Create Date: 2026-10-24

Qué falla hoy
-------------
``v153`` llevó las licitaciones PSCP de ``pscp:{codi_expedient}`` a
``pscp:{uuid de la ficha}:{codi_expedient}`` y repuntó las 27 columnas que
guardan el id de una licitación, pero no ``domain_events.aggregate_id``: el
outbox (ADR-027) no tiene FK ni estaba en su lista. En producción quedaron
**1.117 eventos** (``aggregate_type = 'licitacion'``, todos
``licitacion.tecnologia_pliego``, todos ya despachados, medido el 2026-10-24)
cuyo ``aggregate_id`` no existe en ``licitaciones``. La historia del agregado
(``db.events.get_events('licitacion', id)``) no los encuentra desde la ficha.

Qué hace
--------
Repunta cada evento huérfano con la clave vieja a la licitación que hoy lleva
su mismo código: ``pscp:{codi}`` → la única fila ``pscp:{uuid}:{codi}``. El mapa
se deriva del propio id, igual que el de ``v153`` (el código va tal cual tras
el UUID, posición 43), así que no necesita ninguna tabla de alias.

Solo toca un evento si:

* es de una licitación (``aggregate_type = 'licitacion'``) con la clave vieja de
  PSCP y esa clave **no existe** en ``licitaciones`` (un evento correcto, o el
  de una fila PSCP sin ficha que conservó la clave vieja, no se mueve), y
* exactamente **una** licitación lleva ese código con la clave nueva. Dos o más
  es justo la colisión que motivó ``v153`` (dos órganos con el mismo código) y
  el id viejo no dice cuál era; ninguna es una licitación que ya no existe.

Los que no se pueden repuntar **no se borran**: el log es de solo añadir y un
evento de un agregado borrado sigue siendo historia. Se cuentan con ``NOTICE``.
En producción el 2026-10-24: 1.095 repuntables (1.068 con la misma tecnología
en ``licitacion_tecnologia_pliego`` de la fila destino), 0 ambiguos y 22 sin
candidata (11 licitaciones que ya no existen con ninguna clave, sin historial).

``payload_json`` no se toca: ninguno de estos eventos lleva el id en el
payload, y los despachados se quedan como se enviaron (RFC de identidad
PLACSP, tabla de repunte).

Idempotente: tras la primera pasada, el ``aggregate_id`` repuntado existe en
``licitaciones`` y el filtro ya no lo selecciona. ~1,1 k filas: una sola
sentencia, sin lotes.

``row_security = off`` por lo mismo que en ``v153``: con un rol al que la RLS
se le aplique, falla en vez de saltarse filas en silencio.

Un re-key futuro (la fase B del RFC de identidad PLACSP) tiene que llevar
``domain_events.aggregate_id`` en su lista de referencias desde el principio;
el RFC ya lo incluye.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from alembic import op

revision: str = "v158_domain_events_pscp_rekey"
down_revision: str | None = "v157_mv_canonicas_fuente"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

#: La misma expresión que ``v153._CLAVE_NUEVA``: ``pscp:{uuid}`` o
#: ``pscp:{uuid}:{codi}``.
_CLAVE_NUEVA = "^pscp:[0-9a-f-]{36}(:|$)"

#: Una clave nueva con código: el código empieza en la posición 43
#: (``pscp:`` + 36 del UUID + ``:``).
_CLAVE_NUEVA_CON_CODIGO = "^pscp:[0-9a-f-]{36}:"
_INICIO_CODIGO = 43

#: Eventos de licitación con la clave vieja de PSCP que no apuntan a ninguna fila.
_HUERFANOS = (
    "d.aggregate_type = 'licitacion' "
    "AND d.aggregate_id LIKE 'pscp:%' "
    f"AND d.aggregate_id !~ '{_CLAVE_NUEVA}' "
    "AND NOT EXISTS (SELECT 1 FROM licitaciones l WHERE l.id_externo = d.aggregate_id)"
)

#: Código → id nuevo, solo para los códigos que lleva una única licitación.
_CANDIDATAS = (
    f"SELECT substr(id_externo, {_INICIO_CODIGO}) AS codi, min(id_externo) AS nuevo, "
    "count(*) AS n "
    "FROM licitaciones "
    f"WHERE id_externo ~ '{_CLAVE_NUEVA_CON_CODIGO}' "
    f"GROUP BY substr(id_externo, {_INICIO_CODIGO})"
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _repunte() -> str:
    return (
        "UPDATE domain_events d SET aggregate_id = c.nuevo "
        f"FROM ({_CANDIDATAS}) c "
        f"WHERE {_HUERFANOS} AND c.n = 1 AND c.codi = substr(d.aggregate_id, 6)"
    )


def _aviso_restantes() -> str:
    return f"""
DO $$
DECLARE
    ambiguos bigint;
    sin_candidata bigint;
BEGIN
    SELECT count(*) FILTER (WHERE c.n > 1), count(*) FILTER (WHERE c.n IS NULL)
    INTO ambiguos, sin_candidata
    FROM domain_events d
    LEFT JOIN ({_CANDIDATAS}) c ON c.codi = substr(d.aggregate_id, 6)
    WHERE {_HUERFANOS};
    IF ambiguos + sin_candidata > 0 THEN
        RAISE NOTICE
            'v158: % eventos PSCP siguen con la clave vieja (% ambiguos, % sin licitación)',
            ambiguos + sin_candidata, ambiguos, sin_candidata;
    END IF;
END
$$"""


def sentencias_upgrade() -> list[str]:
    """Las sentencias de :func:`upgrade`, en orden (los tests las reaplican)."""
    return [
        # El rol de producción corta a los 30 s (ver v142); `SET LOCAL` se
        # deshace solo al cerrar la transacción.
        "SET LOCAL statement_timeout = 0",
        "SET LOCAL lock_timeout = '30s'",
        # Ver docstring: falla en vez de saltarse filas que la RLS esconda.
        "SET LOCAL row_security = off",
        _repunte(),
        _aviso_restantes(),
    ]


def upgrade() -> None:
    if not _is_postgres():
        return
    for sentencia in sentencias_upgrade():
        op.execute(sentencia)


def downgrade() -> None:
    """No-op deliberado, y se dice.

    La inversa sería devolver esos eventos a un id que no existe: no recupera
    nada y no se distinguen de los que ya nacieron con la clave nueva. Bajar de
    v158 deja los eventos repuntados, que es lo correcto también para v157.
    """
    return
