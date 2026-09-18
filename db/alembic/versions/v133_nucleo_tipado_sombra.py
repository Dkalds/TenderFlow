"""v133: columnas sombra tipadas en ``licitaciones`` (T2, «núcleo tipado»).

Revision ID: v133_nucleo_tipado_sombra
Revises: v132_informes_programados
Create Date: 2026-09-18

Qué resuelve
------------
Las fechas de ``licitaciones`` son ``text`` ISO-8601 y ``importe`` y
``duracion_valor`` son ``real`` (float4) en producción —el schema de un
bootstrap nuevo los crea ``double precision``, ver la nota de deriva del ítem
P2 del backlog—. Dos consecuencias medidas:

* El round-trip float8 → float4 → float8 fabrica diffs falsos de ``importe``
  (1.785 filas de historial basura en ocho días, 2026-08-16). Hoy lo tapa
  ``shared.numeric.values_equal`` con una tolerancia que además es ciega a
  cambios reales por debajo del 0,001 %.
* Cualquier consulta que necesite aritmética de fechas castea fila a fila, y
  los filtros de rango dependen de ``iso_guard`` (rango lexicográfico).

Qué hace
--------
Añade **cuatro columnas sombra** nullable, sin default y sin índices:

* ``fecha_publicacion_ts timestamptz``
* ``fecha_limite_ts timestamptz``
* ``importe_num numeric(14,2)`` — el nombre y el tipo que fija el plan
  (``docs/plans/2026-09-plan-arquitectura-v2.md`` §6 T2). Absorbe la columna
  ``importe_f8`` que proponía el backlog: una sola sombra para el importe, y
  exacta. Un importe es dinero en céntimos; ``numeric`` lo guarda tal cual lo
  escribió el conector y el round-trip es exacto por construcción, que es el
  criterio de aceptación del plan.
* ``duracion_valor_num numeric`` — el backlog pide «``duracion_valor`` con el
  mismo criterio (mismo tipo, mismo ruido)». Sin precisión fija a propósito: no
  es dinero, y redondearla a dos decimales cambiaría el dato.

Y la función ``nucleo_iso_a_timestamptz(text)``, que traduce el texto ISO a
``timestamptz`` con la misma regla que su gemela Python
(``db.nucleo_tipado.a_timestamptz``): fecha sola → medianoche UTC; fecha y hora
sin offset → UTC; con offset → el instante que dice el offset; cualquier otra
cosa → ``NULL``. La usa el backfill por lotes (``scripts/backfill_nucleo_tipado.py``)
y la verificación; **no** se usa en ningún índice ni columna generada, así que
basta con ``STABLE``.

Por qué no bloquea
------------------
``ADD COLUMN`` nullable y sin default es un cambio **solo de catálogo** desde
Postgres 11: no reescribe la tabla. Toma ``ACCESS EXCLUSIVE`` un instante, pero
un instante que puede quedarse **esperando** detrás de una consulta larga y,
mientras espera, bloquear todo lo que llegue después. Por eso ``lock_timeout``:
si no consigue el lock en cinco segundos, la migración falla limpia y se
reintenta, en vez de encolar la tabla núcleo detrás de un ``SELECT`` de 30 s.

Contraste deliberado con ``v68``: aquella columna era ``GENERATED ... STORED``,
que **sí** reescribe la tabla (>30 min con lock exclusivo en producción). Aquí
el relleno lo hace el backfill por lotes, fuera de la migración, y la escritura
dual de ``db/upsert.py`` a partir de este despliegue.

Los índices van en ``v134`` (``CONCURRENTLY``), y **después** del backfill: un
índice sobre una columna que el backfill va a reescribir entera convierte cada
``UPDATE`` en no-HOT y multiplica el WAL. El runbook
(``docs/runbooks/nucleo-tipado-ventana.md``) fija ese orden.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from alembic import op

revision: str = "v133_nucleo_tipado_sombra"
down_revision: str | None = "v132_informes_programados"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

# Gemela SQL de ``db.nucleo_tipado.a_timestamptz``. Si una cambia, cambia la
# otra (y como las migraciones son append-only, la de aquí sólo cambia con una
# revisión nueva que haga ``CREATE OR REPLACE``). Las expresiones regulares son
# las mismas, carácter a carácter, que ``_RE_SOLO_FECHA``/``_RE_FECHA_HORA``.
#
# El bloque ``EXCEPTION`` (clase ``22``, ``data_exception``) cubre lo que casa
# con el patrón pero no es una fecha (``2026-02-30``, ``2026-13-01``, un offset
# ``+99``): la gemela Python devuelve ``None`` en esos
# casos y la SQL tiene que hacer lo mismo en vez de abortar el lote entero.
# El año ``0000`` y la hora ``24`` se rechazan antes porque Postgres los acepta
# (año 1 a. C., medianoche del día siguiente) y Python no: sin esa guarda las
# dos gemelas discreparían justo en la basura.
_FN_ISO_A_TIMESTAMPTZ = r"""
CREATE OR REPLACE FUNCTION nucleo_iso_a_timestamptz(v text)
RETURNS timestamptz
LANGUAGE plpgsql
STABLE
STRICT
PARALLEL SAFE
AS $$
BEGIN
    IF substr(v, 1, 4) = '0000' THEN
        RETURN NULL;
    END IF;
    IF v ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN
        RETURN (v || 'T00:00:00+00:00')::timestamptz;
    END IF;
    IF v ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}(:[0-9]{2}(\.[0-9]{1,6})?)?(Z|[+-][0-9]{2}(:?[0-9]{2})?)?$' THEN
        IF substr(v, 12, 2) = '24' THEN
            RETURN NULL;
        END IF;
        IF v ~ '(Z|[+-][0-9]{2}(:?[0-9]{2})?)$' THEN
            RETURN v::timestamptz;
        END IF;
        RETURN (v || '+00:00')::timestamptz;
    END IF;
    RETURN NULL;
EXCEPTION
    WHEN data_exception THEN
        RETURN NULL;
END
$$;
"""


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute(_FN_ISO_A_TIMESTAMPTZ)
    # v59 revocó EXECUTE a PUBLIC por defecto en funciones nuevas; el rol de la
    # aplicación es el dueño de las migraciones, así que no hace falta GRANT.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        "ALTER TABLE licitaciones "
        "ADD COLUMN IF NOT EXISTS fecha_publicacion_ts timestamptz, "
        "ADD COLUMN IF NOT EXISTS fecha_limite_ts timestamptz, "
        "ADD COLUMN IF NOT EXISTS importe_num numeric(14,2), "
        "ADD COLUMN IF NOT EXISTS duracion_valor_num numeric"
    )
    # Alembic puede aplicar varias revisiones en la misma transacción: el
    # ``SET LOCAL`` no debe acotar los locks de las que vengan detrás.
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        "ALTER TABLE licitaciones "
        "DROP COLUMN IF EXISTS duracion_valor_num, "
        "DROP COLUMN IF EXISTS importe_num, "
        "DROP COLUMN IF EXISTS fecha_limite_ts, "
        "DROP COLUMN IF EXISTS fecha_publicacion_ts"
    )
    op.execute("RESET lock_timeout")
    op.execute("DROP FUNCTION IF EXISTS nucleo_iso_a_timestamptz(text)")
