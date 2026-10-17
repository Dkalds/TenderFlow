"""v151: las columnas de fecha en texto con ``DEFAULT now()`` escriben ISO con ``T``.

Revision ID: v151_fechas_texto_iso
Revises: v150_mcp_oauth
Create Date: 2026-10-17

Qué falla hoy
-------------
Casi todas las fechas del esquema son ``text`` con ISO-8601 UTC
(``db.connection.now_utc_iso()``: ``2026-09-16T15:00:00.123456+00:00``), y el
código las compara y ordena como texto. Treinta y tres columnas, sin embargo,
nacieron con ``DEFAULT now()``: cuando un ``INSERT`` las omite, Postgres
convierte el ``timestamptz`` a texto con su formato de salida —espacio en vez
de ``T`` y offset corto, ``2026-09-16 15:00:00.123456+00``—. Comparado con un
corte ISO, ``' ' < 'T'`` hace que todo lo escrito el mismo día que el corte
quede «antes» aunque sea posterior. Es lo que dejaba fuera de «desde tu última
visita» los pliegos publicados el día de la visita (``documentos.created_at``,
cuyas filas escribe siempre el DEFAULT).

v67 ya corrigió lo mismo en siete columnas de organizaciones y oportunidades;
esta revisión cierra el resto.

Qué cambia
----------
1. El ``DEFAULT`` de las 33 columnas pasa a la misma expresión que v67
   (``_NOW_ISO_TEXT``), así que un ``INSERT`` que las omita escribe el formato
   de la aplicación.
2. Las filas ya escritas con el formato de ``now()::text`` se normalizan al de
   la aplicación, en UTC. El ``WHERE`` sólo toca las que casan con ese formato
   exacto (espacio, offset numérico), así que el ``::timestamptz`` no puede
   fallar con un valor raro y las filas ya en ISO no se reescriben.
   ``licitacion_tecnologia_score`` tiene un trigger diferido que recalcula
   ``licitaciones.ml_tecnologias`` por fila; la derivación no lee
   ``computed_at``, así que se desactiva mientras dura su ``UPDATE`` para no
   recalcular el corpus entero para obtener el mismo resultado.

No se pasa a ``timestamptz``: hay 132 columnas de fecha en ``text`` y el código
las lee como cadenas en cientos de sitios. Ese cambio de tipo es un proyecto
aparte (``docs/IMPROVEMENT_BACKLOG.md``); este arregla el formato, que es lo que
rompe las comparaciones hoy.

Coste: un recorrido completo de cada tabla. Las grandes son ``documentos`` y
``licitacion_tecnologia_score``; ninguna de las dos se escribe desde la API,
así que el bloqueo de filas sólo retrasa la ingesta que coincida.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from alembic import op

revision: str = "v151_fechas_texto_iso"
down_revision: str | None = "v150_mcp_oauth"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

# Mismo formato que db.connection.now_utc_iso() y que v67.
_NOW_ISO_TEXT = "to_char(NOW() AT TIME ZONE 'utc', 'YYYY-MM-DD\"T\"HH24:MI:SS.US') || '+00:00'"

# Lo que deja ``now()::text``: fecha, espacio, hora, fracción opcional y offset
# numérico con o sin minutos.
_FORMATO_NOW_TEXT = (
    r"'^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?[+-][0-9]{2}(:[0-9]{2})?$'"
)

# Triggers que se desactivan mientras se normaliza su tabla (ver docstring).
_TRIGGERS_A_PAUSAR: dict[str, str] = {
    "licitacion_tecnologia_score": "trg_lts_derivar_ml",
}

# (tabla, columna) ``text`` con ``DEFAULT now()`` en v150.
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

# Columnas sin ``DEFAULT now()`` que un ``NOW()::text`` escrito a mano dejó con
# el mismo formato (``services.dedupe.resolve_pending`` hasta esta revisión).
_SOLO_DATOS: list[tuple[str, str]] = [
    ("licitaciones_duplicados", "resolved_at"),
]


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _normalizar(tabla: str, columna: str) -> None:
    op.execute(
        f"UPDATE {tabla} SET {columna} = "
        f"to_char({columna}::timestamptz AT TIME ZONE 'utc', "
        "'YYYY-MM-DD\"T\"HH24:MI:SS.US') || '+00:00' "
        f"WHERE {columna} ~ {_FORMATO_NOW_TEXT}"
    )


def upgrade() -> None:
    if not _is_postgres():
        return

    for tabla, columna in _COLUMNAS:
        op.execute(f"ALTER TABLE {tabla} ALTER COLUMN {columna} SET DEFAULT ({_NOW_ISO_TEXT})")

    por_tabla: dict[str, list[str]] = {}
    for tabla, columna in [*_COLUMNAS, *_SOLO_DATOS]:
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

    # Como v67: volver a ``DEFAULT now()`` reintroduciría el formato que rompe
    # las comparaciones, y las filas normalizadas son ISO tan válido como el
    # que escribe la aplicación. No hay nada que deshacer con sentido.
    return
