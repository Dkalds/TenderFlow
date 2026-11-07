"""v173: las consultas recientes del Investigador se guardan por usuario.

Qué corrige
-----------
El historial de consultas del Investigador vivía en ``localStorage``
(``web/.../investigador/_hooks/use-ajustes.ts``): no viajaba a otro navegador
ni a otro dispositivo, y es estado de usuario, que según
``docs/frontend-data-invariants.md`` vive en servidor con el navegador como
caché. ``saved_filters`` no sirve: guarda instantáneas del ámbito que otras
pantallas restauran, no frases.

Forma
-----
Una fila por usuario y frase. La clave primaria ``(user_id, consulta)`` es lo
que deduplica: repetir una consulta solo actualiza ``usada_en``, y quien
escribe recorta a las diez más recientes en la misma transacción
(``db/repositories/consultas_recientes.py``). La PK también sirve la única
lectura —las de un usuario, ordenadas por fecha—, que son diez filas: no hace
falta otro índice.

Dato personal, no corporativo: no lleva ``organization_id`` ni RLS, y
``ON DELETE CASCADE`` porque sin la persona la frase no tiene valor para nadie
(``follows`` usa ``SET NULL`` porque su fila sí es del espacio de trabajo).
El borrado y la exportación RGPD la cubren (``services/gdpr.py``).

La frase es la estrategia comercial de quien la escribe: no se registra en
logs ni en telemetría, igual que en ``/search/semantic``.

DIALECT-GUARDED: solo actúa en Postgres.

Revision ID: v173_consultas_recientes
Revises: v172_empresas_busqueda_trgm
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v173_consultas_recientes"
down_revision: str | Sequence[str] | None = "v172_empresas_busqueda_trgm"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: El mismo techo que la consulta de ``/search/semantic`` (``SemanticSearchRequest.q``).
_MAX_CONSULTA = 500


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        "CREATE TABLE IF NOT EXISTS consultas_recientes ("
        " user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
        f" consulta TEXT NOT NULL CHECK (char_length(consulta) BETWEEN 1 AND {_MAX_CONSULTA}),"
        " usada_en TIMESTAMPTZ NOT NULL DEFAULT now(),"
        " PRIMARY KEY (user_id, consulta)"
        ")"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP TABLE IF EXISTS consultas_recientes")
