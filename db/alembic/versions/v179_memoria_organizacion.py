"""v179: memoria de la organización — el texto indexado de sus adjuntos (ADR-040).

Revision ID: v179_memoria_organizacion
Revises: v178_sistema_contratacion
Create Date: 2026-11-10

Qué añade
---------
``pursuit_attachments.indexable`` (v127) era un permiso sin nadie que lo
leyera: ningún camino indexaba un adjunto. Esta revisión le da dónde vivir a lo
que ese permiso autoriza.

- ``pursuit_attachment_chunks``: los fragmentos del texto extraído de un
  adjunto marcado indexable, con su página y su embedding. **Tabla aparte de
  ``documento_chunks``**, a propósito: el corpus de pliegos es público y lo
  leen sin organización la búsqueda, la señal tecnológica, la ficha, el MCP
  interno y media docena de jobs. Meter aquí una columna ``organization_id``
  habría obligado a acertar el filtro en todas esas consultas, y la primera
  que lo olvidara serviría la propuesta de un cliente como si fuera un pliego.
  En una tabla propia, ninguna consulta que ya existe puede alcanzarla.
- Tres columnas de estado en ``pursuit_attachments`` (``index_status``,
  ``index_error``, ``index_embedding_version``), que es lo que la pantalla
  enseña y lo que el relleno nocturno de embeddings usa para saber qué falta
  sin leer el texto.

No hay tabla de páginas: el fragmento ya lleva su ``page_number`` y nadie lee
el texto privado por página. Una copia menos del dato más sensible del producto.

Los permisos anteriores no se heredan
-------------------------------------
``PUT /pursuits/adjuntos/{id}/indexable`` existe desde v127, cuando marcar un
adjunto no hacía nada. Si alguna fila quedó con ``indexable = true``, esta
revisión la devuelve a ``false``: quien dio ese permiso no lo dio para que se
guardara el texto, y sin job que la indexe la fila se quedaría «pendiente»
para siempre y contando contra el tope. Quien lo quiera lo vuelve a dar, ahora
sabiendo lo que implica.

Aislamiento, en tres capas
--------------------------
1. **La fila no puede mentir sobre de quién es.** La FK es compuesta,
   ``(attachment_id, organization_id) → pursuit_attachments (id,
   organization_id)``: un fragmento con la organización de otro adjunto no se
   puede insertar. Por eso se añade el índice único ``(id, organization_id)``
   sobre ``pursuit_attachments``.
2. **RLS sin paso franco.** Las políticas ``tenant_scope_``/``tenant_guard_``
   llevan el nombre y la forma de v128, pero **no** su primer término: sin
   ``app.organization_id`` fijada, aquí no se ve ni se escribe nada. En v128 el
   paso franco existe para que scheduler, scripts y migraciones sigan viendo
   las tablas corporativas; para el texto de una propuesta no hay ningún
   proceso sin ámbito que deba leerlo, y el que indexa (el worker) lo fija con
   ``tenant_scope``. Los borrados en cascada no dependen de la política: las
   consultas de integridad referencial de Postgres la saltan. Como toda la
   RLS de ADR-034, es un respaldo: mientras el runtime conecte con un rol que
   la salta, la frontera efectiva es la capa 1 y el SQL del repositorio.
3. **Sin acceso para el MCP interno**: no hay ``GRANT`` a ``tenderflow_mcp``
   (``mcp_server/catalogo.py`` la declara oculta).

El índice vectorial no es HNSW
------------------------------
``documento_chunks`` lo tiene porque se busca dentro de un expediente entre
millones de fragmentos. Aquí toda búsqueda va acotada a una organización, que
tiene como mucho unos cientos de fragmentos (el tope de documentos indexables
es de configuración): con el índice por ``organization_id`` el orden exacto es
inmediato. Un HNSW global filtraría **después** de elegir vecinos entre todas
las organizaciones, y la de un cliente pequeño se quedaría sin resultados
detrás de la de uno grande.

shortcut: el índice único sobre ``pursuit_attachments`` y los ``ADD COLUMN``
van en la transacción de la migración, sin ``CONCURRENTLY``; la tabla tiene
decenas de filas. Con cientos de miles, partirlo en dos revisiones.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v179_memoria_organizacion"
down_revision: str | Sequence[str] | None = "v178_sistema_contratacion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Tablas corporativas que crea esta revisión
#: (``tests/test_rls_tenant_scope_integration.py`` las contrasta con el catálogo).
TABLAS_CORPORATIVAS: tuple[str, ...] = ("pursuit_attachment_chunks",)

_TABLA = "pursuit_attachment_chunks"

#: Predicado **estricto**: sin ámbito el resultado es NULL y la fila no pasa.
#: El ``(SELECT …)`` hace que Postgres lo evalúe una vez por consulta y no por
#: fila; el ``NULLIF`` va dentro del cast por lo mismo que en v128 (un GUC que
#: se fijó alguna vez vuelve a ``''``, y ``''::integer`` revienta).
_PREDICADO_TENANT = (
    "organization_id = (SELECT NULLIF(current_setting('app.organization_id', true), '')::integer)"
)

_ESTADOS = "'pending', 'indexed', 'error', 'unsupported', 'sin_texto'"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _tablas() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if not _is_postgres() or "pursuit_attachments" not in _tablas():
        return

    # ── Estado del indexado, en la fila del adjunto ─────────────────────────
    op.execute(
        "ALTER TABLE pursuit_attachments "
        "ADD COLUMN IF NOT EXISTS index_status TEXT "
        f"CONSTRAINT ck_pursuit_attachments_index_status CHECK (index_status IN ({_ESTADOS})), "
        "ADD COLUMN IF NOT EXISTS index_error TEXT, "
        # Versión del modelo con la que se embebieron sus fragmentos; NULL
        # mientras estén solo con texto (búsqueda por palabras).
        "ADD COLUMN IF NOT EXISTS index_embedding_version TEXT"
    )
    # Ver «Los permisos anteriores no se heredan» en la cabecera.
    op.execute("UPDATE pursuit_attachments SET indexable = false WHERE indexable")
    # Destino de la FK compuesta de abajo.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_pursuit_attachments_id_org "
        "ON pursuit_attachments (id, organization_id)"
    )
    # Los que el tope por organización cuenta y el relleno de embeddings recorre.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_pursuit_attachments_indexables "
        "ON pursuit_attachments (organization_id) "
        "WHERE indexable AND deleted_at IS NULL"
    )

    # ── Los fragmentos ──────────────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        # El nombre va literal: `tests/test_tablas_citadas_existen.py` lee de aquí
        # qué tablas crean las migraciones.
        "CREATE TABLE IF NOT EXISTS pursuit_attachment_chunks ("
        " id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,"
        " attachment_id INTEGER NOT NULL,"
        " organization_id INTEGER NOT NULL,"
        " chunk_index INTEGER NOT NULL,"
        " page_number INTEGER,"
        " texto TEXT NOT NULL,"
        # Misma dimensión que `documento_chunks`: el mismo modelo embebe los dos.
        " embedding vector(384),"
        " embedding_model TEXT,"
        " embedding_version TEXT,"
        " search_vector tsvector GENERATED ALWAYS AS (to_tsvector('spanish', texto)) STORED,"
        " CONSTRAINT fk_pursuit_attachment_chunks_adjunto"
        "  FOREIGN KEY (attachment_id, organization_id)"
        "  REFERENCES pursuit_attachments (id, organization_id) ON DELETE CASCADE,"
        " CONSTRAINT uq_pursuit_attachment_chunks_orden UNIQUE (attachment_id, chunk_index)"
        ")"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_pursuit_attachment_chunks_org ON {_TABLA} (organization_id)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_pursuit_attachment_chunks_search "
        f"ON {_TABLA} USING GIN (search_vector)"
    )

    # ── Data API cerrada y rol runtime (patrón de v127) ─────────────────────
    op.execute(f"ALTER TABLE {_TABLA} ENABLE ROW LEVEL SECURITY")
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN "
        f"REVOKE ALL ON TABLE {_TABLA} FROM anon; "
        "END IF; "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN "
        f"REVOKE ALL ON TABLE {_TABLA} FROM authenticated; "
        "END IF; "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tenderflow_app') THEN "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {_TABLA} TO tenderflow_app; "
        f"GRANT USAGE, SELECT ON SEQUENCE {_TABLA}_id_seq TO tenderflow_app; "
        f"DROP POLICY IF EXISTS tenderflow_app_full_access ON {_TABLA}; "
        f"CREATE POLICY tenderflow_app_full_access ON {_TABLA} "
        "FOR ALL TO tenderflow_app USING (true) WITH CHECK (true); "
        "END IF; END $$"
    )

    # ── RLS por organización, sin paso franco ───────────────────────────────
    op.execute(f"ALTER TABLE {_TABLA} FORCE ROW LEVEL SECURITY")
    for nombre, modo in (("tenant_scope", "PERMISSIVE"), ("tenant_guard", "RESTRICTIVE")):
        politica = f"{nombre}_{_TABLA}"
        op.execute(f"DROP POLICY IF EXISTS {politica} ON {_TABLA}")
        op.execute(
            f"CREATE POLICY {politica} ON {_TABLA} AS {modo} FOR ALL "
            f"USING ({_PREDICADO_TENANT}) WITH CHECK ({_PREDICADO_TENANT})"
        )


def downgrade() -> None:
    """Borra el texto indexado y el estado. Los adjuntos y su binario quedan."""
    if not _is_postgres() or "pursuit_attachments" not in _tablas():
        return
    op.execute(f"DROP TABLE IF EXISTS {_TABLA}")
    op.execute("DROP INDEX IF EXISTS idx_pursuit_attachments_indexables")
    op.execute("DROP INDEX IF EXISTS uq_pursuit_attachments_id_org")
    op.execute(
        "ALTER TABLE pursuit_attachments "
        "DROP COLUMN IF EXISTS index_embedding_version, "
        "DROP COLUMN IF EXISTS index_error, "
        "DROP COLUMN IF EXISTS index_status"
    )
