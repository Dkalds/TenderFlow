"""v152: las fechas en texto sin zona horaria se leen como UTC y se escriben en ISO.

Revision ID: v152_fechas_sin_zona_utc
Revises: v151_fechas_texto_iso
Create Date: 2026-10-17

Qué queda tras v151
-------------------
v151 normalizó el formato de ``now()::text`` (espacio y offset,
``2026-09-16 15:00:00+00``) en 34 columnas. A propósito dejó fuera un segundo
formato, más antiguo y **sin zona** (``2026-05-21 15:02:22``): el que escribía
el ``datetime('now')`` de SQLite antes de la migración a Postgres. Sin offset,
convertirlo exigía decidir en qué zona estaba, y v151 no lo adivinaba.

Medido en producción tras aplicar v151 (2026-10-17), en las columnas que el
MCP de solo lectura deja ver: 53.903 filas en
``licitacion_tecnologia_score.computed_at`` (de mayo a julio de 2026) y 134 en
``contrato_eventos.created_at``. Comparadas como texto con un corte ISO
provocan el mismo fallo que v151 arregló: ``' ' < 'T'`` las deja «antes» del
corte aunque sean del mismo día.

Qué cambia
----------
Las filas de las mismas 34 columnas de v151 que casan **exactamente** con
``AAAA-MM-DD HH:MM:SS`` (fracción opcional, sin offset) se reescriben en el
formato de la aplicación, **interpretadas como UTC**: es la zona de
``datetime('now')`` en SQLite. El ``::timestamp`` (sin zona) conserva la hora
de pared tal cual, que en UTC es el instante. Lo que ya es ISO, lo que lleva
offset y lo que no es una fecha no casa con el patrón y no se toca.

Como en v151, el trigger diferido de ``licitacion_tecnologia_score`` se pausa
solo durante su ``UPDATE``: la derivación no lee ``computed_at``.

Sin cambios de esquema ni de ``DEFAULT``: eso ya lo hizo v151.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from alembic import op

revision: str = "v152_fechas_sin_zona_utc"
down_revision: str | None = "v151_fechas_texto_iso"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

# Lo que dejaba ``datetime('now')`` de SQLite: fecha, espacio, hora y fracción
# opcional, sin offset.
_FORMATO_SIN_ZONA = r"'^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?$'"

# Triggers que se desactivan mientras se normaliza su tabla (ver docstring).
_TRIGGERS_A_PAUSAR: dict[str, str] = {
    "licitacion_tecnologia_score": "trg_lts_derivar_ml",
}

# Las mismas columnas que v151 (``_COLUMNAS`` y ``_SOLO_DATOS``). Se copian y no
# se importan: una migración no puede depender del código de otra.
_COLUMNAS: list[tuple[str, str]] = [
    ("api_keys", "created_at"),
    ("contrato_eventos", "created_at"),
    ("documentos", "created_at"),
    ("documentos", "updated_at"),
    ("empresa_aliases", "created_at"),
    ("empresa_review_queue", "created_at"),
    ("empresas", "created_at"),
    ("empresas", "updated_at"),
    ("go_no_go_scores", "created_at"),
    ("go_no_go_scores", "updated_at"),
    ("go_no_go_weights", "updated_at"),
    ("grupos_empresariales", "created_at"),
    ("licitacion_tecnologia_score", "computed_at"),
    ("licitaciones_duplicados", "detectado_en"),
    ("licitaciones_duplicados", "resolved_at"),
    ("ops_events", "ts"),
    ("predicciones_baja", "computed_at"),
    ("predicciones_retencion", "computed_at"),
    ("pursuit_attachments", "created_at"),
    ("pursuit_comment_mentions", "created_at"),
    ("pursuit_comments", "created_at"),
    ("pursuit_tasks", "created_at"),
    ("pursuit_tasks", "updated_at"),
    ("pursuits", "identified_at"),
    ("source_ingestion_health", "updated_at"),
    ("tecnologias_keywords", "created_at"),
    ("tecnologias_keywords", "updated_at"),
    ("tender_fact_sheets", "updated_at"),
    ("user_notifications", "created_at"),
    ("user_profiles", "updated_at"),
    ("users", "created_at"),
    ("watchlist_empresas", "created_at"),
    ("watchlist_items", "created_at"),
    ("watchlist_rules", "created_at"),
]


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _normalizar(tabla: str, columna: str) -> None:
    op.execute(
        f"UPDATE {tabla} SET {columna} = "
        f"to_char({columna}::timestamp, 'YYYY-MM-DD\"T\"HH24:MI:SS.US') || '+00:00' "
        f"WHERE {columna} ~ {_FORMATO_SIN_ZONA}"
    )


def upgrade() -> None:
    if not _is_postgres():
        return

    por_tabla: dict[str, list[str]] = {}
    for tabla, columna in _COLUMNAS:
        por_tabla.setdefault(tabla, []).append(columna)

    for tabla, columnas in por_tabla.items():
        trigger = _TRIGGERS_A_PAUSAR.get(tabla)
        if trigger:
            op.execute(f"ALTER TABLE {tabla} DISABLE TRIGGER {trigger}")
        for columna in columnas:
            _normalizar(tabla, columna)
        if trigger:
            op.execute(f"ALTER TABLE {tabla} ENABLE TRIGGER {trigger}")


def downgrade() -> None:
    if not _is_postgres():
        return

    # Como v151: las filas normalizadas son ISO tan válido como el que escribe
    # la aplicación, y volver al formato sin zona reintroduciría el fallo.
    return
