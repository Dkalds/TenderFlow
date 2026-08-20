"""v88: ``documentos.source_hash`` — identidad estable de un adjunto.

Revision ID: v88_documentos_source_hash
Revises: v87_unaccent_extension
Create Date: 2026-08-18

Los adjuntos de PLACSP se referencian con dos familias de URI y solo una es
estable. El 82% de las 37.953 filas de ``documentos`` usa
``GetDocumentByIdServlet?cifrado=…&DocumentIdParam=<token>``, y ese token lo
**re-emite** la plataforma: cuando caduca, el servlet responde 500
(NullPointerException), no 404. Como el token forma parte de la ``uri``, el
``ON CONFLICT(licitacion_id, uri) DO NOTHING`` de ``upsert_meta`` no reconocía
el documento re-publicado y **insertaba una fila nueva** en cada rotación —262
grupos ya duplicados así, 637 filas sobrantes, medido el 2026-08-18—.

El CODICE sí publica identidad estable y el parser la ignoraba: sobre el feed
Atom vivo (390 entries, 1.323 ``DocumentReference``) el 100% trae
``cbc:DocumentHash``, un hash del contenido que **no cambia** cuando rota el
token. Esta revisión le da sitio en el esquema.

Por qué el índice es ``(licitacion_id, tipo, source_hash)`` y no
``(licitacion_id, tipo)``
-------------------------------------------------------------------------
Porque ``(licitacion_id, tipo)`` **no** identifica un documento: 3.997 grupos
de la tabla tienen varias filas del mismo tipo creadas el mismo día, y son
legítimas —un expediente publica varios anexos, o varios PCAP por lotes—. Lo
que la rotación duplica son filas del mismo ``(licitacion_id, tipo)`` en días
distintos; solo el hash distingue un caso del otro.

Coste
-----
``ADD COLUMN`` nullable y sin ``DEFAULT`` es un cambio de catálogo: no reescribe
la tabla (a diferencia de v68, que con una columna generada STORED bloqueó
``licitaciones`` más de 30 minutos). El índice parcial **nace vacío** —ninguna
fila tiene todavía ``source_hash``, y el predicado excluye los NULL—, así que
se crea en tiempo constante y no puede fallar por duplicados preexistentes. Por
eso no se emite ``CONCURRENTLY``: el patrón de v72/v79 es para índices sobre
``licitaciones`` (1,6 M filas, caliente); ``documentos`` tiene 38 k filas y solo
la escribe el cron nocturno.

Reparación de datos (paso 3)
----------------------------
De los 2.556 documentos en ``status='error'``, **1.702 (el 66%) no tienen nada
malo**: fallaron con el circuit breaker abierto —es decir, ni se intentó la
descarga— y ``fetch_and_extract`` los marcaba como error terminal, que los saca
de ``list_pendientes`` para siempre. Se devuelven a ``pending``. El fetcher ya
no vuelve a hacerlo (devuelve ``"skipped"`` y deja la fila intacta), así que
esto es una limpieza única, no recurrente. Precedente de reparación de datos en
una migración: ``v67_pg_short_tz_offset_repair``.

Esa reparación **no es reversible**: al volver a ``pending`` se pierde qué
filas estaban en error. El ``downgrade`` solo retira columna e índice y lo
declara explícitamente.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v88_documentos_source_hash"
down_revision: str | Sequence[str] | None = "v87_unaccent_extension"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mismo formato que db.connection.now_utc_iso(). NO usar ``NOW()::text``:
# Postgres omite los minutos del offset cuando son cero (``+00`` en vez de
# ``+00:00``) y eso no cumple RFC3339 estricto — es exactamente el bug que v67
# tuvo que ir a reparar a mano.
_NOW_ISO_TEXT = "to_char(NOW() AT TIME ZONE 'utc', 'YYYY-MM-DD\"T\"HH24:MI:SS.US') || '+00:00'"

_ADD_SOURCE_HASH = "ALTER TABLE documentos ADD COLUMN IF NOT EXISTS source_hash TEXT"

_CREATE_UNIQUE_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_documentos_lic_tipo_hash "
    "ON documentos (licitacion_id, tipo, source_hash) "
    "WHERE source_hash IS NOT NULL"
)

# Los dos mensajes observados en producción son
# «Timeout not elapsed yet, circuit breaker still open» (1.681 filas) y
# «Failures threshold reached, circuit breaker opened» (21); ambos contienen la
# subcadena «circuit breaker».
#
# Se usa ``strpos`` y no ``ILIKE '%circuit breaker%'`` a propósito: ``op.execute``
# entrega la sentencia a SQLAlchemy y de ahí al driver, y si en ese camino la
# cadena se trata como plantilla con parámetros, el ``%`` hay que duplicarlo —
# pero si NO se trata así, el ``%%`` llega literal a Postgres y el patrón no
# casa con nada. Las dos variantes fallan **en silencio**: la migración
# terminaría en verde reparando 0 filas. Ninguna otra migración del repo usa
# ``LIKE``, así que no hay precedente que zanje cuál de las dos aplica aquí;
# ``strpos`` no tiene ese problema porque no lleva comodines.
_REPAIR_BREAKER_VICTIMS = f"""
UPDATE documentos
   SET status = 'pending',
       error_detail = NULL,
       updated_at = {_NOW_ISO_TEXT}
 WHERE status = 'error'
   AND strpos(lower(coalesce(error_detail, '')), 'circuit breaker') > 0
"""

_DROP_UNIQUE_INDEX = "DROP INDEX IF EXISTS uq_documentos_lic_tipo_hash"
_DROP_SOURCE_HASH = "ALTER TABLE documentos DROP COLUMN IF EXISTS source_hash"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute(_ADD_SOURCE_HASH)
    op.execute(_CREATE_UNIQUE_INDEX)
    op.execute(_REPAIR_BREAKER_VICTIMS)


def downgrade() -> None:
    """Retira columna e índice.

    No restaura el ``status='error'`` de las filas reparadas en el upgrade: esa
    información no se conserva en ningún sitio, y volver a marcarlas por el
    patrón del ``error_detail`` es imposible porque el upgrade lo puso a NULL.
    Bajar de esta revisión deja esos documentos en la cola de pendientes, que
    es el estado correcto para ellos de todas formas.
    """
    if not _is_postgres():
        return
    op.execute(_DROP_UNIQUE_INDEX)
    op.execute(_DROP_SOURCE_HASH)
