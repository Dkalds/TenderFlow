"""v161: ``documentos.status`` admite ``'sin_texto'`` (PDF escaneado sin OCR).

Revision ID: v161_documentos_sin_texto
Revises: v160_fechas_ts_indices
Create Date: 2026-10-25

Qué falla hoy
-------------
Un PDF escaneado —sin capa de texto— que el OCR no puede leer (``ocrmypdf`` no
está en el proceso, o falla) acaba en ``status = 'error'`` con el mismo estado
que una descarga fallida o un PDF roto. Consecuencias medidas en el ítem S8 del
backlog: 54 filas «sin texto extraíble» en ``error`` el 2026-10-23, que

* la ficha bajo demanda explicaba como «descargas fallidas, los enlaces de
  PLACSP caducan; suelen volver tras la ingesta diaria» —falso: el enlace
  abre, lo que falta es OCR, y la ingesta diaria no lo arregla—, y
* ``/analytics/quality`` y el informe nocturno contaban como fallos, no como
  cobertura de OCR pendiente.

Qué hace
--------
1. Amplía el ``CHECK`` de ``documentos.status`` con ``'sin_texto'``. Terminal,
   como ``unsupported``: el fetcher lo escribe desde
   ``scraper/document_fetcher.py::PdfSinTextoError``.
2. Pasa a ``'sin_texto'`` las filas ``error`` cuyo ``error_detail`` empieza por
   el mensaje con el que el fetcher marcaba ese caso
   (``"PDF sin texto extraíble"``). Ningún otro ``error`` lleva ese prefijo: los
   de descarga empiezan por ``"descarga fallida"`` y los de PDF roto por
   ``"PDF corrupto"``/``"PDF cifrado"``/``"PDF excede"``. ~54 filas: una sola
   sentencia, sin lotes.

El ``CHECK`` se tira y se recrea con el mismo bloque que ``v103`` (por
contenido y no por nombre, ver allí por qué); ``strpos`` y no ``LIKE '%…%'``
por el problema del ``%`` que ``v88`` dejó documentado.

Idempotente: el ``DROP`` recorre las restricciones que existan, el ``ADD``
parte de cero y el ``UPDATE`` no encuentra nada en la segunda pasada.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v161_documentos_sin_texto"
down_revision: str | Sequence[str] | None = "v160_fechas_ts_indices"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS_NUEVOS = ("pending", "downloaded", "extracted", "error", "unsupported", "sin_texto")
_STATUS_ANTERIORES = ("pending", "downloaded", "extracted", "error", "unsupported")

_CONSTRAINT = "documentos_status_check"

#: Prefijo del ``error_detail`` con el que el fetcher marcaba un PDF sin texto
#: antes de esta revisión (``_MSG_PDF_SIN_TEXTO``, sin la coletilla).
_PREFIJO_SIN_TEXTO = "PDF sin texto extraíble"

#: Mismo bloque que ``v103``: tira toda restricción CHECK de ``documentos`` cuya
#: definición mencione ``'downloaded'``, que solo puede ser la de ``status``.
_DROP_CHECK_STATUS = """
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


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _check_status(valores: tuple[str, ...]) -> str:
    literales = ", ".join(f"'{v}'" for v in valores)
    return f"ALTER TABLE documentos ADD CONSTRAINT {_CONSTRAINT} CHECK (status IN ({literales}))"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute(_DROP_CHECK_STATUS)
    op.execute(_check_status(_STATUS_NUEVOS))
    op.execute(
        "UPDATE documentos SET status = 'sin_texto' "
        f"WHERE status = 'error' AND starts_with(error_detail, '{_PREFIJO_SIN_TEXTO}')"
    )


def downgrade() -> None:
    """Devuelve las filas ``sin_texto`` a ``error`` y el ``CHECK`` a ``v103``.

    Es donde caían antes de esta revisión; sin el ``UPDATE`` previo el
    ``ADD CONSTRAINT`` fallaría y el downgrade quedaría a medias. Su
    ``error_detail`` ya lleva el mensaje, así que no se pierde la causa.
    """
    if not _is_postgres():
        return
    op.execute("UPDATE documentos SET status = 'error' WHERE status = 'sin_texto'")
    op.execute(_DROP_CHECK_STATUS)
    op.execute(_check_status(_STATUS_ANTERIORES))
