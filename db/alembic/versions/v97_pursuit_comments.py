"""v97: hilo de comentarios de cada oportunidad (``pursuit_comments``).

Revision ID: v97_pursuit_comments
Revises: v96_password_reset_tokens
Create Date: 2026-09-02

El chat del equipo sobre un expediente. Tabla propia y no entradas del ledger
``pursuit_events``: el ledger es append-only por trigger (v61) y un comentario
tiene que poder borrarse; además, mezclar conversación con auditoría convierte
el historial de decisiones en ruido.

Timestamps como TEXT ISO por coherencia con la familia de pursuits (v61/v83;
ADR-016/021): el repositorio escribe ``now_utc_iso()``. ``author_user_id`` va
``ON DELETE SET NULL`` y la anonimización RGPD lo pone a NULL sin borrar el
texto, que es trabajo del equipo y no dato personal del autor.

``idempotency_key`` + índice único parcial: el mismo patrón que
``pursuit_events``, para que un reintento del cliente no duplique el mensaje.
El CHECK de longitud duplica ``shared.dto.PURSUIT_COMMENT_MAX_CHARS`` (4000).

``organization_id`` va desnormalizado (el pursuit ya lo tiene) por el mismo
motivo que en ``pursuit_events``: toda query del hilo se acota por
organización sin pasar por ``pursuits``.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v97_pursuit_comments"
down_revision: str | Sequence[str] | None = "v96_password_reset_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _protect_table(table: str) -> None:
    """Cierra Data API y conserva acceso del rol runtime de la aplicación."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN "
        f"REVOKE ALL ON TABLE {table} FROM anon; "
        "END IF; "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN "
        f"REVOKE ALL ON TABLE {table} FROM authenticated; "
        "END IF; "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tenderflow_app') THEN "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO tenderflow_app; "
        f"GRANT USAGE, SELECT ON SEQUENCE {table}_id_seq TO tenderflow_app; "
        f"CREATE POLICY tenderflow_app_full_access ON {table} "
        "FOR ALL TO tenderflow_app USING (true) WITH CHECK (true); "
        "END IF; END $$"
    )


def upgrade() -> None:
    if not _is_postgres():
        return
    op.create_table(
        "pursuit_comments",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "pursuit_id",
            sa.Integer,
            sa.ForeignKey("pursuits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            sa.Integer,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("idempotency_key", sa.Text, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint(
            "char_length(body) BETWEEN 1 AND 4000",
            name="ck_pursuit_comments_body_length",
        ),
    )
    # El hilo se lee por pursuit y se pagina por id (desde el más reciente).
    op.create_index(
        "idx_pursuit_comments_pursuit_id",
        "pursuit_comments",
        ["pursuit_id", "id"],
    )
    # Portabilidad y anonimización RGPD buscan por autor.
    op.create_index(
        "idx_pursuit_comments_author",
        "pursuit_comments",
        ["author_user_id"],
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_pursuit_comments_idempotency "
        "ON pursuit_comments(pursuit_id, idempotency_key) "
        "WHERE idempotency_key IS NOT NULL"
    )
    _protect_table("pursuit_comments")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP INDEX IF EXISTS uq_pursuit_comments_idempotency")
    op.drop_index("idx_pursuit_comments_author", table_name="pursuit_comments")
    op.drop_index("idx_pursuit_comments_pursuit_id", table_name="pursuit_comments")
    op.drop_table("pursuit_comments")
