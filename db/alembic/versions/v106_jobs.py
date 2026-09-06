"""v106: cola de trabajo persistente (`jobs`) — plan 2026-09 v2, S5.1.

Hasta hoy no había cola. El trabajo pesado que pide un usuario —extraer la
ficha de un pliego, maquetar un PDF de 50 000 filas, embeber los documentos de
un expediente— corría en los ``BackgroundTasks`` del propio proceso de la API
(``api/routes/licitaciones.py``), con un drenado de 30 s al apagar
(``api/app.py``). Un despliegue en mitad de una extracción la mataba y nadie se
enteraba: la fila de ``tender_fact_sheets`` se quedaba sin escribir y el
frontend sondeaba un estado que ya no avanzaba. Esta tabla es el sitio donde ese
trabajo sobrevive al proceso que lo pidió.

Reclamación
-----------
Un consumidor toma trabajo con ``SELECT … FOR UPDATE SKIP LOCKED`` (ver
``db/repositories/jobs.py``): el row lock de Postgres es lo que garantiza que
dos workers concurrentes no ejecuten el mismo job, sin un lock global que
serialice la cola entera. ``SKIP LOCKED`` es la pieza que lo hace escalable —
sin él, el segundo worker esperaría al primero en vez de saltar a la fila
siguiente.

Por qué NO retira `job_locks` (v34)
-----------------------------------
El plan dejaba la retirada condicionada a que la cola cubriera sus usos, y **no
los cubre**. ``job_locks`` es un *mutex con nombre y TTL* que
``scheduler/pipeline_runs.py::_run_periodic`` usa como **ventana temporal**: el
lock no se libera al terminar bien, de modo que las pasadas siguientes dentro
del periodo se saltan el paso (un digest "diario" no se envía seis veces al
día). Esta tabla modela *unidades de trabajo*, no ventanas de cadencia ni
exclusión por nombre; ``scheduler/healthcheck.py`` además publica los locks
vivos como diagnóstico. Emular una ventana de 24 h con filas de ``jobs``
exigiría inventar un vocabulario nuevo para expresar «no hacer nada y que eso
esté bien». ``job_locks`` se queda.

Coste
-----
Tabla nueva y vacía: los índices nacen sin filas. El parcial de la cola
(``estado = 'pending'``) es el que recorre cada ``claim``, y se mantiene
pequeño por construcción — un job terminado sale del índice.

DIALECT-GUARDED: solo actúa en Postgres.

Revision ID: v106_jobs
Revises: v105_users_oauth_provider
Create Date: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v106_jobs"
down_revision: str | Sequence[str] | None = "v105_users_oauth_provider"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("NOW()")

#: Vocabulario de ``jobs.estado``. ``pending`` cubre tanto «nunca se intentó»
#: como «falló y espera su reintento»: la diferencia la cuenta ``intentos`` y la
#: fecha la fija ``run_after``, así que un estado ``retrying`` aparte solo
#: añadiría una transición más que mantener sincronizada.
ESTADOS = ("pending", "running", "done", "failed")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _protect_table(table: str) -> None:
    """Cierra la Data API de Supabase y conserva el acceso del rol runtime.

    Mismo tratamiento que ``v89``/``v97``: ``payload_json`` puede llevar el
    identificador del expediente y el sujeto de presupuesto LLM de quien pidió
    el trabajo, así que la tabla no puede quedar legible por ``anon``.
    """
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

    estados_sql = ", ".join(f"'{e}'" for e in ESTADOS)
    op.create_table(
        "jobs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tipo", sa.Text, nullable=False),
        # TEXT y no JSONB: el payload se serializa y se deserializa entero en
        # Python (``shared/jobs.py``) y ninguna consulta indexa dentro de él.
        # JSONB pagaría el parseo en cada escritura para una capacidad que
        # nadie usa, y el nombre de la columna que fija el plan ya dice que su
        # contenido es JSON.
        sa.Column("payload_json", sa.Text, nullable=False, server_default="{}"),
        # Nullable a propósito: los pasos del cierre post-ingesta (S5.4) son
        # trabajo del sistema y no pertenecen a ninguna organización. Es
        # justamente lo que hace que ``GET /jobs/{id}`` no los sirva a nadie.
        sa.Column(
            "organization_id",
            sa.Integer,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("estado", sa.Text, nullable=False, server_default="pending"),
        sa.Column("intentos", sa.Integer, nullable=False, server_default="0"),
        # Cuándo puede reclamarse. Es la fecha que empuja el backoff tras un
        # fallo, y también permite encolar trabajo diferido sin otro mecanismo.
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("locked_by", sa.Text, nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resultado_json", sa.Text, nullable=True),
        sa.Column("error_detail", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.CheckConstraint(f"estado IN ({estados_sql})", name="ck_jobs_estado"),
    )

    # El índice que recorre cada ``claim``. Parcial sobre ``pending`` para que
    # su tamaño lo marque la cola pendiente y no el histórico: un job terminado
    # deja de ocupar entradas.
    op.create_index(
        "ix_jobs_pendientes",
        "jobs",
        ["run_after", "id"],
        postgresql_where=sa.text("estado = 'pending'"),
    )
    # La barrida de locks caducados (``reclamar_caducados``): también parcial,
    # porque solo mira los que están corriendo ahora mismo.
    op.create_index(
        "ix_jobs_corriendo",
        "jobs",
        ["locked_at"],
        postgresql_where=sa.text("estado = 'running'"),
    )
    # ``GET /jobs/{id}`` filtra por organización y el panel lista lo reciente
    # primero.
    op.create_index("ix_jobs_organizacion", "jobs", ["organization_id", sa.text("id DESC")])

    _protect_table("jobs")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.drop_index("ix_jobs_organizacion", table_name="jobs")
    op.drop_index("ix_jobs_corriendo", table_name="jobs")
    op.drop_index("ix_jobs_pendientes", table_name="jobs")
    op.drop_table("jobs")
