"""v90: una solicitud pendiente por email en ``solicitudes_acceso``.

Revision ID: v90_solicitudes_acceso_dedupe
Revises: v89_solicitudes_acceso
Create Date: 2026-08-26

La cola de v89 no tenía ninguna restricción de unicidad y ``crear_solicitud``
era un ``INSERT`` pelado, así que cada pulsación del botón creaba una fila. Los
tres caminos que lo provocan no son hipotéticos: un doble clic en un formulario
que tarda en responder, un reintento después del 303 de error, y sobre todo el
reintento tras agotar el rate limit —cinco por minuto y por IP—, que es
exactamente el momento en que alguien vuelve a darle. El resultado lo paga la
persona que revisa la cola a mano: tres filas idénticas que hay que descartar
una por una.

**Índice único parcial y no restricción de tabla**, por dos motivos. El primero
es que la unicidad solo debe valer mientras la solicitud está ``pendiente``: si
se atendió o se descartó hace seis meses, volver a pedir acceso es legítimo y
tiene que poder entrar. El segundo es que un ``UNIQUE`` sobre ``email`` a secas
convertiría el histórico en un obstáculo para el presente.

``lower(email)`` porque la parte de dominio del correo no distingue mayúsculas
y en la práctica la parte local tampoco: ``Ana@Empresa.com`` y
``ana@empresa.com`` son la misma persona pidiendo lo mismo dos veces, y el
objetivo aquí es la cola de una persona, no el RFC 5321.

**Limpia antes de indexar.** Un índice único sobre datos que ya tienen
duplicados falla al crearse, así que primero se dejan sólo las filas más
recientes de cada email pendiente. Las que sobran se marcan ``descartada`` en
vez de borrarse: son solicitudes reales de personas reales y su rastro —con la
marca de consentimiento— no se tira sin necesidad.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v90_solicitudes_acceso_dedupe"
down_revision: str | Sequence[str] | None = "v89_solicitudes_acceso"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDICE = "ux_solicitudes_acceso_pendiente_email"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return

    # Conserva la más reciente de cada email pendiente; el resto pasa a
    # descartada. `ctid` desempata si dos comparten `created_at` al milisegundo.
    op.execute(
        "UPDATE solicitudes_acceso SET estado = 'descartada' WHERE id IN ("
        "  SELECT id FROM ("
        "    SELECT id, row_number() OVER ("
        "      PARTITION BY lower(email) ORDER BY created_at DESC, ctid DESC"
        "    ) AS rn"
        "    FROM solicitudes_acceso WHERE estado = 'pendiente'"
        "  ) ranked WHERE rn > 1"
        ")"
    )

    op.execute(
        f"CREATE UNIQUE INDEX {_INDICE} ON solicitudes_acceso (lower(email)) "
        "WHERE estado = 'pendiente'"
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute(f"DROP INDEX IF EXISTS {_INDICE}")
