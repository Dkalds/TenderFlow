"""Migración v81 — admite el method 'llm_metadata' en la señal de tecnología.

``v71`` creó ``licitacion_tecnologia_pliego`` con
``CHECK (method IN ('keywords','llm'))``, los dos únicos carriles que existían
entonces: keywords sobre el texto del pliego, y las tecnologías que el LLM
extrae de la ficha del pliego.

El etiquetado batch sobre la metadata del anuncio
(``services/llm_tech_labeling.py``) añade un tercero. Necesita ``method``
propio y no puede reutilizar ``'llm'``: ``upsert_signals`` borra las filas del
mismo ``method`` que la corrida en curso ya no detecta, así que compartirlo
haría que cada carril machacase las señales del otro.

Sin esta migración el job no escribe **nada**: cada upsert muere con
``CheckViolation`` y la corrida entera se contabiliza como error.

Revision ID: v81_tech_signal_method_llm_metadata
Revises: v80_ml_feedback_source
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v81_tech_signal_method_llm_metadata"
down_revision: str | Sequence[str] | None = "v80_ml_feedback_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLA = "licitacion_tecnologia_pliego"
_CK = "ck_lic_tec_pliego_method"


def upgrade() -> None:
    # DROP + ADD y no ALTER: Postgres no permite redefinir un CHECK in situ.
    # El DROP es IF EXISTS para poder re-correr sobre una base a medio migrar.
    op.execute(f"ALTER TABLE {_TABLA} DROP CONSTRAINT IF EXISTS {_CK}")
    op.execute(
        f"ALTER TABLE {_TABLA} ADD CONSTRAINT {_CK} "
        "CHECK (method IN ('keywords','llm','llm_metadata'))"
    )


def downgrade() -> None:
    # Volver al conjunto estrecho exige que no queden filas del carril nuevo, o
    # el ADD CONSTRAINT fallaría al validar. Se borran primero: son señal
    # regenerable (basta con volver a correr el job), no dato de origen.
    op.execute(f"DELETE FROM {_TABLA} WHERE method = 'llm_metadata'")
    op.execute(f"ALTER TABLE {_TABLA} DROP CONSTRAINT IF EXISTS {_CK}")
    op.execute(f"ALTER TABLE {_TABLA} ADD CONSTRAINT {_CK} CHECK (method IN ('keywords','llm'))")
