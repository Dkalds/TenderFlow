"""v121: ``asistente_feedback`` — el voto deja de morir en telemetría (C5.4).

Qué corrige
-----------
El chat tiene pulgares desde hace meses y el voto es **solo un evento de
telemetría** (``registrarEvento("asistente_feedback", …)``): no llega a ninguna
tabla, no hay ruta que lo reciba y no hay forma de responder «¿el asistente
responde peor este mes que el pasado?». Se le pide al usuario que evalúe y su
evaluación se tira.

Sin persistirlo tampoco existe el insumo del active learning que el propio
producto ya usa para el clasificador: las preguntas que salieron mal son
exactamente las que hay que revisar.

Qué se guarda, y qué no
-----------------------
La fila lleva **la forma del turno, no su contenido**: hash de la pregunta,
modo, modelo, voto y un motivo opcional de una lista cerrada. La pregunta en
claro solo se guarda con ``texto_opt_in`` explícito del usuario, y va en una
columna aparte para que una consulta que no la pida no la lea por accidente.

El hash es la clave que permite agrupar («esta pregunta falla siempre») sin
guardar la pregunta. Lleva sal de servidor (``SIGNING_KEY``): sin sal, un hash
de un texto corto y adivinable —«¿cuál es el plazo?»— se revierte con un
diccionario en minutos, y entonces la columna «sin PII» tendría el contenido
que dice no tener.

``licitacion_id`` sí se guarda: es un identificador público del anuncio oficial,
no dato del usuario, y sin él una respuesta mal valorada no se puede reproducir.

Por qué `user_id` con `ON DELETE SET NULL`
------------------------------------------
El voto sigue siendo información de calidad del sistema cuando quien lo emitió
borra su cuenta; lo que no puede es seguir apuntando a esa persona. Mismo
criterio que ADR-030 §D aplica al trabajo compartido de una organización.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v121_asistente_feedback"
down_revision: str | Sequence[str] | None = "v120_documento_chunks_version_pagina"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("CURRENT_TIMESTAMP")


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
        # HMAC de la pregunta normalizada. Agrupa sin guardar el texto.
        sa.Column("pregunta_hash", sa.Text, nullable=False),
        # `pregunta` | `resumen` | `ficha`.
        sa.Column("modo", sa.Text, nullable=False),
        sa.Column("modelo", sa.Text, nullable=True),
        sa.Column("licitacion_id", sa.Text, nullable=True),
        # `si` | `no`.
        sa.Column("voto", sa.Text, nullable=False),
        # Lista cerrada (`incompleta`, `incorrecta`, `sin_fuentes`, `otro`).
        sa.Column("motivo", sa.Text, nullable=True),
        # Solo con opt-in explícito. Columna aparte a propósito.
        sa.Column("pregunta_texto", sa.Text, nullable=True),
        sa.Column("user_id", sa.Integer, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False, server_default=_NOW),
    )
    op.execute(
        "ALTER TABLE asistente_feedback ADD CONSTRAINT ck_asistente_feedback_voto "
        "CHECK (voto IN ('si', 'no'))"
    )
    op.execute(
        "ALTER TABLE asistente_feedback ADD CONSTRAINT fk_asistente_feedback_user "
        "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL"
    )
    # El panel agrupa por pregunta y ordena por recencia; son las dos únicas
    # consultas que hace, y sin índices ambas son seq scan sobre una tabla que
    # crece con cada respuesta valorada.
    op.create_index("idx_asistente_feedback_hash", "asistente_feedback", ["pregunta_hash"])
    op.create_index("idx_asistente_feedback_created", "asistente_feedback", ["created_at"])


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP TABLE IF EXISTS asistente_feedback CASCADE")
