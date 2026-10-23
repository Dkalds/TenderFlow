"""v154: las filas de ``galicia_rss`` con importe y sin base declarada pasan a ``desconocido``.

Revision ID: v154_importe_tipo_galicia_desconocido
Revises: v153_rekey_pscp_id_externo
Create Date: 2026-10-23

Qué falla hoy
-------------
El control ``importe/filas_nuevas_sin_tipo`` de la auditoría de verdad
(``db.domain_truth_audit.importe_sin_base_declarada``, umbral **cero** desde
``v113``) salta a diario por cuatro filas de ``galicia_rss``, escritas entre el
10 y el 17/09/2026 por un camino de escritura que no poblaba ``importe_tipo``.
Ese camino ya está cerrado: los RSS autonómicos declaran la base desde
``scraper.connectors.regional_rss._tipo_de_importe`` (#419), y cuando la prosa
del feed no la dice escriben ``desconocido``, nunca ``NULL``. Medido en
producción el 2026-10-23: son las únicas filas de todo ``licitaciones`` con
importe y sin tipo.

Qué hace
--------
Las marca ``desconocido``, que es lo más que se puede afirmar sin volver a leer
el feed (el RSS solo trae publicaciones recientes y estas ya no salen) y lo que
ADR-032 ya hace con un ``NULL`` al leer. No se afirma ``sin_iva`` ni ``con_iva``:
adivinar la base metería el IVA en las bajas, el error que ADR-032 cerró.

Acotada a ``galicia_rss`` a propósito: si mañana otro camino de escritura vuelve
a dejar ``NULL``, la auditoría tiene que seguir viéndolo, no esta revisión
taparlo. Idempotente: una segunda pasada no encuentra filas.

Downgrade: no-op deliberado. Volver a ``NULL`` solo reabriría la alerta, y no
hay forma de distinguir estas cuatro filas de otras ``galicia_rss`` que el
conector marcó ``desconocido`` por su cuenta.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from alembic import op

revision: str = "v154_importe_tipo_galicia_desconocido"
down_revision: str | None = "v153_rekey_pscp_id_externo"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

#: Mismo predicado que ``importe_sin_base_declarada`` (sin la ventana de fechas:
#: en producción no hay otras) más la fuente.
_MARCAR = (
    "UPDATE licitaciones SET importe_tipo = 'desconocido' "
    "WHERE fuente = 'galicia_rss' AND importe IS NOT NULL AND importe_tipo IS NULL"
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute(_MARCAR)


def downgrade() -> None:
    """No-op: ver el docstring del módulo."""
