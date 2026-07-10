"""Migracion baseline002 -- genesis de tablas núcleo para Postgres desde cero.

Esta migracion es DIALECT-GUARDED: solo hace algo en Postgres. En SQLite es
un no-op (estas tablas ya existen ahi via db/schema.py SCHEMA + db/migrations.py
apply_pending(), el camino de init_db()).

Contexto (auditoria v51/v53/v54/v55, confirmada por el job de CI
"schema-migrations-postgres" contra un Postgres real vacío): `alembic upgrade
head` desde cero rompe en v15_webhooks porque necesita `api_keys`, que
--como `licitaciones`, `adjudicaciones`, `users`, `ingestion_cursors`,
`licitaciones_history`, `extracciones`, `feature_flags`, `feature_store` y
`domain_events`-- NUNCA se crea en ninguna migracion de Alembic: o bien las
crea solo `db/schema.py` (SCHEMA, camino init_db() para SQLite) o solo el
sistema casero `db/migrations.py` (que nunca corre contra Postgres). v51 ya
rellenó las 16 tablas que faltaban de ese segundo grupo (mas api_key_tiers,
csp_violations); esta migracion cierra las que quedaban y que además son
*prerequisito* de migraciones tempranas (v15, v18, v22, v25, v28, v30, v33,
v35, v37...), por lo que tiene que insertarse ANTES de v14, no al final de
la cadena como v51/v53/v54/v55.

Insertada en la cadena entre `baseline001` y `v14_ml_feedback` (se cambió el
`down_revision` de v14 para apuntar aquí). Esto es seguro para producción:
Postgres de producción ya está en v55 (mucho más adelante), así que esta
migracion nunca se re-ejecuta ahi -- solo afecta un bootstrap nuevo desde
cero (como el Postgres efímero de CI).

Revision ID: baseline002_pg_core_genesis
Revises: baseline001
Create Date: 2026-07-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "baseline002_pg_core_genesis"
down_revision: str | None = "baseline001"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

_NOW = sa.text("NOW()")


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return  # no-op en SQLite -- estas tablas ya existen via db/schema.py + db/migrations.py

    insp = sa.inspect(op.get_bind())
    existing = set(insp.get_table_names(schema="public"))

    # ── licitaciones (tabla principal; db/schema.py SCHEMA + db/models.py) ──
    if "licitaciones" not in existing:
        op.create_table(
            "licitaciones",
            sa.Column("id_externo", sa.Text, primary_key=True),
            sa.Column("titulo", sa.Text, nullable=False),
            sa.Column("descripcion", sa.Text, nullable=True),
            sa.Column("organo_contratacion", sa.Text, nullable=True),
            sa.Column("importe", sa.Float, nullable=True),
            sa.Column("moneda", sa.Text, nullable=True, server_default="EUR"),
            sa.Column("cpv", sa.Text, nullable=True),
            sa.Column("tipo_contrato", sa.Text, nullable=True),
            sa.Column("estado", sa.Text, nullable=True),
            sa.Column("fecha_publicacion", sa.Text, nullable=True),
            sa.Column("fecha_limite", sa.Text, nullable=True),
            sa.Column("url", sa.Text, nullable=True),
            sa.Column("raw_keywords", sa.Text, nullable=True),
            sa.Column("provincia", sa.Text, nullable=True),
            sa.Column("ccaa", sa.Text, nullable=True),
            sa.Column("nuts_code", sa.Text, nullable=True),
            sa.Column("duracion_valor", sa.Float, nullable=True),
            sa.Column("duracion_unidad", sa.Text, nullable=True),
            sa.Column("fecha_inicio", sa.Text, nullable=True),
            sa.Column("fecha_fin", sa.Text, nullable=True),
            sa.Column("prorroga_descripcion", sa.Text, nullable=True),
            sa.Column("ml_proba", sa.Float, nullable=True),
            sa.Column("tecnologia", sa.Text, nullable=True),
            sa.Column("ml_tecnologias", sa.Text, nullable=True),
            sa.Column("ml_proba_max", sa.Float, nullable=True),
            sa.Column("ml_tech_principal", sa.Text, nullable=True),
            sa.Column("fecha_actualizacion_fuente", sa.Text, nullable=True),
            sa.Column("fuente", sa.Text, nullable=False, server_default="placsp"),
            sa.Column("fecha_extraccion", sa.Text, nullable=False),
        )
        op.create_index("idx_fecha_pub", "licitaciones", ["fecha_publicacion"])
        op.create_index("idx_organo", "licitaciones", ["organo_contratacion"])
        op.create_index("idx_estado", "licitaciones", ["estado"])
        op.create_index("idx_cpv", "licitaciones", ["cpv"])
        op.create_index("idx_ccaa", "licitaciones", ["ccaa"])
        op.create_index("idx_ml_tech_principal", "licitaciones", ["ml_tech_principal"])
        op.create_index("idx_lic_fuente", "licitaciones", ["fuente"])

    # ── adjudicaciones ────────────────────────────────────────────────────
    if "adjudicaciones" not in existing:
        op.create_table(
            "adjudicaciones",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column(
                "licitacion_id",
                sa.Text,
                sa.ForeignKey("licitaciones.id_externo", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("nif", sa.Text, nullable=True),
            sa.Column("nombre", sa.Text, nullable=False),
            sa.Column("provincia", sa.Text, nullable=True),
            sa.Column("ccaa", sa.Text, nullable=True),
            sa.Column("nuts_code", sa.Text, nullable=True),
            sa.Column("importe_adjudicado", sa.Float, nullable=True),
            sa.Column("importe_pagable", sa.Float, nullable=True),
            sa.Column("fecha_adjudicacion", sa.Text, nullable=True),
            sa.Column("es_pyme", sa.Integer, nullable=True),
            sa.Column("n_ofertas_recibidas", sa.Integer, nullable=True),
            sa.Column("oferta_minima", sa.Float, nullable=True),
            sa.Column("oferta_maxima", sa.Float, nullable=True),
            sa.Column("result_code", sa.Text, nullable=True),
            sa.Column("result_description", sa.Text, nullable=True),
            sa.Column("fecha_extraccion", sa.Text, nullable=False),
            sa.Column("empresa_id", sa.Integer, nullable=True),
            sa.UniqueConstraint("licitacion_id", "nif", "importe_adjudicado"),
        )
        op.create_index("idx_adj_lic", "adjudicaciones", ["licitacion_id"])
        op.create_index("idx_adj_nif", "adjudicaciones", ["nif"])
        op.create_index("idx_adj_ccaa", "adjudicaciones", ["ccaa"])
        op.create_index("idx_adj_fecha", "adjudicaciones", ["fecha_adjudicacion"])

    # ── users (db/migrations.py #8) ─────────────────────────────────────────
    if "users" not in existing:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("email", sa.Text, nullable=True, unique=True),
            sa.Column("oauth_provider", sa.Text, nullable=True),
            sa.Column("oauth_sub", sa.Text, nullable=True),
            sa.Column("display_name", sa.Text, nullable=True),
            sa.Column("created_at", sa.Text, nullable=False, server_default=_NOW),
            sa.UniqueConstraint("oauth_provider", "oauth_sub"),
        )
        op.create_index("idx_users_email", "users", ["email"])
        op.create_index("idx_users_oauth", "users", ["oauth_provider", "oauth_sub"])

    # ── api_keys (db/migrations.py #19; prerequisito de v15/v25/v28) ────────
    if "api_keys" not in existing:
        op.create_table(
            "api_keys",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("key_hash", sa.Text, nullable=False, unique=True),
            sa.Column("name", sa.Text, nullable=False),
            sa.Column("created_at", sa.Text, nullable=False, server_default=_NOW),
            sa.Column("last_used", sa.Text, nullable=True),
            sa.Column("is_active", sa.Integer, nullable=False, server_default="1"),
            sa.Column("expires_at", sa.Text, nullable=True),
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash) WHERE is_active = 1"
        )

    # ── ingestion_cursors (db/migrations.py #5) ─────────────────────────────
    if "ingestion_cursors" not in existing:
        op.create_table(
            "ingestion_cursors",
            sa.Column("source", sa.Text, primary_key=True),
            sa.Column("last_seen_updated", sa.Text, nullable=True),
            sa.Column("last_entry_id", sa.Text, nullable=True),
            sa.Column("etag", sa.Text, nullable=True),
            sa.Column("last_modified", sa.Text, nullable=True),
            sa.Column("updated_at", sa.Text, nullable=False),
        )

    # ── licitaciones_history (db/migrations.py #5; prerequisito de v18) ────
    if "licitaciones_history" not in existing:
        op.create_table(
            "licitaciones_history",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column(
                "id_externo", sa.Text, sa.ForeignKey("licitaciones.id_externo"), nullable=False
            ),
            sa.Column("captured_at", sa.Text, nullable=False),
            sa.Column("source", sa.Text, nullable=True),
            sa.Column("snapshot_json", sa.Text, nullable=False),
            sa.Column("changed_fields", sa.Text, nullable=False),
        )
        op.create_index("idx_hist_externo", "licitaciones_history", ["id_externo", "captured_at"])

    # ── extracciones (db/schema.py SCHEMA) ──────────────────────────────────
    if "extracciones" not in existing:
        op.create_table(
            "extracciones",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("fecha", sa.Text, nullable=False),
            sa.Column("fuente", sa.Text, nullable=False),
            sa.Column("nuevas", sa.Integer, server_default="0"),
            sa.Column("actualizadas", sa.Integer, server_default="0"),
            sa.Column("total_revisadas", sa.Integer, server_default="0"),
            sa.Column("notas", sa.Text, nullable=True),
        )
        op.create_index("idx_extr_fecha", "extracciones", ["fecha"])

    # ── feature_flags (db/schema.py SCHEMA) ─────────────────────────────────
    if "feature_flags" not in existing:
        op.create_table(
            "feature_flags",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("name", sa.Text, nullable=False, unique=True),
            sa.Column("enabled", sa.Integer, nullable=False, server_default="0"),
            sa.Column("rollout_pct", sa.Integer, nullable=False, server_default="100"),
            sa.Column("user_emails", sa.Text, nullable=False, server_default=""),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("updated_at", sa.Text, nullable=False),
        )

    # ── feature_store (db/schema.py SCHEMA) ─────────────────────────────────
    if "feature_store" not in existing:
        op.create_table(
            "feature_store",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("entity_type", sa.Text, nullable=False),
            sa.Column("entity_id", sa.Text, nullable=False),
            sa.Column("feature_name", sa.Text, nullable=False),
            sa.Column("value_json", sa.Text, nullable=False),
            sa.Column("version", sa.Text, nullable=False, server_default="v1"),
            sa.Column("computed_at", sa.Text, nullable=False),
            sa.UniqueConstraint("entity_type", "entity_id", "feature_name", "version"),
        )
        op.create_index("idx_feature_store_entity", "feature_store", ["entity_type", "entity_id"])
        op.create_index("idx_feature_store_name", "feature_store", ["entity_type", "feature_name"])

    # ── domain_events (db/schema.py SCHEMA) ─────────────────────────────────
    if "domain_events" not in existing:
        op.create_table(
            "domain_events",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("event_type", sa.Text, nullable=False),
            sa.Column("aggregate_id", sa.Text, nullable=False),
            sa.Column("aggregate_type", sa.Text, nullable=False),
            sa.Column("payload_json", sa.Text, nullable=False, server_default="{}"),
            sa.Column("actor_id", sa.Integer, nullable=True),
            sa.Column("created_at", sa.Text, nullable=False),
        )
        op.create_index(
            "idx_domain_events_aggregate", "domain_events", ["aggregate_type", "aggregate_id"]
        )
        op.create_index("idx_domain_events_type", "domain_events", ["event_type"])
        op.create_index("idx_domain_events_created", "domain_events", ["created_at"])


def downgrade() -> None:
    # No reversible con sentido: no distingue tablas creadas por esta
    # migracion de tablas que ya existian por otra vía. No-op deliberado --
    # mismo criterio que v51/v54/v55.
    pass
