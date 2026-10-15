"""v150: persistencia OAuth del MCP interno (``mcp_oauth_clients`` y ``mcp_oauth_tokens``).

Revision ID: v150_mcp_oauth
Revises: v149_ledger_borrado_org
Create Date: 2026-10-15

Qué falta hoy
-------------
El MCP interno (solo lectura) es su propio servidor de autorización OAuth 2.1:
registra clientes por DCR, emite un código de autorización, un access token y
un refresh token, y delega la identidad del usuario en Google. Necesita dónde
guardar los clientes registrados y los tokens. Sin tabla, un reinicio del
proceso (cada despliegue) invalidaría todas las sesiones de los clientes.

Qué cambia
----------
- ``mcp_oauth_clients``: un cliente registrado. ``redirect_uris`` va aparte de
  ``datos`` porque es lo que se valida en cada ``/authorize``; ``datos``
  (``jsonb``) guarda el resto del registro tal como el SDK lo modela.
- ``mcp_oauth_tokens``: cuatro clases de fila en una sola tabla (``kind``): la
  petición ``pendiente`` entre ``/authorize`` y el callback de Google, el
  ``code`` de autorización, el ``access`` y el ``refresh``. Comparten ciclo de
  vida (nacen con caducidad, se revocan o se consumen) y cualquier consulta
  que quiera «todo lo vivo de este usuario» las necesita juntas.
  - **Solo se guarda ``sha256(token)``** (``token_hash``). Quien lea la tabla
    no puede presentar ningún token; el secreto en claro no existe en la base.
  - ``user_id`` es nulo solo en ``pendiente`` (lo impone un CHECK): todavía no
    se sabe quién es. Con ``ON DELETE CASCADE``, borrar al usuario cierra sus
    sesiones MCP sin código aparte. ``client_id`` también cascada.
  - ``family_id`` agrupa un refresh y los access/refresh que nacen de rotarlo.
    Reutilizar un refresh ya consumido revoca la familia entera. El ``code``
    consumido también conserva la familia de los tokens que se emitieron con
    él, de modo que reutilizar un código revoca lo emitido (RFC 6749 §4.1.2).
    Consumir el token, emitir los nuevos y, si era una reutilización, revocar
    la familia ocurre en **una sola transacción** (``db/mcp_oauth.py``): con la
    emisión aparte, quien pierde la carrera revocaría la familia antes de que
    el ganador insertara sus tokens y estos sobrevivirían.
  - ``datos`` (``jsonb``) lleva lo propio de cada clase: PKCE, redirect URI y
    ``resource`` del código; la petición pendiente completa.
  - ``revoked_at`` sirve a la vez de «revocado» y de «consumido»: el consumo de
    un código o de un refresh es un único ``UPDATE … WHERE revoked_at IS NULL
    RETURNING``, atómico en la base. Dos peticiones simultáneas con el mismo
    refresh producen un solo ganador sin bloqueos en Python.
- Índices por ``(user_id)`` (revocar todo lo de un usuario), ``(family_id)``
  (revocar la familia) y ``(expires_at)`` (purga de caducados).

RLS y políticas
---------------
Ninguna de las dos tablas lleva ``organization_id``: son infraestructura de
autenticación del servicio, no datos de un tenant. No reciben, pues, las
políticas ``tenant_scope``/``tenant_guard`` de ``v128``/``v145`` ni van en
``TABLAS_CORPORATIVAS`` (``tests/test_rls_tenant_scope_integration.py`` solo
exige decisión para tablas con ``organization_id``). Tampoco ``FORCE``: no hay
predicado por fila que imponer al dueño, y el dueño de la tabla es el rol que
corre las migraciones.

Sí llevan ``ENABLE ROW LEVEL SECURITY``, como toda tabla desde ``v52`` (cierra
la Data API de Supabase a ``anon``/``authenticated``), y eso tiene una
consecuencia que esta revisión resuelve en vez de dejar al operador:
``tenderflow_app`` (el rol de runtime en producción) no es dueño, así que con
RLS activa y sin política queda en deny-all. ``scripts/setup_pg_roles.sql`` §3
le crea ``tenderflow_app_full_access`` con un bucle sobre las tablas que
existen **cuando se ejecuta**; una tabla creada después queda sin política
hasta que alguien lo vuelva a correr. Por eso esta migración, como ``v106`` y
``v112``, crea ``tenderflow_app_full_access`` (``FOR ALL ... USING (true) WITH
CHECK (true)``) sobre las dos tablas si el rol existe, y le concede el DML. Se
borra antes por si el script ya la había creado, de modo que el orden entre
migración y script no importa.

La política de lectura del rol ``tenderflow_mcp`` (``scripts/setup_pg_role_mcp.sql``)
no se crea: ambas tablas están clasificadas OCULTA en ``mcp_server/catalogo.py``
porque contienen credenciales. El MCP de solo lectura no las ve, ni siquiera
hasheadas.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v150_mcp_oauth"
down_revision: str | Sequence[str] | None = "v149_ledger_borrado_org"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Tablas que crea esta revisión (sin ``organization_id``: no son corporativas).
TABLAS: tuple[str, ...] = ("mcp_oauth_clients", "mcp_oauth_tokens")

#: Vocabulario de ``mcp_oauth_tokens.kind``.
TIPOS: tuple[str, ...] = ("pendiente", "code", "access", "refresh")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _proteger(tabla: str) -> None:
    """RLS activa y acceso total para ``tenderflow_app`` si el rol existe."""
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
        f"DROP POLICY IF EXISTS tenderflow_app_full_access ON {tabla}; "
        f"CREATE POLICY tenderflow_app_full_access ON {tabla} "
        "FOR ALL TO tenderflow_app USING (true) WITH CHECK (true); "
        "END IF; END $$"
    )


def upgrade() -> None:
    if not _is_postgres():
        return

    op.execute(
        "CREATE TABLE IF NOT EXISTS mcp_oauth_clients ("
        " client_id TEXT PRIMARY KEY,"
        " client_name TEXT,"
        " redirect_uris JSONB NOT NULL,"
        " datos JSONB NOT NULL,"
        " created_at TIMESTAMPTZ NOT NULL DEFAULT now()"
        ")"
    )

    tipos_sql = ", ".join(f"'{t}'" for t in TIPOS)
    op.execute(
        "CREATE TABLE IF NOT EXISTS mcp_oauth_tokens ("
        # sha256 hex del token; el token en claro no se guarda.
        " token_hash TEXT PRIMARY KEY,"
        f" kind TEXT NOT NULL CHECK (kind IN ({tipos_sql})),"
        " client_id TEXT NOT NULL REFERENCES mcp_oauth_clients(client_id) ON DELETE CASCADE,"
        # Nulo solo en `pendiente`: aún no se sabe quién es.
        " user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,"
        " family_id TEXT,"
        " scopes JSONB NOT NULL DEFAULT '[]'::jsonb,"
        " datos JSONB,"
        " expires_at TIMESTAMPTZ NOT NULL,"
        # Revocado o consumido: el consumo es un UPDATE atómico sobre esta columna.
        " revoked_at TIMESTAMPTZ,"
        " created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
        # Solo la petición pendiente puede carecer de usuario.
        " CONSTRAINT ck_mcp_oauth_tokens_usuario"
        " CHECK (kind = 'pendiente' OR user_id IS NOT NULL)"
        ")"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_mcp_oauth_tokens_user ON mcp_oauth_tokens (user_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mcp_oauth_tokens_family ON mcp_oauth_tokens (family_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mcp_oauth_tokens_expires ON mcp_oauth_tokens (expires_at)"
    )

    for tabla in TABLAS:
        _proteger(tabla)


def downgrade() -> None:
    """Retira las dos tablas. Se pierden los clientes registrados y las sesiones MCP."""
    if not _is_postgres():
        return
    op.execute("DROP TABLE IF EXISTS mcp_oauth_tokens")
    op.execute("DROP TABLE IF EXISTS mcp_oauth_clients")
