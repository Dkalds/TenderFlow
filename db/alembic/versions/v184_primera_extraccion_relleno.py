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

La estimación es::

    GREATEST(suelo, LEAST(fecha_publicacion, MIN(captured_at)))

* El **suelo** es el instante del relleno de ``v100``: el mayor valor que dejó
  en producción es ``2026-09-04T08:29:46.152168+00:00`` (medido el 2026-11-16),
  y el suelo es el minuto siguiente, ``2026-09-04T08:30:00``. Una fila está a
  ``NULL`` porque entró después de ese relleno, así que no se vio antes; y el
  suelo la deja por detrás, comparando texto, de toda gemela que rellenó
  ``v100`` (ver «Efecto en la canónica»).
* ``fecha_publicacion``, cuando cae después del suelo: ordena la ficha como la
  ve el usuario. Antes del suelo no sirve (un contrato de 2012 ingerido en
  octubre se vio en octubre, no en 2012).
* ``MIN(captured_at)`` de ``licitaciones_history``: un momento en que la fila ya
  existía, la misma cota que usó ``v100``.
* Sin ninguna de las dos (116 filas el 2026-11-16), el suelo: ``GREATEST``
  ignora los ``NULL``.

``fecha_extraccion`` no entra: las reingestas la re-sellan en cada pasada, así
que para casi todas valdría «hace un rato» y la ficha las enseñaría como nuevas.

El texto se escribe en el formato de ``now_utc_iso()`` (``…T…+00:00``), el que
ya escribe el upsert, y la sombra con el mismo instante.

Efecto en la canónica
---------------------
``primera_extraccion`` entra en dos sitios de ``db/sql_fragments.py``, y los
dos los congela el cuerpo de ``mv_licitaciones_canonicas``, que lo recoge en su
siguiente refresco programado:

* El **desempate** de la canónica (``_criterios_canonicos_sql``: rango de
  fuente, ``fecha_publicacion`` y después ``coalesce(primera_extraccion,
  fecha_extraccion)``), para **todas** las filas. Una fila a ``NULL`` desempata
  hoy por su ``fecha_extraccion``, reciente, y pierde frente a su gemela
  rellenada por ``v100`` (≤ ``08:29:46`` del 2026-09-04). Con el suelo sigue
  perdiendo, así que la canónica y la URL del sitemap de esos grupos no
  cambian: con ``fecha_publicacion`` como relleno, sin suelo, la fila ganaba y
  cambiaba la URL de hasta 313 grupos (1 317 pares con la misma clave, el mismo
  rango y la misma publicación, medidos el 2026-11-16), lo que ``v100`` se
  escribió para evitar. Entre dos gemelas que estaban las dos a ``NULL`` el
  orden puede cambiar una vez; hasta hoy lo movía cada reingesta.
* El **año-mes** de la clave (``periodo_publicacion_sql``), solo para las filas
  sin ``fecha_publicacion``: hasta ahora se movía con ``fecha_extraccion`` cada
  mes y desde aquí queda fijo, lo que buscaba ``v100``.

Efecto en la auditoría del importe
----------------------------------
``domain_truth_audit.importe_sin_base_declarada`` cuenta como «nuevas» las filas
con ``COALESCE(primera_extraccion, fecha_extraccion) >= '2026-09-06'``. Las
66 940 filas a ``NULL`` con importe y publicadas antes de esa fecha cuentan hoy
por su ``fecha_extraccion`` y, con el suelo, salen de esa población (sobre
76 540 el 2026-11-16; 0 sin tipo entre ellas, así que no se esconde ningún
fallo). Las filas que entren desde el despliegue del upsert sí cuentan: llevan
la fecha real.

Orden de despliegue
-------------------
**Después** del código que escribe la columna en el ``INSERT``: aplicada antes,
las filas que entren entre la migración y el despliegue nacerían otra vez a
``NULL`` y esta revisión ya no volvería a correr. Y después de ``v183``, que
tiene su propio paso previo del propietario (las claves de API sin dueño): las
dos van juntas en ``alembic upgrade head``.

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

#: El minuto siguiente al mayor valor que escribió el relleno de ``v100``
#: (``2026-09-04T08:29:46.152168+00:00`` en producción): ver el docstring.
SUELO_V100 = "2026-09-04 08:30:00+00"

RELLENAR = (
    "WITH corte AS ("
    "  SELECT COALESCE("
    "    (SELECT nucleo_iso_a_timestamptz(last_seen_updated) FROM ingestion_cursors "
    f"    WHERE source = '{CURSOR_CUENTAS}'), now()) - interval '1 hour' AS ts"
    "), estimado AS ("
    "  SELECT l.id_externo, LEAST("
    f"    GREATEST(TIMESTAMPTZ '{SUELO_V100}', LEAST("
    "      nucleo_iso_a_timestamptz(l.fecha_publicacion), "
    "      (SELECT MIN(nucleo_iso_a_timestamptz(h.captured_at)) FROM licitaciones_history h "
    "       WHERE h.id_externo = l.id_externo)"
    "    )), "
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
