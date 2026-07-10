"""Migracion v55 -- backfill de tablas v27-v49 con DDL SQLite embebida (Postgres).

Esta migracion es DIALECT-GUARDED: solo hace algo en Postgres. En SQLite es
un no-op (esas tablas ya se crearon correctamente via las migraciones
originales, que sí funcionan contra SQLite).

Contexto (continuacion de la auditoria que motivo v51/v53/v54): a partir de
v27, buena parte de las migraciones de este repo dejaron de usar
``op.create_table()``/``sa.Column`` (portable entre dialectos, como v14
``ml_feedback``) y empezaron a escribir DDL cruda con ``op.execute()``
copiada literalmente de ``db/schema.py`` (pensada solo para SQLite):
``INTEGER PRIMARY KEY AUTOINCREMENT`` (no es sintaxis valida en Postgres) y
``DEFAULT (datetime('now'))`` / ``datetime('now','utc')`` (Postgres no tiene
la funcion ``datetime()``). v40 y v35 ademas hacen introspeccion contra
``sqlite_master`` en modo online, que tampoco existe en Postgres.

No hay forma de verificar contra la Postgres real de producción si estas
tablas quedaron creadas por un bootstrap externo (bulk-copy/pgloader desde
Turso, que sí traduce el DDL) o si faltan igual que le pasó a ``watchlist_cpv``
(v53) y a las secuencias (v54). Por eso esta migracion es puramente aditiva
e idempotente (``CREATE TABLE IF NOT EXISTS`` vía SQLAlchemy + ``ADD COLUMN
IF NOT EXISTS``): si la tabla/columna ya existe con la forma correcta, es un
no-op; si falta, la crea. Cubre las tablas introducidas por v30, v35, v36,
v38 (+ CHECK ampliado por v40), v39, v40, v41, v42, v43 (+ columna email de
v47), v45, v46, v48, v49 -- y la columna ``adjudicaciones.empresa_id`` de v35.

No se toca ``ml_feedback`` (v14) ni sus columnas de v44: ya usan
``op.create_table``/``ALTER TABLE ... ADD COLUMN`` estandar, portable en
ambos dialectos sin cambios.

Revision ID: v55_pg_v27_v49_tables_backfill
Revises: v54_resync_pg_sequences
Create Date: 2026-07-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "v55_pg_v27_v49_tables_backfill"
down_revision: str | None = "v54_resync_pg_sequences"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

_NOW = sa.text("NOW()")


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def _add_column_if_not_exists(table: str, column_ddl: str) -> None:
    op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column_ddl}")


def upgrade() -> None:
    if not _is_postgres():
        return  # no-op en SQLite -- estas tablas ya existen via sus migraciones originales

    insp = sa.inspect(op.get_bind())
    existing = set(insp.get_table_names(schema="public"))

    # ── v30: licitacion_tecnologia_score ──────────────────────────────────
    if "licitacion_tecnologia_score" not in existing:
        op.create_table(
            "licitacion_tecnologia_score",
            sa.Column(
                "licitacion_id",
                sa.Text,
                sa.ForeignKey("licitaciones.id_externo", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("tecnologia", sa.Text, primary_key=True),
            sa.Column("probabilidad", sa.Float, nullable=False),
            sa.Column("threshold_aplicado", sa.Float, nullable=False),
            sa.Column("computed_at", sa.Text, nullable=False, server_default=_NOW),
        )
        op.create_index(
            "idx_lts_tecnologia",
            "licitacion_tecnologia_score",
            ["tecnologia", sa.text("probabilidad DESC")],
        )
        op.create_index("idx_lts_lic", "licitacion_tecnologia_score", ["licitacion_id"])

    # ── v35: maestro de empresas ───────────────────────────────────────────
    if "grupos_empresariales" not in existing:
        op.create_table(
            "grupos_empresariales",
            sa.Column("grupo_id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("nombre", sa.Text, nullable=False, unique=True),
            sa.Column("created_at", sa.Text, nullable=False, server_default=_NOW),
        )
    if "empresas" not in existing:
        op.create_table(
            "empresas",
            sa.Column("empresa_id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("nif_canonico", sa.Text, nullable=True),
            sa.Column("nombre_canonico", sa.Text, nullable=False),
            sa.Column("es_ute", sa.Integer, nullable=False, server_default="0"),
            sa.Column("es_pyme", sa.Integer, nullable=True),
            sa.Column("grupo_id", sa.Integer, sa.ForeignKey("grupos_empresariales.grupo_id")),
            sa.Column("created_at", sa.Text, nullable=False, server_default=_NOW),
            sa.Column("updated_at", sa.Text, nullable=False, server_default=_NOW),
        )
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_empresas_nif ON empresas(nif_canonico) "
            "WHERE nif_canonico IS NOT NULL"
        )
        op.create_index("idx_empresas_grupo", "empresas", ["grupo_id"])
    if "empresa_aliases" not in existing:
        op.create_table(
            "empresa_aliases",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column(
                "empresa_id",
                sa.Integer,
                sa.ForeignKey("empresas.empresa_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("alias_normalizado", sa.Text, nullable=False),
            sa.Column("nif_variante", sa.Text, nullable=True),
            sa.Column("fuente", sa.Text, nullable=False, server_default=""),
            sa.Column("confianza", sa.Float, nullable=False, server_default="1.0"),
            sa.Column("created_at", sa.Text, nullable=False, server_default=_NOW),
        )
        op.create_index("idx_empresa_aliases_alias", "empresa_aliases", ["alias_normalizado"])
        op.create_index("idx_empresa_aliases_nif", "empresa_aliases", ["nif_variante"])
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_empresa_aliases_uniq ON empresa_aliases"
            "(empresa_id, alias_normalizado, COALESCE(nif_variante, ''))"
        )
    if "ute_miembros" not in existing:
        op.create_table(
            "ute_miembros",
            sa.Column(
                "ute_empresa_id",
                sa.Integer,
                sa.ForeignKey("empresas.empresa_id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "miembro_empresa_id",
                sa.Integer,
                sa.ForeignKey("empresas.empresa_id", ondelete="CASCADE"),
                primary_key=True,
            ),
        )
    if "empresa_review_queue" not in existing:
        op.create_table(
            "empresa_review_queue",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("nombre_original", sa.Text, nullable=False),
            sa.Column("alias_normalizado", sa.Text, nullable=False),
            sa.Column("nif", sa.Text, nullable=True),
            sa.Column(
                "candidato_empresa_id",
                sa.Integer,
                sa.ForeignKey("empresas.empresa_id", ondelete="CASCADE"),
            ),
            sa.Column("score", sa.Float, nullable=False),
            sa.Column(
                "status",
                sa.Text,
                nullable=False,
                server_default="pending",
            ),
            sa.CheckConstraint("status IN ('pending','accepted','rejected')"),
            sa.Column("created_at", sa.Text, nullable=False, server_default=_NOW),
            sa.Column("resolved_at", sa.Text, nullable=True),
            sa.Column("resolved_by", sa.Text, nullable=True),
        )
        op.create_index("idx_empresa_review_status", "empresa_review_queue", ["status"])
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_empresa_review_pending ON "
            "empresa_review_queue(alias_normalizado, COALESCE(nif, ''), candidato_empresa_id) "
            "WHERE status = 'pending'"
        )
    if "adjudicaciones" in existing:
        cols = {c["name"] for c in insp.get_columns("adjudicaciones")}
        if "empresa_id" not in cols:
            _add_column_if_not_exists(
                "adjudicaciones", "empresa_id INTEGER REFERENCES empresas(empresa_id)"
            )
        op.execute("CREATE INDEX IF NOT EXISTS idx_adj_empresa ON adjudicaciones(empresa_id)")

    # ── v36: watchlist_empresas ────────────────────────────────────────────
    if "watchlist_empresas" not in existing:
        op.create_table(
            "watchlist_empresas",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("user_key", sa.Text, nullable=False),
            sa.Column(
                "empresa_id",
                sa.Integer,
                sa.ForeignKey("empresas.empresa_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("email", sa.Text, nullable=True),
            sa.Column("frequency", sa.Text, nullable=False, server_default="daily"),
            sa.Column("created_at", sa.Text, nullable=False, server_default=_NOW),
            sa.Column("last_notified_at", sa.Text, nullable=True),
            sa.UniqueConstraint("user_key", "empresa_id"),
        )
        op.create_index("idx_wl_emp_user", "watchlist_empresas", ["user_key"])

    # ── v38 + v40: contrato_eventos (CHECK ya incluye 'recurso') ───────────
    if "contrato_eventos" not in existing:
        op.create_table(
            "contrato_eventos",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column(
                "licitacion_id",
                sa.Text,
                sa.ForeignKey("licitaciones.id_externo", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("tipo", sa.Text, nullable=False),
            sa.CheckConstraint(
                "tipo IN ('adjudicacion','formalizacion','modificacion','prorroga',"
                "'anulacion','cambio_estado','recurso')"
            ),
            sa.Column("fecha", sa.Text, nullable=False),
            sa.Column("campo", sa.Text, nullable=True),
            sa.Column("valor_antes", sa.Text, nullable=True),
            sa.Column("valor_despues", sa.Text, nullable=True),
            sa.Column("importe_delta", sa.Float, nullable=True),
            sa.Column("detalle", sa.Text, nullable=True),
            sa.Column("history_id", sa.Integer, nullable=True),
            sa.Column("created_at", sa.Text, nullable=False, server_default=_NOW),
        )
        op.create_index("idx_eventos_lic", "contrato_eventos", ["licitacion_id", "fecha"])
        op.create_index("idx_eventos_tipo", "contrato_eventos", ["tipo", "fecha"])
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_eventos_dedupe ON contrato_eventos"
            "(history_id, tipo, COALESCE(campo, '')) WHERE history_id IS NOT NULL"
        )

    # ── v39: licitaciones_duplicados ───────────────────────────────────────
    if "licitaciones_duplicados" not in existing:
        op.create_table(
            "licitaciones_duplicados",
            sa.Column(
                "licitacion_id",
                sa.Text,
                sa.ForeignKey("licitaciones.id_externo", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "canonical_id",
                sa.Text,
                sa.ForeignKey("licitaciones.id_externo", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("clave_match", sa.Text, nullable=True),
            sa.Column("confianza", sa.Float, nullable=False, server_default="1.0"),
            sa.Column("status", sa.Text, nullable=False, server_default="confirmed"),
            sa.CheckConstraint("status IN ('confirmed','pending','rejected')"),
            sa.Column("detectado_en", sa.Text, nullable=False, server_default=_NOW),
            sa.Column("resolved_at", sa.Text, nullable=True),
            sa.Column("resolved_by", sa.Text, nullable=True),
        )
        op.create_index("idx_lic_dup_canonical", "licitaciones_duplicados", ["canonical_id"])
        op.create_index("idx_lic_dup_status", "licitaciones_duplicados", ["status"])

    # ── v40: resoluciones_recurso ───────────────────────────────────────────
    if "resoluciones_recurso" not in existing:
        op.create_table(
            "resoluciones_recurso",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("tribunal", sa.Text, nullable=False, server_default="tacrc"),
            sa.Column("numero_resolucion", sa.Text, nullable=False),
            sa.Column("numero_recurso", sa.Text, nullable=True),
            sa.Column("fecha", sa.Text, nullable=True),
            sa.Column("expediente", sa.Text, nullable=True),
            sa.Column("organo", sa.Text, nullable=True),
            sa.Column("sentido", sa.Text, nullable=True),
            sa.CheckConstraint(
                "sentido IS NULL OR sentido IN "
                "('estimado','desestimado','inadmitido','desistimiento')"
            ),
            sa.Column("url_pdf", sa.Text, nullable=True),
            sa.Column("resumen", sa.Text, nullable=True),
            sa.Column(
                "licitacion_id", sa.Text, sa.ForeignKey("licitaciones.id_externo"), nullable=True
            ),
            sa.Column("fecha_extraccion", sa.Text, nullable=False),
            sa.UniqueConstraint("tribunal", "numero_resolucion"),
        )
        op.create_index("idx_resoluciones_lic", "resoluciones_recurso", ["licitacion_id"])
        op.create_index("idx_resoluciones_fecha", "resoluciones_recurso", ["fecha"])
        op.create_index("idx_resoluciones_sentido", "resoluciones_recurso", ["sentido", "fecha"])

    # ── v41: predicciones_baja ───────────────────────────────────────────────
    if "predicciones_baja" not in existing:
        op.create_table(
            "predicciones_baja",
            sa.Column(
                "licitacion_id",
                sa.Text,
                sa.ForeignKey("licitaciones.id_externo", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("p10", sa.Float, nullable=False),
            sa.Column("p50", sa.Float, nullable=False),
            sa.Column("p90", sa.Float, nullable=False),
            sa.Column("model_version", sa.Integer, nullable=True),
            sa.Column("computed_at", sa.Text, nullable=False, server_default=_NOW),
        )
        op.create_index("idx_pred_baja_computed", "predicciones_baja", ["computed_at"])

    # ── v42: predicciones_retencion ──────────────────────────────────────────
    if "predicciones_retencion" not in existing:
        op.create_table(
            "predicciones_retencion",
            sa.Column(
                "licitacion_id",
                sa.Text,
                sa.ForeignKey("licitaciones.id_externo", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("empresa_id", sa.Integer, sa.ForeignKey("empresas.empresa_id")),
            sa.Column("prob_retencion", sa.Float, nullable=False),
            sa.Column("riesgo_cambio", sa.Float, nullable=False),
            sa.Column("model_version", sa.Integer, nullable=True),
            sa.Column("computed_at", sa.Text, nullable=False, server_default=_NOW),
        )
        op.create_index(
            "idx_pred_ret_riesgo", "predicciones_retencion", [sa.text("riesgo_cambio DESC")]
        )

    # ── v43 (+ v47 email) : watchlist_rules ──────────────────────────────────
    if "watchlist_rules" not in existing:
        op.create_table(
            "watchlist_rules",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("user_key", sa.Text, nullable=False),
            sa.Column("user_id", sa.Integer, nullable=True),
            sa.Column("nombre", sa.Text, nullable=True),
            sa.Column("keyword", sa.Text, nullable=True),
            sa.Column("cpv", sa.Text, nullable=True),
            sa.Column("min_importe", sa.Float, nullable=True),
            sa.Column("ccaa", sa.Text, nullable=True),
            sa.Column("frequency", sa.Text, nullable=False, server_default="daily"),
            sa.Column("active", sa.Integer, nullable=False, server_default="1"),
            sa.Column("created_at", sa.Text, nullable=False, server_default=_NOW),
            sa.Column("last_notified_at", sa.Text, nullable=True),
            sa.Column("email", sa.Text, nullable=True),  # v47
        )
        op.create_index("idx_wl_rules_user", "watchlist_rules", ["user_key"])
        op.create_index("idx_wl_rules_active", "watchlist_rules", ["active", "frequency"])
    else:
        cols = {c["name"] for c in insp.get_columns("watchlist_rules")}
        if "email" not in cols:
            _add_column_if_not_exists("watchlist_rules", "email TEXT")

    # ── v45: watchlist_items ─────────────────────────────────────────────────
    if "watchlist_items" not in existing:
        op.create_table(
            "watchlist_items",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("user_key", sa.Text, nullable=False),
            sa.Column("user_id", sa.Integer, nullable=True),
            sa.Column("id_externo", sa.Text, nullable=False),
            sa.Column("created_at", sa.Text, nullable=False, server_default=_NOW),
            sa.UniqueConstraint("user_key", "id_externo"),
        )
        op.create_index("idx_wl_items_user", "watchlist_items", ["user_key"])

    # ── v46: ops_events ──────────────────────────────────────────────────────
    if "ops_events" not in existing:
        op.create_table(
            "ops_events",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("ts", sa.Text, nullable=False, server_default=_NOW),
            sa.Column("event_type", sa.Text, nullable=False),
            sa.Column("value", sa.Float, nullable=True),
            sa.Column("plane", sa.Text, nullable=True),
            sa.Column("pid", sa.Integer, nullable=True),
            sa.Column("detail", sa.Text, nullable=True),
        )
        op.create_index("idx_ops_events_type_ts", "ops_events", ["event_type", "ts"])

    # ── v48: user_notifications ─────────────────────────────────────────────
    if "user_notifications" not in existing:
        op.create_table(
            "user_notifications",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("user_key", sa.Text, nullable=False),
            sa.Column("created_at", sa.Text, nullable=False, server_default=_NOW),
            sa.Column("type", sa.Text, nullable=False),
            sa.Column("title", sa.Text, nullable=True),
            sa.Column("body", sa.Text, nullable=True),
            sa.Column("licitacion_id", sa.Text, nullable=True),
            sa.Column("rule_id", sa.Integer, nullable=True),
            sa.Column("read_at", sa.Text, nullable=True),
            sa.UniqueConstraint("user_key", "licitacion_id", "type"),
        )
        op.create_index("idx_user_notif_user_read", "user_notifications", ["user_key", "read_at"])

    # ── v49: user_profiles ───────────────────────────────────────────────────
    if "user_profiles" not in existing:
        op.create_table(
            "user_profiles",
            sa.Column("user_key", sa.Text, primary_key=True),
            sa.Column("weights_json", sa.Text, nullable=True),
            sa.Column("afinidad_keywords_json", sa.Text, nullable=True),
            sa.Column("cpvs_json", sa.Text, nullable=True),
            sa.Column("ccaa_json", sa.Text, nullable=True),
            sa.Column("importe_min", sa.Float, nullable=True),
            sa.Column("importe_max", sa.Float, nullable=True),
            sa.Column("updated_at", sa.Text, nullable=False, server_default=_NOW),
        )


def downgrade() -> None:
    # No reversible con sentido: no distingue tablas creadas por esta
    # migracion de tablas que ya existian (bootstrap externo). No-op
    # deliberado -- mismo criterio que v54.
    pass
