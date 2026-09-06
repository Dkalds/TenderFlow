"""v113: maestro de órganos de contratación (C1.2, ADR-032, D22).

Qué corrige
-----------
``licitaciones.organo_contratacion`` es **texto libre**, y la analítica agrupa y
cuenta por ese texto (``db/repositories/aggregates.py``,
``services/analytics/organos.py``). O sea que «Ayuntamiento de Madrid» y
«AYUNTAMIENTO DE MADRID» son dos órganos, con dos historiales, dos cuotas de
mercado y dos páginas.

El parser tampoco extraía el código **DIR3**, aunque CODICE lo transporta: el
identificador oficial del Inventario de Unidades Orgánicas, que resuelve la
identidad sin ambigüedad cuando está presente.

Por qué copia el patrón de ``empresas``
---------------------------------------
El mismo problema ya se resolvió una vez, en ``v35``: canónico + alias + cola de
revisión humana. Inventar un patrón distinto para el mismo problema obligaría a
mantener dos formas de pensar la resolución de identidad, y la segunda siempre
es la que se queda a medias.

Las tres tablas
---------------
``organos``
    La entidad. ``dir3`` es único cuando existe (índice parcial): dos filas con
    el mismo DIR3 son el mismo órgano, sin discusión. ``nombre_canonico`` es el
    respaldo para las fuentes que no publican DIR3 — regionales y expedientes
    antiguos.

``organo_aliases``
    Las grafías vistas, normalizadas con ``services.dedupe.normalize_organo``.
    Es lo que permite que el backfill resuelva sin volver a normalizar en cada
    consulta.

``organo_review_queue``
    Las fusiones dudosas. **No se deciden solas**: dos organismos distintos
    pueden tener nombres casi idénticos (los «Servicio de Salud» de dos
    comunidades), y fusionarlos junta dos historiales de contratación que no son
    el mismo. El error de fusionar de más no se detecta mirando la ficha.

Riesgo
------
Ninguno por sí sola: crea tablas vacías. El riesgo vive en ``v114``, que añade
la columna a la tabla núcleo y la rellena.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v113_organos_master"
down_revision: str | Sequence[str] | None = "v112_lic_semantica_del_importe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("CURRENT_TIMESTAMP")

TABLAS = ("organo_review_queue", "organo_aliases", "organos")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return

    inspector = sa.inspect(op.get_bind())
    existentes = set(inspector.get_table_names())

    if "organos" not in existentes:
        op.create_table(
            "organos",
            sa.Column("organo_id", sa.Integer, primary_key=True, autoincrement=True),
            # Código DIR3 del Inventario de Unidades Orgánicas. Nullable: las
            # fuentes regionales y los expedientes antiguos no lo publican.
            sa.Column("dir3", sa.Text, nullable=True),
            sa.Column("nombre_canonico", sa.Text, nullable=False),
            # Normalizado con `services.dedupe.normalize_organo`: es la clave de
            # resolución cuando no hay DIR3, y guardarlo evita normalizar en
            # cada consulta.
            sa.Column("nombre_normalizado", sa.Text, nullable=False),
            sa.Column("ccaa", sa.Text, nullable=True),
            # `ayuntamiento`, `universidad`, `sanidad`… Clasificación gruesa
            # para agregar por tipo de comprador.
            sa.Column("tipo", sa.Text, nullable=True),
            # Perfil del contratante: la URL oficial del órgano en PLACSP.
            sa.Column("url_perfil", sa.Text, nullable=True),
            sa.Column("created_at", sa.Text, nullable=False, server_default=_NOW),
            sa.Column("updated_at", sa.Text, nullable=False, server_default=_NOW),
        )
        # DIR3 es único **cuando existe**. Un índice único sin el `WHERE`
        # convertiría los NULL en colisiones en algunos motores y, sobre todo,
        # impediría tener dos órganos sin DIR3, que es la mayoría.
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_organos_dir3 "
            "ON organos(dir3) WHERE dir3 IS NOT NULL"
        )
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_organos_nombre_norm "
            "ON organos(nombre_normalizado)"
        )
        op.create_index("idx_organos_ccaa", "organos", ["ccaa"])

    if "organo_aliases" not in existentes:
        op.create_table(
            "organo_aliases",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column(
                "organo_id",
                sa.Integer,
                sa.ForeignKey("organos.organo_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("alias_normalizado", sa.Text, nullable=False),
            # La grafía tal cual llegó, para poder auditar de dónde salió el
            # alias sin reconstruirlo.
            sa.Column("alias_original", sa.Text, nullable=True),
            sa.Column("dir3_variante", sa.Text, nullable=True),
            sa.Column("fuente", sa.Text, nullable=False, server_default=""),
            sa.Column("confianza", sa.Float, nullable=False, server_default="1.0"),
            sa.Column("created_at", sa.Text, nullable=False, server_default=_NOW),
        )
        op.create_index("idx_organo_aliases_alias", "organo_aliases", ["alias_normalizado"])
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_organo_aliases_uniq "
            "ON organo_aliases(organo_id, alias_normalizado)"
        )

    if "organo_review_queue" not in existentes:
        op.create_table(
            "organo_review_queue",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("nombre_original", sa.Text, nullable=False),
            sa.Column("alias_normalizado", sa.Text, nullable=False),
            sa.Column("dir3", sa.Text, nullable=True),
            sa.Column(
                "candidato_organo_id",
                sa.Integer,
                sa.ForeignKey("organos.organo_id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("score", sa.Float, nullable=False, server_default="0"),
            sa.Column("status", sa.Text, nullable=False, server_default="pending"),
            sa.Column("created_at", sa.Text, nullable=False, server_default=_NOW),
            sa.Column("resolved_at", sa.Text, nullable=True),
            sa.Column("resolved_by", sa.Text, nullable=True),
        )
        op.execute(
            "ALTER TABLE organo_review_queue ADD CONSTRAINT ck_organo_review_status "
            "CHECK (status IN ('pending','accepted','rejected'))"
        )
        op.create_index("idx_organo_review_status", "organo_review_queue", ["status"])
        # Una misma grafía dudosa no puede encolarse dos veces mientras siga
        # pendiente: la cola es para que un humano decida, no para acumular
        # copias de la misma decisión.
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_organo_review_pending "
            "ON organo_review_queue(alias_normalizado, COALESCE(candidato_organo_id, 0)) "
            "WHERE status = 'pending'"
        )


def downgrade() -> None:
    if not _is_postgres():
        return
    for tabla in TABLAS:
        op.execute(f"DROP TABLE IF EXISTS {tabla} CASCADE")
