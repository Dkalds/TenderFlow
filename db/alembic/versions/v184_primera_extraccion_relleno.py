"""v184: rellena ``licitaciones.primera_extraccion`` donde quedó ``NULL``, sin re-notificar.

Revision ID: v184_primera_extraccion_relleno
Revises: v183_api_keys_activa_con_dueno
Create Date: 2026-11-16

Qué corrige
-----------
``v100`` creó ``primera_extraccion`` y la rellenó, pero ``db/upsert.py`` no la
escribió hasta la auditoría de 2026-11 (ahora sí, solo en el ``INSERT``). Toda
fila ingerida entre medias la tiene a ``NULL``: 77 032 de 134 437 medidas con el
MCP de solo lectura el 2026-11-16, y su sombra ``primera_extraccion_ts``
(``v159``) también, porque ``licitaciones`` no tiene trigger de sombras.
``db/repositories/cuentas.py`` filtra por la columna sin ``COALESCE``, así que
esas filas no salen ni en el aviso «publicación nueva» de una cuenta
(``publicaciones_nuevas``) ni en el bloque de publicaciones de su ficha
(``resumen``, ``publicaciones_de_cuenta``).

El valor, y por qué no re-notifica
----------------------------------
El aviso emite las filas con ``primera_extraccion`` en ``(cursor, marca]``,
comparando texto, y el cursor (``ingestion_cursors``, fuente
``outbox_cuentas_publicaciones``) solo avanza. Estas filas nunca se avisaron: si
el relleno las pusiera por encima del cursor saldrían ahora, de golpe, como
publicaciones nuevas que tienen semanas. Por eso el valor es::

    LEAST(estimación, cursor - 1 hora)

con ``now() - 1 hora`` si el cursor aún no existe (su primera pasada lo fija en
``ahora - MARGEN_COMMIT_CUENTAS``, diez minutos, y no emite nada). La hora de
margen hace que el texto escrito quede por debajo del cursor también al
compararlo como texto, aunque uno lleve microsegundos y el otro no.

La estimación es lo más temprano que se sabe de la fila:

* ``fecha_publicacion``: la fecha que declara la fuente. Ordena la ficha como
  la ve el usuario, y una fuente que se ingirió tarde (contratos de 2012
  entrados después de ``v100``) no los pinta como recientes.
* ``MIN(captured_at)`` de ``licitaciones_history``: un momento en que la fila ya
  existía, la misma cota que usó ``v100``.
* Si no hay ninguna de las dos (116 filas el 2026-11-16), la fecha de ``v100``
  (2026-09-03): la fila no se veía antes de que la columna existiera, así que es
  la cota inferior de su primer avistamiento.

``fecha_extraccion`` no entra: las reingestas la re-sellan en cada pasada, así
que para casi todas valdría «hace un rato» y la ficha las enseñaría como nuevas.

El texto se escribe en el formato de ``now_utc_iso()`` (``…T…+00:00``), el que
ya escribe el upsert, y la sombra con el mismo instante.

Efecto en la clave canónica
---------------------------
``clave_canonica_sql`` usa ``coalesce(fecha_publicacion, primera_extraccion,
fecha_extraccion)``: solo cambia la componente de las filas sin
``fecha_publicacion``, que hasta ahora se movía con ``fecha_extraccion`` cada
mes y desde aquí queda fija (lo que buscaba ``v100``). ``mv_licitaciones_canonicas``
lo recoge en su siguiente refresco programado.

Orden de despliegue
-------------------
**Después** del código que escribe la columna en el ``INSERT``: aplicada antes,
las filas que entren entre la migración y el despliegue nacerían otra vez a
``NULL`` y esta revisión ya no volvería a correr.

Coste
-----
Un único ``UPDATE`` de las filas a ``NULL``, como el de ``v100`` (692k filas en
una sentencia); son unas 77k, y el índice ``idx_hist_externo`` resuelve cada
subconsulta de la historia. ``statement_timeout = 0`` porque puede pasar de los
30 s del rol, y ``lock_timeout`` para no quedarse esperando detrás de una
ingesta que tenga bloqueadas las mismas filas. Idempotente: una segunda pasada
no encuentra filas.

Downgrade: no-op deliberado. Lo rellenado no se distingue de lo que escribió el
upsert, y volver a ``NULL`` solo escondería otra vez esas filas.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from alembic import op

revision: str = "v184_primera_extraccion_relleno"
down_revision: str | None = "v183_api_keys_activa_con_dueno"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

#: Copia congelada de ``services.avisos_outbox.CURSOR_CUENTAS``: una migración
#: no importa la app, y ese nombre es un dato ya escrito en producción.
CURSOR_CUENTAS = "outbox_cuentas_publicaciones"

#: ``Create Date`` de ``v100``: cota inferior para la fila sin otra fecha.
SUELO_V100 = "2026-09-03 00:00:00+00"

RELLENAR = (
    "WITH corte AS ("
    "  SELECT COALESCE("
    "    (SELECT nucleo_iso_a_timestamptz(last_seen_updated) FROM ingestion_cursors "
    f"    WHERE source = '{CURSOR_CUENTAS}'), now()) - interval '1 hour' AS ts"
    "), estimado AS ("
    "  SELECT l.id_externo, LEAST("
    "    COALESCE(LEAST("
    "      nucleo_iso_a_timestamptz(l.fecha_publicacion), "
    "      (SELECT MIN(nucleo_iso_a_timestamptz(h.captured_at)) FROM licitaciones_history h "
    "       WHERE h.id_externo = l.id_externo)"
    f"    ), TIMESTAMPTZ '{SUELO_V100}'), "
    "    (SELECT ts FROM corte)) AS ts "
    "  FROM licitaciones l WHERE l.primera_extraccion IS NULL"
    ") "
    "UPDATE licitaciones l SET "
    "  primera_extraccion = "
    "    to_char(e.ts AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"+00:00\"'), "
    "  primera_extraccion_ts = e.ts "
    "FROM estimado e "
    "WHERE l.id_externo = e.id_externo AND l.primera_extraccion IS NULL"
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute("SET statement_timeout = 0")
    op.execute("SET lock_timeout = '30s'")
    op.execute(RELLENAR)
    op.execute("RESET lock_timeout")
    op.execute("RESET statement_timeout")


def downgrade() -> None:
    """No-op: ver el docstring del módulo."""
