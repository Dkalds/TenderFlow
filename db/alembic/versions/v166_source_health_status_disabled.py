"""v166: ``source_ingestion_health.status`` admite ``'disabled'``.

Revision ID: v166_source_health_status_disabled
Revises: v165_user_id_fase3_tanda3
Create Date: 2026-10-29

``v62`` creó la tabla con ``CHECK (status IN ('running','success','partial',
'failed'))``. Después, los conectores que arrancan sin su variable de entorno
obligatoria (PSCP, TACRC, las sindicaciones agregadas y menores de PLACSP)
pasaron a declararse apagados con ``record_source_disabled``, que escribe
``status='disabled'``, y ``scheduler/healthcheck.py`` cuenta esa fila como
``apagada`` en vez de ``sin_registro``. Ninguna revisión amplió el ``CHECK``:
cada pasada de ``scrape-daily`` dejaba un ``CheckViolation`` en el log y el
panel de salud enseñaba las dos sindicaciones como ``sin_registro`` (#578).

DROP + ADD porque Postgres no redefine un ``CHECK`` in situ. La tabla tiene una
fila por fuente, así que la validación del ``ADD`` es instantánea.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v166_source_health_status_disabled"
down_revision: str | Sequence[str] | None = "v165_user_id_fase3_tanda3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLA = "source_ingestion_health"
_CK = "ck_source_ingestion_health_status"
ESTADOS = ("running", "success", "partial", "failed", "disabled")
_ESTADOS_V62 = ESTADOS[:-1]


def _check(estados: Sequence[str]) -> str:
    lista = ",".join(f"'{estado}'" for estado in estados)
    return f"ALTER TABLE {_TABLA} ADD CONSTRAINT {_CK} CHECK (status IN ({lista}))"


def upgrade() -> None:
    op.execute(f"ALTER TABLE {_TABLA} DROP CONSTRAINT IF EXISTS {_CK}")
    op.execute(_check(ESTADOS))


def downgrade() -> None:
    # Una fila ``disabled`` solo dice que la fuente no está configurada: el
    # conector la vuelve a escribir en su siguiente pasada. Se borra para que
    # el CHECK estrecho valide.
    op.execute(f"DELETE FROM {_TABLA} WHERE status = 'disabled'")
    op.execute(f"ALTER TABLE {_TABLA} DROP CONSTRAINT IF EXISTS {_CK}")
    op.execute(_check(_ESTADOS_V62))
