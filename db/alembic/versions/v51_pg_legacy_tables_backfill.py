"""Migracion v51 -- backfill de tablas creadas solo por el sistema legacy (Postgres).

Esta migracion es DIALECT-GUARDED: solo hace algo en Postgres. En SQLite es
un no-op (esas tablas ya existen ahi, creadas por ``db/migrations.py``
v1-v32, el sistema homegrown que nunca corrio contra Postgres).

Contexto (auditoria F3b, 2026-07-05): el bootstrap de Postgres se hizo via
``alembic upgrade head``, que solo replay-ea las migraciones v14+. Las
migraciones v1-v13 y buena parte de v14-v32 fueron aplicadas historicamente
en SQLite/Turso por el sistema casero (``db/migrations.py``), que nunca se
porto a Postgres. Resultado: 17 tablas no existian en Postgres pese a que
``alembic current`` reportaba ``head``. Varias migraciones Alembic
posteriores (v26, v31) hacen ``op.add_column`` sobre estas tablas envuelto
en ``try/except: pass`` -- fallaron en silencio contra Postgres porque la
tabla base nunca se creo. Esta migracion cierra el gap creando las 17
tablas con el shape completo (incluidas esas columnas anadidas despues).

No incluye ``schema_version``: es la tabla de bookkeeping del sistema
legacy; Alembic ya tiene su propio ``alembic_version`` con el mismo rol.

Revision ID: v51_pg_legacy_tables_backfill
Revises: v50_pg_search_infra
Create Date: 2026-07-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "v51_pg_legacy_tables_backfill"
down_revision: str | None = "v50_pg_search_infra"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return  # no-op en SQLite -- estas tablas ya existen via db/migrations.py

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_key", sa.Text, nullable=False),
        sa.Column("session_hash", sa.Text, nullable=False, server_default=""),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("detail", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("prev_hash", sa.Text, nullable=True),  # v26
        sa.Column("this_hash", sa.Text, nullable=True),  # v26
    )
    op.create_index("idx_audit_log_user", "audit_log", ["user_key"])
    op.create_index("idx_audit_log_action", "audit_log", ["action"])

    op.create_table(
        "access_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("email", sa.Text, nullable=True),
        sa.Column("auth_method", sa.Text, nullable=False),
        sa.Column("logged_in_at", sa.Text, nullable=False),
    )
    op.create_index("idx_access_log_user", "access_log", ["user_id"])
    op.create_index("idx_access_log_time", "access_log", ["logged_in_at"])

    op.create_table(
        "api_key_tiers",
        sa.Column("tier", sa.Text, primary_key=True),
        sa.Column("daily_quota", sa.Integer, nullable=False, server_default="10000"),
        sa.Column("per_minute_limit", sa.Integer, nullable=False, server_default="120"),
        sa.Column("description", sa.Text, nullable=True),
    )
    op.execute(
        """
        INSERT INTO api_key_tiers (tier, daily_quota, per_minute_limit, description) VALUES
            ('free', 1000, 30, 'Tier gratuito - 1k req/dia, 30 req/min'),
            ('pro', 50000, 300, 'Tier pro - 50k req/dia, 300 req/min'),
            ('enterprise', 0, 0, 'Sin limites (0 = sin limite)')
        ON CONFLICT (tier) DO NOTHING
        """
    )

    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("idem_key", sa.Text, nullable=False),
        sa.Column("endpoint", sa.Text, nullable=False),
        sa.Column("response_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.UniqueConstraint("idem_key", "endpoint"),
    )
    op.create_index("idx_idem_key", "idempotency_keys", ["idem_key", "endpoint"])
    op.create_index("idx_idem_created", "idempotency_keys", ["created_at"])

    op.create_table(
        "kpi_snapshots",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("computed_at", sa.Text, nullable=False),
        sa.Column("metrica", sa.Text, nullable=False),
        sa.Column("dimension", sa.Text, nullable=False, server_default="global"),
        sa.Column("valor", sa.Float, nullable=True),
        sa.Column("valor_text", sa.Text, nullable=True),
    )
    op.create_index(
        "idx_kpi_snapshots_fecha", "kpi_snapshots", ["computed_at", "metrica", "dimension"]
    )

    op.create_table(
        "mat_clusters",
        sa.Column("id_externo", sa.Text, primary_key=True),
        sa.Column("cluster_id", sa.Integer, nullable=False),
        sa.Column("cluster_label", sa.Text, nullable=False, server_default=""),
        sa.Column("updated_at", sa.Text, nullable=False),
    )
    op.create_index("idx_mat_clusters_cluster_id", "mat_clusters", ["cluster_id"])

    op.create_table(
        "mat_top_empresas_ccaa",
        sa.Column("ccaa", sa.Text, nullable=False),
        sa.Column("rank", sa.Integer, nullable=False),
        sa.Column("nombre_canon", sa.Text, nullable=False),
        sa.Column("n_adj", sa.Integer, nullable=False, server_default="0"),
        sa.Column("importe_total", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("updated_at", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("ccaa", "rank"),
    )
    op.create_index("idx_mat_top_empresas_ccaa", "mat_top_empresas_ccaa", ["ccaa"])

    op.create_table(
        "notification_reads",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_key", sa.Text, nullable=False),
        sa.Column("notification_id", sa.Text, nullable=False),
        sa.Column("read_at", sa.Text, nullable=False),
        sa.UniqueConstraint("user_key", "notification_id"),
    )
    op.create_index("idx_notif_reads_user", "notification_reads", ["user_key"])

    op.create_table(
        "pending_digests",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_key", sa.Text, nullable=False),
        sa.Column("recipient_email", sa.Text, nullable=False),
        sa.Column("entry_id", sa.Integer, nullable=False),
        sa.Column("licitacion_id", sa.Text, nullable=False),
        sa.Column("frequency", sa.Text, nullable=False, server_default="daily"),
        sa.Column("matched_at", sa.Text, nullable=False),
        sa.Column("sent", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("entry_id", "licitacion_id"),
    )
    op.create_index(
        "idx_pending_digests_recipient", "pending_digests", ["recipient_email", "sent", "frequency"]
    )

    op.create_table(
        "rate_limits",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("key", sa.Text, nullable=False),
        sa.Column("ts", sa.Float, nullable=False),
    )
    op.create_index("idx_rate_limits_expires", "rate_limits", ["key", "ts"])

    op.create_table(
        "saved_filters",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_key", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("filters_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.UniqueConstraint("user_key", "name"),
    )
    op.create_index("idx_saved_filters_user", "saved_filters", ["user_key"])

    op.create_table(
        "watchlist_cpv",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_key", sa.Text, nullable=False),
        sa.Column("cpv_prefix", sa.Text, nullable=False),
        sa.Column("keyword", sa.Text, nullable=True),
        sa.Column("min_importe", sa.Float, nullable=True),
        sa.Column("ccaa", sa.Text, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.UniqueConstraint("user_key", "cpv_prefix", "keyword", "ccaa"),
    )
    op.create_index("idx_wl_user", "watchlist_cpv", ["user_key"])

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "webhook_id",
            sa.Integer,
            sa.ForeignKey("webhooks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("status_code", sa.Integer, nullable=False, server_default="0"),
        sa.Column("success", sa.Integer, nullable=False, server_default="0"),
        sa.Column("payload_size", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index("idx_wh_del_webhook", "webhook_deliveries", ["webhook_id"])
    op.create_index("idx_wh_del_created", "webhook_deliveries", ["created_at"])

    op.create_table(
        "extraction_runs",
        sa.Column("run_id", sa.Text, primary_key=True),
        sa.Column("started_at", sa.Text, nullable=False),
        sa.Column("ended_at", sa.Text, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("months_attempted", sa.Integer, server_default="0"),
        sa.Column("months_ok", sa.Integer, server_default="0"),
        sa.Column("months_failed", sa.Integer, server_default="0"),
        sa.Column("licitaciones_nuevas", sa.Integer, server_default="0"),
        sa.Column("licitaciones_actualizadas", sa.Integer, server_default="0"),
        sa.Column("adjudicaciones", sa.Integer, server_default="0"),
        sa.Column("errores_parseo", sa.Integer, server_default="0"),
        sa.Column("errores_descarga", sa.Integer, server_default="0"),
        sa.Column("notas", sa.Text, nullable=True),
    )
    op.create_index("idx_runs_started", "extraction_runs", ["started_at"])
    op.create_index("idx_runs_status", "extraction_runs", ["status"])

    op.create_table(
        "failed_extractions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Text, nullable=True),
        sa.Column("fuente", sa.Text, nullable=False),
        sa.Column("scope", sa.Text, nullable=True),
        sa.Column("error_type", sa.Text, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("payload_ref", sa.Text, nullable=True),
        sa.Column("retry_count", sa.Integer, server_default="0"),
        sa.Column("resolved_at", sa.Text, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("last_attempt_at", sa.Text, nullable=True),  # v31
        sa.Column("exhausted_at", sa.Text, nullable=True),  # v31
    )
    op.create_index("idx_fail_run", "failed_extractions", ["run_id"])
    op.create_index("idx_fail_unresolved", "failed_extractions", ["resolved_at"])
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_fail_exhausted "
        "ON failed_extractions(exhausted_at) WHERE exhausted_at IS NOT NULL"
    )

    op.create_table(
        "csp_violations",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("blocked_uri", sa.Text, nullable=True),
        sa.Column("violated_directive", sa.Text, nullable=True),
        sa.Column("document_uri", sa.Text, nullable=True),
        sa.Column("source_file", sa.Text, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index("idx_csp_created", "csp_violations", ["created_at"])


def downgrade() -> None:
    if not _is_postgres():
        return  # no-op en SQLite

    for table in (
        "csp_violations",
        "failed_extractions",
        "extraction_runs",
        "webhook_deliveries",
        "watchlist_cpv",
        "saved_filters",
        "rate_limits",
        "pending_digests",
        "notification_reads",
        "mat_top_empresas_ccaa",
        "mat_clusters",
        "kpi_snapshots",
        "idempotency_keys",
        "api_key_tiers",
        "access_log",
        "audit_log",
    ):
        op.drop_table(table)
