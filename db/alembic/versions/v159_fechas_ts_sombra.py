"""v159: sombras ``*_ts timestamptz`` de 14 fechas en texto (fase 1 de «fechas a timestamptz»).

Revision ID: v159_fechas_ts_sombra
Revises: v158_domain_events_pscp_rekey
Create Date: 2026-10-25

Qué resuelve
------------
Las fechas son ``text`` ISO en casi todo el esquema, y cada comparación y cada
orden depende de que todos los escritores usen el mismo formato. No lo usaron:
en producción conviven ``2026-09-04T09:38:20.097671+00:00`` y
``2026-09-04 09:38:20.097671+00`` en ``licitaciones.fecha_extraccion``, y
``' ' < 'T'`` es exactamente el fallo de «desde tu última visita» que arreglaron
``v151``/``v152``. Esta revisión es el primer paso para que el **tipo** lo
impida: una columna ``timestamptz`` al lado de cada fecha de texto de las tablas
calientes, sin tocar la vieja.

Columnas (``<columna>_ts`` junto a cada una)
--------------------------------------------
* ``licitaciones``: ``fecha_extraccion``, ``primera_extraccion``,
  ``fecha_inicio``, ``fecha_fin``, ``fecha_actualizacion_fuente``. Las otras dos
  fechas ya tienen sombra desde ``v133``.
* ``adjudicaciones.fecha_adjudicacion``
* ``licitaciones_history.captured_at``
* ``documentos``: ``created_at``, ``fetched_at``, ``updated_at``
* ``pursuit_events.created_at``
* ``user_notifications``: ``created_at``, ``read_at``

La conversión es ``nucleo_iso_a_timestamptz`` (``v133``), la misma de las
sombras del núcleo tipado y con la misma gemela Python
(``db.nucleo_tipado.a_timestamptz``): fecha sola → medianoche UTC, sin offset →
UTC, con offset → su instante, cualquier otra cosa → ``NULL``.

Quién escribe la sombra
-----------------------
* ``licitaciones``: la escritura dual de ``db/upsert.py``, como las de ``v133``
  —el único escritor masivo, y la tabla más caliente: un trigger plpgsql por
  fila en cada ingesta de 1,6 M filas es un coste que la escritura dual no
  tiene—. ``primera_extraccion`` no la escribe hoy nadie salvo ``v100``, así
  que su sombra sólo la rellena el backfill.
* El resto: un trigger ``BEFORE INSERT OR UPDATE OF <columnas>`` por tabla. Sus
  escritores están repartidos (``documentos`` tiene once ``UPDATE`` distintos y
  un ``DEFAULT``; ``user_notifications``, dos módulos), y el trigger cubre a
  todos, a los ``DEFAULT`` incluidos, sin tocar ninguno.

El trigger se crea **antes** del relleno: una fila insertada mientras corre el
backfill ya nace con su sombra, y el backfill solo tiene que alcanzar a las que
existían.

Relleno
-------
``pursuit_events`` y ``user_notifications`` son diminutas (54 y 60 filas en
producción el 2026-10-25) y se rellenan aquí. ``pursuit_events`` es un ledger
append-only (trigger de ``v61``): se pausa solo alrededor de su ``UPDATE``. El
resto lo rellena ``scripts/backfill_fechas_ts.py`` por lotes fuera de la
migración (``docs/runbooks/fechas-ts-ventana.md``).

Por qué no bloquea
------------------
``ADD COLUMN`` nullable y sin default es solo de catálogo desde Postgres 11; el
``lock_timeout`` evita que el ``ACCESS EXCLUSIVE`` de un instante se quede
esperando detrás de una consulta larga y encole la tabla detrás de él. Los
índices van en ``v160`` (``CONCURRENTLY``) y **después** del backfill, por el
mismo motivo que ``v134``.

Fase 2 (no aquí)
----------------
Retirar las columnas de texto exige que todos los lectores lean ya la sombra;
queda escrita en el ítem del backlog.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from alembic import op

revision: str = "v159_fechas_ts_sombra"
down_revision: str | None = "v158_domain_events_pscp_rekey"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

#: Tabla → columnas de texto que reciben sombra ``<columna>_ts``. Congelado:
#: ``db.fechas_ts.TABLAS`` debe describir lo mismo (lo fija
#: ``tests/test_unit_fechas_ts.py``), pero una migración no importa código vivo.
COLUMNAS: dict[str, tuple[str, ...]] = {
    "licitaciones": (
        "fecha_extraccion",
        "primera_extraccion",
        "fecha_inicio",
        "fecha_fin",
        "fecha_actualizacion_fuente",
    ),
    "adjudicaciones": ("fecha_adjudicacion",),
    "licitaciones_history": ("captured_at",),
    "documentos": ("created_at", "fetched_at", "updated_at"),
    "pursuit_events": ("created_at",),
    "user_notifications": ("created_at", "read_at"),
}

#: Tablas cuya sombra mantiene un trigger (las demás, la escritura dual).
CON_TRIGGER: tuple[str, ...] = (
    "adjudicaciones",
    "licitaciones_history",
    "documentos",
    "pursuit_events",
    "user_notifications",
)

#: Tablas que se rellenan en la migración (las demás, el script por lotes).
RELLENO_EN_MIGRACION: tuple[str, ...] = ("pursuit_events", "user_notifications")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _funcion(tabla: str) -> str:
    return f"fechas_ts_{tabla}"


def _trigger(tabla: str) -> str:
    return f"trg_fechas_ts_{tabla}"


def _sql_funcion(tabla: str) -> str:
    asignaciones = " ".join(
        f"NEW.{col}_ts := nucleo_iso_a_timestamptz(NEW.{col});" for col in COLUMNAS[tabla]
    )
    return (
        f"CREATE OR REPLACE FUNCTION {_funcion(tabla)}() "
        "RETURNS trigger LANGUAGE plpgsql AS $$ "
        f"BEGIN {asignaciones} RETURN NEW; END; $$"
    )


def _sql_trigger(tabla: str) -> str:
    # `pursuit_events` no admite UPDATE (append-only): con INSERT basta.
    evento = (
        "INSERT"
        if tabla == "pursuit_events"
        else f"INSERT OR UPDATE OF {', '.join(COLUMNAS[tabla])}"
    )
    return (
        f"CREATE TRIGGER {_trigger(tabla)} BEFORE {evento} ON {tabla} "
        f"FOR EACH ROW EXECUTE FUNCTION {_funcion(tabla)}()"
    )


def _sql_rellenar(tabla: str) -> str:
    asignaciones = ", ".join(
        f"{col}_ts = nucleo_iso_a_timestamptz({col})" for col in COLUMNAS[tabla]
    )
    divergente = " OR ".join(
        f"{col}_ts IS DISTINCT FROM nucleo_iso_a_timestamptz({col})" for col in COLUMNAS[tabla]
    )
    return f"UPDATE {tabla} SET {asignaciones} WHERE {divergente}"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute("SET LOCAL lock_timeout = '5s'")
    for tabla, columnas in COLUMNAS.items():
        nuevas = ", ".join(f"ADD COLUMN IF NOT EXISTS {col}_ts timestamptz" for col in columnas)
        op.execute(f"ALTER TABLE {tabla} {nuevas}")
    for tabla in CON_TRIGGER:
        op.execute(_sql_funcion(tabla))
        op.execute(f"REVOKE EXECUTE ON FUNCTION {_funcion(tabla)}() FROM PUBLIC")
        op.execute(f"DROP TRIGGER IF EXISTS {_trigger(tabla)} ON {tabla}")
        op.execute(_sql_trigger(tabla))
    for tabla in RELLENO_EN_MIGRACION:
        if tabla == "pursuit_events":
            op.execute("ALTER TABLE pursuit_events DISABLE TRIGGER trg_pursuit_events_append_only")
        op.execute(_sql_rellenar(tabla))
        if tabla == "pursuit_events":
            op.execute("ALTER TABLE pursuit_events ENABLE TRIGGER trg_pursuit_events_append_only")
    # Alembic puede aplicar varias revisiones en la misma transacción: el
    # ``SET LOCAL`` no debe acotar los locks de las que vengan detrás.
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("SET LOCAL lock_timeout = '5s'")
    for tabla in CON_TRIGGER:
        op.execute(f"DROP TRIGGER IF EXISTS {_trigger(tabla)} ON {tabla}")
        op.execute(f"DROP FUNCTION IF EXISTS {_funcion(tabla)}()")
    for tabla, columnas in COLUMNAS.items():
        fuera = ", ".join(f"DROP COLUMN IF EXISTS {col}_ts" for col in columnas)
        op.execute(f"ALTER TABLE {tabla} {fuera}")
    op.execute("RESET lock_timeout")
