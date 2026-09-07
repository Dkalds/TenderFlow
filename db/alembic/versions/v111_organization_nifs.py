"""v111: identidad fiscal de la organización (NIF/CIF).

Plan de arquitectura 2026-09 v2, S2.1 (decisión D11: tablas propias, no
``organizations.settings_json``).

Hasta aquí una organización era un nombre y una lista de familias
tecnológicas. Por eso ``services/pursuit_awards.py`` avisa de una adjudicación
pero no dice si es suya, y su docstring lo escribe con todas las letras: «el
sistema no conoce el NIF de la organización». Esta tabla es ese dato.

Diseño, y por qué:

* **Varias filas por organización.** Un grupo se presenta con la matriz, con
  filiales y en UTE, y las tres formas aparecen en ``adjudicaciones.nif``. Con
  un solo NIF en ``organizations`` el cierre por NIF fallaría justo en los
  casos que importan. ``principal`` marca con cuál se presenta por defecto.
* **``nif`` se guarda ya normalizado** (``services.normalization.normalize_nif``:
  sin espacios, guiones ni puntos, en mayúsculas) y el ``CHECK`` lo impone.
  Guardarlo como lo teclea el usuario obligaría a normalizar la columna en
  cada consulta —``WHERE normaliza(nif) = %s``— y eso no usa índice.
* **Único parcial de ``principal``**: como mucho una fila principal por
  organización. Dos «principales» no es un estado que nadie sepa resolver.
* **Índice por ``nif``** además del único compuesto: la pregunta inversa
  («¿de quién es este NIF?») la hace el cruce con el maestro de empresas y
  con los adjudicatarios, y el compuesto empieza por ``organization_id``.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v111_organization_nifs"
down_revision: str | Sequence[str] | None = "v110_pursuits_lote_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _protect_table(table: str) -> None:
    """RLS + grants mínimos, el mismo patrón que v96 y v104."""
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
        "organization_nifs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "organization_id",
            sa.Integer,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("nif", sa.Text, nullable=False),
        sa.Column("razon_social", sa.Text, nullable=True),
        sa.Column("principal", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_by_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        # La forma normalizada es la única que entra: mayúsculas, dígitos y
        # nada más. Si alguien escribe SQL a mano y se salta `normalize_nif`,
        # falla aquí en vez de crear una fila que ningún cruce encontrará.
        sa.CheckConstraint(
            "nif ~ '^[A-Z0-9]{4,32}$'",
            name="ck_organization_nifs_normalizado",
        ),
        sa.UniqueConstraint("organization_id", "nif", name="uq_organization_nifs_org_nif"),
    )
    # Índice por EXPRESIÓN parcial: SQL crudo, como en v104, para que se lea
    # exactamente lo que se crea.
    op.execute(
        "CREATE UNIQUE INDEX uq_organization_nifs_principal "
        "ON organization_nifs (organization_id) WHERE principal"
    )
    op.execute("CREATE INDEX ix_organization_nifs_nif ON organization_nifs (nif)")
    _protect_table("organization_nifs")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP INDEX IF EXISTS ix_organization_nifs_nif")
    op.execute("DROP INDEX IF EXISTS uq_organization_nifs_principal")
    op.drop_table("organization_nifs")
