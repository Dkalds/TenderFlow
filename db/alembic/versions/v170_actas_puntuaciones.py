"""v170: ``documentos.tipo`` admite ``'acta'`` y nacen las tablas de puntuaciones del acta.

Revision ID: v170_actas_puntuaciones
Revises: v169_radar_dismissals_desglose
Create Date: 2026-11-02

Qué falla hoy
-------------
El acta de la mesa de contratación es el único documento público donde constan
los puntos que cada licitador sacó en cada criterio, y es lo que dice por qué
se perdió una oportunidad. ``scraper.codice_parser.parse_document_references``
ya la entrega (``tipo = 'acta'``), pero ``documentos.tipo`` solo admite
``legal``/``technical``/``additional`` (``CHECK`` inline de ``v56``): la
ingesta del expediente entero moriría con ``CheckViolation`` en cuanto
apareciera una. Y aunque entrara, no hay dónde guardar lo que se lea de ella.

Qué hace
--------
1. Sustituye el ``CHECK`` de ``documentos.tipo`` por ``ck_documentos_tipo``,
   con ``acta`` además de los tres de antes. El de ``v56`` no tiene nombre (lo
   bautizó Postgres), así que se busca en el catálogo por su contenido, con el
   mismo bloque y por las mismas razones que ``v103``/``v161`` (``strpos`` y no
   ``LIKE '%…%'``; ``'documentos'::regclass`` y no ``relname``).
2. ``acta_extracciones``: una fila por expediente con el estado de la lectura
   del acta (``ok``, ``sin_tabla``, ``sin_acta``, ``error``). Evita repetir la
   llamada al modelo y dice qué enseñar cuando no hay cifras.
3. ``acta_puntuaciones``: una fila por licitador, criterio y lote, con la
   página y la cita de donde salió. En filas y no en JSON porque la fila es la
   unidad que después se agrega por competidor. ``criterio = NULL`` es la fila
   del total.

Forma, y por qué
----------------
La unicidad ``(licitacion_id, lote_numero, licitador_normalizado, criterio)``
va en un índice de expresión con ``COALESCE``: ``NULL <> NULL`` dejaría sin
proteger justo la fila del total y el nivel de expediente (mismo razonamiento
que ``v148``). ``lote_numero`` es el ``cbc:ID`` del lote tal como se publica y
no un FK a ``lotes.id``, que ``replace_lotes`` reasigna en cada re-ingesta.

``documento_id`` lleva ``ON DELETE CASCADE``: sin el documento no hay cita que
la respalde, y una cifra sin cita no se guarda (ADR-014). La escritura la hace
``db.repositories.puntuaciones_acta`` borrando y volviendo a insertar el
expediente en una transacción; repetirla no duplica. El cascade necesita
``idx_acta_puntuaciones_documento``: el único índice de la tabla empieza por
``licitacion_id`` y, sin uno por ``documento_id``, cada borrado de un documento
recorre ``acta_puntuaciones`` entera.

Sin ``CHECK`` sobre ``puntos``/``puntos_max``: son lo que el modelo leyó del
acta, ya validado contra su cita antes de escribirlo, y un valor raro no debe
tumbar la escritura del expediente entero.

RLS
---
Dato de mercado, sin ``organization_id``: no lleva políticas por tenant. Nacen
cerradas a ``anon``/``authenticated`` y abiertas a ``tenderflow_app``, como las
de ``v148``.

Downgrade
---------
Quita las dos tablas y **borra los documentos ``acta``**, que son los que el
``CHECK`` anterior rechaza. No se reetiquetan como ``additional``: antes de esta
revisión las actas no se guardaban, y como ``additional`` la ficha del pliego
las leería como si fueran pliego. Lo que cuelga de ellos (``documento_chunks``,
``documento_pages``) cae en cascada; los blobs del almacén de objetos quedan
huérfanos.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v170_actas_puntuaciones"
down_revision: str | Sequence[str] | None = "v169_radar_dismissals_desglose"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TIPOS_NUEVOS = ("legal", "technical", "additional", "acta")
_TIPOS_ANTERIORES = ("legal", "technical", "additional")

_STATUS_EXTRACCION = ("ok", "sin_tabla", "sin_acta", "error")

#: El ``CHECK`` de ``v56`` es inline y Postgres lo bautizó (``documentos_tipo_check``);
#: el que deja esta revisión tiene nombre propio. Se tiran **todas** las
#: restricciones CHECK de la tabla cuya definición mencione ``'legal'``, que solo
#: puede ser la de ``tipo`` (en cualquiera de sus dos nombres, así que repetir la
#: revisión tampoco duplica). Mismo bloque que ``v103``/``v161``.
_DROP_CHECK_TIPO = """
DO $$
DECLARE
    nombre text;
BEGIN
    FOR nombre IN
        SELECT con.conname
          FROM pg_constraint con
         WHERE con.conrelid = 'documentos'::regclass
           AND con.contype = 'c'
           AND strpos(pg_get_constraintdef(con.oid), 'legal') > 0
    LOOP
        EXECUTE 'ALTER TABLE documentos DROP CONSTRAINT ' || quote_ident(nombre);
    END LOOP;
END
$$
"""


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _check_tipo(nombre: str, valores: tuple[str, ...]) -> str:
    literales = ", ".join(f"'{v}'" for v in valores)
    return f"ALTER TABLE documentos ADD CONSTRAINT {nombre} CHECK (tipo IN ({literales}))"


def _proteger(tabla: str, secuencia: str | None = None) -> None:
    """RLS fail-closed para la Data API y acceso explícito del rol runtime."""
    grant_secuencia = (
        f"GRANT USAGE, SELECT ON SEQUENCE {secuencia} TO tenderflow_app; " if secuencia else ""
    )
    op.execute(f"ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY")
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN "
        f"REVOKE ALL ON TABLE {tabla} FROM anon; "
        "END IF; "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN "
        f"REVOKE ALL ON TABLE {tabla} FROM authenticated; "
        "END IF; "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tenderflow_app') THEN "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {tabla} TO tenderflow_app; "
        f"{grant_secuencia}"
        "IF NOT EXISTS (SELECT 1 FROM pg_policies "
        f"WHERE schemaname = current_schema() AND tablename = '{tabla}' "
        "AND policyname = 'tenderflow_app_full_access') THEN "
        f"CREATE POLICY tenderflow_app_full_access ON {tabla} "
        "FOR ALL TO tenderflow_app USING (true) WITH CHECK (true); "
        "END IF; END IF; END $$"
    )


def upgrade() -> None:
    if not _is_postgres():
        return

    op.execute(_DROP_CHECK_TIPO)
    op.execute(_check_tipo("ck_documentos_tipo", _TIPOS_NUEVOS))

    op.create_table(
        "acta_extracciones",
        sa.Column(
            "licitacion_id",
            sa.Text,
            sa.ForeignKey("licitaciones.id_externo", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("extraction_version", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=True),
        sa.Column("documentos_leidos", sa.Integer, nullable=False),
        sa.Column("error_detail", sa.Text, nullable=True),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in _STATUS_EXTRACCION) + ")",
            name="ck_acta_extracciones_status",
        ),
    )
    op.create_table(
        "acta_puntuaciones",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "licitacion_id",
            sa.Text,
            sa.ForeignKey("licitaciones.id_externo", ondelete="CASCADE"),
            nullable=False,
        ),
        # `cbc:ID` del lote tal como se publica; NULL = nivel de expediente.
        sa.Column("lote_numero", sa.Text, nullable=True),
        # Tal como lo publica el acta, y su forma normalizada
        # (`services.normalization.normalize_company`) para casar y agrupar.
        sa.Column("licitador_nombre", sa.Text, nullable=False),
        sa.Column("licitador_normalizado", sa.Text, nullable=False),
        # NULL = la fila del total del licitador.
        sa.Column("criterio", sa.Text, nullable=True),
        sa.Column("puntos", sa.Float, nullable=True),
        sa.Column("puntos_max", sa.Float, nullable=True),
        sa.Column("es_precio", sa.Boolean, nullable=True),
        sa.Column("excluida", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column(
            "documento_id",
            sa.Integer,
            sa.ForeignKey("documentos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pagina", sa.Integer, nullable=False),
        sa.Column("cita", sa.Text, nullable=False),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_acta_puntuaciones_fila ON acta_puntuaciones "
        "(licitacion_id, COALESCE(lote_numero, ''), licitador_normalizado, COALESCE(criterio, ''))"
    )
    # Para el `ON DELETE CASCADE` de `documento_id` (ver «Forma, y por qué»). El
    # downgrade lo arrastra al quitar la tabla.
    op.create_index("idx_acta_puntuaciones_documento", "acta_puntuaciones", ["documento_id"])
    _proteger("acta_extracciones")
    _proteger("acta_puntuaciones", secuencia="acta_puntuaciones_id_seq")


def downgrade() -> None:
    if not _is_postgres():
        return

    op.drop_table("acta_puntuaciones")
    op.drop_table("acta_extracciones")
    # Antes de estrechar el CHECK: con filas `acta` el ADD CONSTRAINT fallaría
    # y el downgrade quedaría a medias.
    op.execute("DELETE FROM documentos WHERE tipo = 'acta'")
    op.execute(_DROP_CHECK_TIPO)
    op.execute(_check_tipo("documentos_tipo_check", _TIPOS_ANTERIORES))
