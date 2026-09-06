"""v103: el binario del pliego se conserva, y una página sabe si vino de OCR.

Tres cambios pequeños que sostienen el stream S8 del plan de arquitectura
2026-09 v2 (`docs/plans/2026-09-plan-arquitectura-v2.md`, §5 S8):

1. ``documentos.blob_key`` — clave del binario en el almacén de objetos
   (``shared/object_store.py``, ``documentos/{source_hash}``). Hasta hoy el
   binario se procesaba en memoria y se descartaba, así que **re-extraer
   exigía volver a PLACSP**; y los enlaces de PLACSP llevan un token rotativo
   que caduca (el 82% de las URIs antiguas, medido en ``v88``). Con la clave
   persistida, reprocesar es una lectura local.
2. ``documentos.status`` admite ``'unsupported'``. Antes, un DOCX o un ZIP
   caían en ``'error'``, indistinguibles de un PDF corrupto o de una descarga
   rota: no se podía contar cuánta cobertura faltaba por formato, que es justo
   lo que S8.2 viene a cerrar. El ``CHECK`` de ``v56`` los prohibía, así que
   hay que rehacerlo.
3. ``documento_pages.ocr`` — si el texto de esa página lo produjo el OCR
   (``ocrmypdf``) en vez del extractor de texto del PDF. La ficha del pliego
   cita páginas (``EvidenceRef``) y quien lee una cita necesita saber si el
   texto es transcripción automática de una imagen: el OCR se equivoca de otra
   manera que el copiado de texto, y el lector tiene que poder desconfiar.

Por qué ``blob_key`` y no la ``storage_key`` que ``v56`` dejó reservada
-----------------------------------------------------------------------
``v56`` creó ``storage_key TEXT`` con el comentario «reservado (NULL) para
añadir blobs en el futuro sin otra migración», y en tres meses no la escribió
nadie: sigue nula en todas las filas. Reutilizarla habría ahorrado esta columna,
pero su nombre no dice **de qué almacén** es la clave y el plan nombra
``blob_key`` de forma explícita en su criterio de aceptación. Se añade la
columna nombrada y ``storage_key`` queda como lo que siempre fue: vestigial. Su
retirada es un cambio destructivo que merece su propia revisión y su propio OK.

Coste
-----
``ADD COLUMN`` nullable sin ``DEFAULT`` (``blob_key``) es un cambio de catálogo:
no reescribe la tabla. ``documento_pages.ocr`` sí lleva ``DEFAULT false``, pero
desde Postgres 11 un default **constante** tampoco reescribe la tabla (se guarda
en el catálogo y se materializa al reescribir cada fila). El ``CHECK`` nuevo sí
recorre ``documentos`` para validar: son ~38 k filas y sólo la escribe el cron
nocturno, así que no hace falta el baile de ``NOT VALID`` + ``VALIDATE``.

DIALECT-GUARDED: solo actúa en Postgres.

Revision ID: v103_documentos_blob_ocr
Revises: v102_mv_canonicas_clave_inmutable
Create Date: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v103_documentos_blob_ocr"
down_revision: str | Sequence[str] | None = "v102_mv_canonicas_clave_inmutable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Vocabulario de ``documentos.status`` a partir de esta revisión.
_STATUS_NUEVOS = ("pending", "downloaded", "extracted", "error", "unsupported")
_STATUS_ANTERIORES = ("pending", "downloaded", "extracted", "error")

_CONSTRAINT = "documentos_status_check"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _check_status(valores: tuple[str, ...]) -> str:
    literales = ", ".join(f"'{v}'" for v in valores)
    return f"ALTER TABLE documentos ADD CONSTRAINT {_CONSTRAINT} CHECK (status IN ({literales}))"


#: El ``CHECK`` de ``v56`` es inline y sin nombre, así que Postgres lo bautizó
#: (``documentos_status_check``). El nombre es determinista pero no está
#: garantizado por el estándar: se tiran **todas** las restricciones CHECK de
#: la tabla cuya definición mencione ``'downloaded'``, que sólo puede ser ésa.
#: Sin esto, un bautizo distinto dejaría la restricción vieja en pie y el primer
#: documento ``unsupported`` reventaría en producción, no aquí.
#:
#: Ni ``LIKE '%…%'`` ni ``format('%I', …)``: el ``%`` es el problema que ``v88``
#: dejó documentado. ``op.execute`` entrega la sentencia a SQLAlchemy y de ahí
#: al driver, y según si en ese camino se trata como plantilla con parámetros
#: hay que duplicarlo o no — y las dos variantes fallan **en silencio**.
#: ``strpos`` y ``quote_ident`` hacen lo mismo sin comodines.
#:
#: ``'documentos'::regclass`` y no ``rel.relname = 'documentos'``: los tests
#: proyectan el schema entero en un schema propio por test, y comparar por
#: nombre encontraría la tabla de otro. ``regclass`` resuelve por ``search_path``,
#: que es la misma tabla que van a alterar las sentencias de al lado.
_DROP_CHECK_ANTERIOR = """
DO $$
DECLARE
    nombre text;
BEGIN
    FOR nombre IN
        SELECT con.conname
          FROM pg_constraint con
         WHERE con.conrelid = 'documentos'::regclass
           AND con.contype = 'c'
           AND strpos(pg_get_constraintdef(con.oid), 'downloaded') > 0
    LOOP
        EXECUTE 'ALTER TABLE documentos DROP CONSTRAINT ' || quote_ident(nombre);
    END LOOP;
END
$$
"""


def upgrade() -> None:
    if not _is_postgres():
        return

    op.execute("ALTER TABLE documentos ADD COLUMN IF NOT EXISTS blob_key TEXT")
    # Índice parcial: nace vacío (ninguna fila tiene todavía ``blob_key``) y lo
    # recorre la purga de retención, que busca justo las filas que SÍ la tienen.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_documentos_blob_key "
        "ON documentos (blob_key) WHERE blob_key IS NOT NULL"
    )

    op.execute(_DROP_CHECK_ANTERIOR)
    op.execute(_check_status(_STATUS_NUEVOS))

    op.execute(
        "ALTER TABLE documento_pages ADD COLUMN IF NOT EXISTS ocr BOOLEAN NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    """Retira las dos columnas y devuelve el ``CHECK`` a su vocabulario de v56.

    Las filas que hayan llegado a ``'unsupported'`` se devuelven a ``'error'``
    antes de restaurar la restricción: es donde caían antes de esta revisión y,
    si no, el ``ADD CONSTRAINT`` fallaría y el downgrade quedaría a medias. Se
    pierde la distinción entre «formato no soportado» y «falló la extracción»,
    que es exactamente lo que esta revisión vino a introducir.
    """
    if not _is_postgres():
        return

    op.execute("UPDATE documentos SET status = 'error' WHERE status = 'unsupported'")
    op.execute(_DROP_CHECK_ANTERIOR)
    op.execute(_check_status(_STATUS_ANTERIORES))

    op.execute("ALTER TABLE documento_pages DROP COLUMN IF EXISTS ocr")
    op.execute("DROP INDEX IF EXISTS idx_documentos_blob_key")
    op.execute("ALTER TABLE documentos DROP COLUMN IF EXISTS blob_key")
