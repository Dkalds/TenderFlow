"""v145: una cuenta objetivo agrupa uno o varios órganos (``cuenta_organos``).

Revision ID: v145_cuenta_organos
Revises: v143_lic_busqueda_plegada_trgm
Create Date: 2026-09-25

Qué falta hoy
-------------
v105 hizo de la cuenta un órgano: una fila de ``cuentas_objetivo`` por órgano
seguido, con el órgano como identidad. Pero un cliente no es un órgano de
contratación. El Ayuntamiento de Madrid no publica nada con ese nombre: en
producción (2026-09-25) contrata a través de seis órganos —«Área de Gobierno
de Economía, Innovación y Hacienda del Ayuntamiento de Madrid», «Organismo
Autónomo Informática del Ayuntamiento de Madrid»…—, y ninguno se llama
«Ayuntamiento de Madrid». Una cuenta con ese nombre no casaba con ninguna
licitación y no avisaba de nada; seis cuentas, una por órgano, partían al
cliente en seis filas sin nada que las uniera.

Qué cambia
----------
- ``cuentas_objetivo`` pasa a ser **el cliente**. Gana ``nombre`` —lo que el
  equipo llama a la cuenta, editable— y ``nombre_norm``, su clave de unicidad
  dentro de la organización: dos cuentas «Ayuntamiento de Getafe» en el mismo
  equipo serían la misma escrita dos veces.
- ``cuenta_organos`` guarda sus órganos, uno por fila, con el nombre tal como
  lo publica la fuente y el plegado (``organo_norm``) con el que casan los
  avisos de publicación y de vencimiento, el cruce de las alertas de
  competidores y la ficha. Un órgano pertenece a **una sola** cuenta de cada
  organización (``UNIQUE (organization_id, organo_norm)``): si pudiera estar
  en dos, cada publicación suya saldría dos veces en la campana de cada
  miembro.

Expand, no contract
-------------------
``organo_nombre``, ``organo_norm`` y ``organo_id`` de ``cuentas_objetivo`` se
quedan, ahora nullables, con su unicidad. El código anterior a esta revisión
sigue funcionando contra el esquema nuevo mientras dura el despliegue: inserta
con esas columnas y su ``ON CONFLICT`` sigue encontrando la unicidad que
nombra. El código nuevo no las lee para casar —lee ``cuenta_organos``— y deja
``NULL`` en las cuentas que crea, que no choca con esa unicidad. Retirarlas es
otra revisión, cuando ningún despliegue las use.

``nombre`` y ``nombre_norm`` nacen nullables por el mismo motivo: el código
anterior no los escribe. El nuevo siempre.

Backfill
--------
Cada fila existente es una cuenta de un órgano: ``nombre`` es su
``organo_nombre`` y su órgano pasa a ``cuenta_organos``. En producción había
0 filas el 2026-09-25; el backfill es para los demás entornos. La clave del
nombre pliega igual que ``db.repositories.cuentas.clave_de_nombre`` (tildes,
mayúsculas y espacios repetidos); si dos cuentas de una organización
colisionaran al plegar, la segunda conserva la suya con su id como sufijo, en
vez de hacer fallar la migración.

RLS
---
``cuenta_organos`` lleva ``organization_id`` y nace protegida, como ``follows``
en v130 y ``organization_report_schedules`` en v132: cada migración protege
las tablas que crea.

El índice por expresión sobre ``licitaciones`` con el que la ficha y el
resumen buscan las licitaciones de un órgano va aparte, en v146:
``CREATE INDEX CONCURRENTLY`` no puede correr dentro de la transacción de este
backfill.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v145_cuenta_organos"
down_revision: str | Sequence[str] | None = "v143_lic_busqueda_plegada_trgm"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Tablas corporativas que crea esta revisión (ver cabecera §RLS).
TABLAS_CORPORATIVAS: tuple[str, ...] = ("cuenta_organos",)

_PREDICADO_TENANT = (
    "NULLIF(current_setting('app.organization_id', true), '') IS NULL "
    "OR organization_id IS NULL "
    "OR organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer"
)

#: Gemela congelada de ``clave_de_nombre``: el plegado de ``fold_expr``
#: (``db/sql_fragments.py``) sobre el nombre con los espacios colapsados.
#: Congelada y no importada: ninguna migración de este linaje importa de
#: ``db/``.
_CLAVE_NOMBRE_SQL = (
    "lower(translate(btrim(regexp_replace(organo_nombre, '\\s+', ' ', 'g')), "
    "'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ', "
    "'aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC'))"
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _tablas() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if not _is_postgres() or "cuentas_objetivo" not in _tablas():
        return

    # ── cuentas_objetivo: la cuenta es el cliente ────────────────────────────
    op.execute("ALTER TABLE cuentas_objetivo ADD COLUMN IF NOT EXISTS nombre TEXT")
    op.execute("ALTER TABLE cuentas_objetivo ADD COLUMN IF NOT EXISTS nombre_norm TEXT")
    op.execute("ALTER TABLE cuentas_objetivo ALTER COLUMN organo_nombre DROP NOT NULL")
    op.execute("ALTER TABLE cuentas_objetivo ALTER COLUMN organo_norm DROP NOT NULL")
    op.execute(
        "UPDATE cuentas_objetivo SET nombre = btrim(organo_nombre) "
        "WHERE nombre IS NULL AND organo_nombre IS NOT NULL"
    )
    # La primera de cada clave se la queda; una colisión conserva la suya con
    # el id como sufijo (ver la cabecera §Backfill).
    op.execute(
        "UPDATE cuentas_objetivo c SET nombre_norm = d.clave "
        "FROM ("
        "  SELECT id, CASE WHEN row_number() OVER ("
        "      PARTITION BY organization_id, base ORDER BY id) = 1 "
        "    THEN base ELSE base || ' #' || id END AS clave "
        f"  FROM (SELECT id, organization_id, {_CLAVE_NOMBRE_SQL} AS base "
        "        FROM cuentas_objetivo WHERE organo_nombre IS NOT NULL) b"
        ") d "
        "WHERE d.id = c.id AND c.nombre_norm IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_cuentas_objetivo_org_nombre "
        "ON cuentas_objetivo (organization_id, nombre_norm)"
    )

    # ── cuenta_organos: los órganos de cada cuenta ──────────────────────────
    op.execute(
        "CREATE TABLE IF NOT EXISTS cuenta_organos ("
        " id SERIAL PRIMARY KEY,"
        # Denormalizado desde la cuenta: la unicidad por organización y la RLS
        # lo necesitan en la fila, sin un JOIN.
        " organization_id INTEGER NOT NULL,"
        " cuenta_id INTEGER NOT NULL REFERENCES cuentas_objetivo(id) ON DELETE CASCADE,"
        # Tal como lo publica la fuente, para pintarlo sin re-consultar.
        " organo_nombre TEXT NOT NULL,"
        # `plegar_organo`: la clave con la que casa contra `licitaciones`.
        " organo_norm TEXT NOT NULL,"
        # Para el maestro de órganos (C1.2), cuando cubra el corpus.
        " organo_id INTEGER,"
        " created_by_user_id INTEGER,"
        " created_at TEXT NOT NULL,"
        " CONSTRAINT uq_cuenta_organos_org_organo UNIQUE (organization_id, organo_norm)"
        ")"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_cuenta_organos_cuenta ON cuenta_organos (cuenta_id)")
    # Los productores de avisos cruzan por órgano sin saber de qué organización
    # es: la unicidad de arriba empieza por `organization_id` y no les sirve.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cuenta_organos_organo ON cuenta_organos (organo_norm)"
    )
    op.execute(
        "INSERT INTO cuenta_organos "
        "(organization_id, cuenta_id, organo_nombre, organo_norm, organo_id, "
        " created_by_user_id, created_at) "
        "SELECT organization_id, id, btrim(organo_nombre), organo_norm, organo_id, "
        "       created_by_user_id, created_at "
        "FROM cuentas_objetivo "
        "WHERE organo_nombre IS NOT NULL AND organo_norm IS NOT NULL "
        "ON CONFLICT (organization_id, organo_norm) DO NOTHING"
    )

    op.execute("ALTER TABLE cuenta_organos ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cuenta_organos FORCE ROW LEVEL SECURITY")
    for nombre, modo in (("tenant_scope", "PERMISSIVE"), ("tenant_guard", "RESTRICTIVE")):
        politica = f"{nombre}_cuenta_organos"
        op.execute(f"DROP POLICY IF EXISTS {politica} ON cuenta_organos")
        op.execute(
            f"CREATE POLICY {politica} ON cuenta_organos AS {modo} FOR ALL "
            f"USING ({_PREDICADO_TENANT}) WITH CHECK ({_PREDICADO_TENANT})"
        )


def downgrade() -> None:
    """Vuelve a una cuenta por órgano. Se pierden la agrupación y los nombres.

    Una cuenta de varios órganos no cabe en el esquema de v105: se queda con
    su primer órgano y los demás se sueltan. Las cuentas creadas sin columnas
    legadas las recuperan de ese mismo primer órgano; si no tienen ninguno, se
    borran, porque v105 exige órgano.
    """
    if not _is_postgres() or "cuentas_objetivo" not in _tablas():
        return
    if "cuenta_organos" in _tablas():
        op.execute(
            "UPDATE cuentas_objetivo c SET organo_nombre = p.organo_nombre, "
            "       organo_norm = p.organo_norm, organo_id = p.organo_id "
            "FROM (SELECT DISTINCT ON (cuenta_id) cuenta_id, organo_nombre, organo_norm, "
            "             organo_id FROM cuenta_organos ORDER BY cuenta_id, id) p "
            "WHERE p.cuenta_id = c.id AND c.organo_norm IS NULL"
        )
        op.execute("DROP TABLE IF EXISTS cuenta_organos")
    op.execute("DELETE FROM cuentas_objetivo WHERE organo_nombre IS NULL OR organo_norm IS NULL")
    op.execute("DROP INDEX IF EXISTS uq_cuentas_objetivo_org_nombre")
    op.execute("ALTER TABLE cuentas_objetivo ALTER COLUMN organo_norm SET NOT NULL")
    op.execute("ALTER TABLE cuentas_objetivo ALTER COLUMN organo_nombre SET NOT NULL")
    op.execute("ALTER TABLE cuentas_objetivo DROP COLUMN IF EXISTS nombre_norm")
    op.execute("ALTER TABLE cuentas_objetivo DROP COLUMN IF EXISTS nombre")
