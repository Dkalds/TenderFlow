"""v120: ``asistente_feedback`` — el voto sobre una respuesta va a algún sitio (C5.4).

Qué corrige
-----------
El asistente no tiene forma de saber si acierta. El bucle de active learning que
sí existe (``/feedback``, ``feedback_queue``, ``model-info``) es el del
clasificador de tecnología: mide si un expediente es relevante, no si una
respuesta era buena. De la calidad de ``/ask`` no hay ni un número.

La forma
--------
=================== ========================================================
``pregunta_hash``   SHA-256 de la pregunta normalizada. Es la clave de
                    agregación: «esta pregunta falla siempre» es la señal
                    útil, y para eso no hace falta el texto.
``pregunta_texto``  El texto **sólo si la persona lo comparte** de forma
                    explícita (``compartir_pregunta``). ``NULL`` es el
                    caso normal.
``modo``            ``general`` | ``licitacion`` | ``resumen``.
``modelo``          Qué modelo respondió: sin esto, comparar dos modelos
                    exige adivinar cuál estaba activo cada día.
``voto``            ``up`` | ``down``.
``motivo``          Vocabulario **cerrado** (ver ``MOTIVOS``), no texto
                    libre.
``id_externo``      Expediente sobre el que se preguntó, si lo había.
``cached``          Si la respuesta venía de caché (C5.5). Un voto negativo
                    sobre una respuesta cacheada apunta a la entrada, no al
                    modelo.
=================== ========================================================

Por qué ``motivo`` es vocabulario cerrado
-----------------------------------------
Un campo de texto libre en un formulario de queja acaba conteniendo el nombre
del cliente, el importe que se va a ofertar y el teléfono de quien lo escribe.
La aceptación de C5.4 pide que la fila no lleve PII, y eso no se consigue
pidiéndolo en la interfaz: se consigue no teniendo dónde escribirla. Cinco
motivos cubren lo accionable —incorrecta, incompleta, sin fuentes, lenta, otro—
y el que quiera contar más tiene la conversación con soporte.

Por qué no hay columna de usuario
---------------------------------
Misma razón. Sin ella no se puede impedir que alguien vote dos veces la misma
respuesta; con ella, cada fila apunta a una persona y el conjunto pasa a ser un
registro de qué preguntó cada cual. El abuso lo acota el rate limiting del
endpoint; la privacidad no la acota nada si la columna existe.

Retención
---------
La hereda ``retention_cleanup`` por ``created_at``, como el resto de las tablas
de telemetría de producto.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v120_asistente_feedback"
down_revision: str | Sequence[str] | None = "v119_retirar_extracciones"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("CURRENT_TIMESTAMP")

VOTOS = ("up", "down")
MOTIVOS = ("incorrecta", "incompleta", "sin_fuentes", "lenta", "otro")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    if "asistente_feedback" in set(sa.inspect(op.get_bind()).get_table_names()):
        return

    op.create_table(
        "asistente_feedback",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("pregunta_hash", sa.Text, nullable=False),
        sa.Column("pregunta_texto", sa.Text, nullable=True),
        sa.Column("modo", sa.Text, nullable=False),
        sa.Column("modelo", sa.Text, nullable=False),
        sa.Column("voto", sa.Text, nullable=False),
        sa.Column("motivo", sa.Text, nullable=True),
        sa.Column("id_externo", sa.Text, nullable=True),
        sa.Column("cached", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.Text, nullable=False, server_default=_NOW),
    )
    votos = ", ".join(f"'{v}'" for v in VOTOS)
    op.execute(
        "ALTER TABLE asistente_feedback ADD CONSTRAINT ck_asistente_feedback_voto "
        f"CHECK (voto IN ({votos}))"
    )
    motivos = ", ".join(f"'{m}'" for m in MOTIVOS)
    op.execute(
        "ALTER TABLE asistente_feedback ADD CONSTRAINT ck_asistente_feedback_motivo "
        f"CHECK (motivo IS NULL OR motivo IN ({motivos}))"
    )
    # El panel agrupa por huella y ordena por recencia; la purga de retención
    # corta por `created_at`. Los dos índices sirven a esas dos consultas y no
    # a una tercera imaginaria.
    op.create_index("idx_asist_fb_hash", "asistente_feedback", ["pregunta_hash"])
    op.create_index("idx_asist_fb_created", "asistente_feedback", ["created_at"])


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP TABLE IF EXISTS asistente_feedback CASCADE")
