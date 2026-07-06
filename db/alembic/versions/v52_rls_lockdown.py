"""Migracion v52 -- RLS lockdown defensivo (Postgres/Supabase).

Esta migracion es DIALECT-GUARDED: solo hace algo en Postgres. En SQLite es
un no-op (RLS no existe).

Motivacion (revision de seguridad Supabase, ADR-016):
  Supabase expone una Data API (PostgREST) sobre el schema ``public`` accesible
  con la ``anon`` key (publica). Si esa API llegara a estar activa y las tablas
  no tienen RLS, cualquiera con la anon key podria leer/escribir PII y material
  sensible (``users``, ``api_keys``, ``totp_secrets``, ``sessions``,
  ``audit_log``...). El runbook de cutover manda desactivar la Data API, pero eso
  es un paso manual no verificado. Esta migracion cierra la puerta a nivel de BD
  (fail-closed) como defensa en profundidad, independientemente de la Data API.

Que hace (solo Postgres):
  1. ``ENABLE ROW LEVEL SECURITY`` en todas las tablas base de ``public``
     (excepto ``alembic_version``). SIN ``FORCE``: el rol dueño de las tablas
     (con el que conecta la app) *bypassa* RLS por diseno, por lo que NO se
     rompe ninguna query de la aplicacion. Solo se cierra a roles no-dueños
     (``anon``/``authenticated``), que sin politicas ven deny-all.
  2. ``REVOKE`` de todos los privilegios de ``anon``/``authenticated`` sobre el
     schema ``public`` (tablas, secuencias, funciones y USAGE del schema), y
     ``ALTER DEFAULT PRIVILEGES`` para que futuras tablas tampoco les concedan
     acceso. Todo GUARDADO por existencia de rol via ``pg_roles`` -- en un
     Postgres puro (CI ``integration-pg``) esos roles no existen y se omite.

Reversibilidad: ``downgrade()`` deshabilita RLS y re-concede los privilegios por
defecto de Supabase (estado inseguro previo) -- solo para rollback.

Revision ID: v52_rls_lockdown
Revises: v51_pg_legacy_tables_backfill
Create Date: 2026-07-06
"""

from __future__ import annotations

from alembic import op

revision: str = "v52_rls_lockdown"
down_revision: str | None = "v51_pg_legacy_tables_backfill"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


# SQL estático (sin interpolación): habilita RLS en todas las tablas base de public
# (sin FORCE → el rol dueño, con el que conecta la app, bypassa RLS y no se rompe
# ninguna query; los roles no-dueños anon/authenticated quedan deny-all sin políticas).
_ENABLE_RLS = """
DO $$
DECLARE r RECORD;
BEGIN
    FOR r IN
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public' AND tablename <> 'alembic_version'
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', r.tablename);
    END LOOP;
END $$;
"""

_DISABLE_RLS = """
DO $$
DECLARE r RECORD;
BEGIN
    FOR r IN
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public' AND tablename <> 'alembic_version'
    LOOP
        EXECUTE format('ALTER TABLE public.%I DISABLE ROW LEVEL SECURITY', r.tablename);
    END LOOP;
END $$;
"""

# Revoca todo acceso de los roles PostgREST de Supabase (anon/authenticated) sobre
# public, y bloquea futuras concesiones por defecto. Guardado por existencia de rol
# (en un Postgres puro -- CI integration-pg -- esos roles no existen y se omite).
_REVOKE_EXPOSED_ROLES = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon;
        REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon;
        REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM anon;
        REVOKE USAGE ON SCHEMA public FROM anon;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON ALL TABLES IN SCHEMA public FROM authenticated;
        REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM authenticated;
        REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM authenticated;
        REVOKE USAGE ON SCHEMA public FROM authenticated;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM authenticated;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM authenticated;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM authenticated;
    END IF;
END $$;
"""

# Re-concede los privilegios por defecto de Supabase (estado INSEGURO previo).
# Solo para rollback; guardado por existencia de rol.
_REGRANT_EXPOSED_ROLES = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        GRANT USAGE ON SCHEMA public TO anon;
        GRANT ALL ON ALL TABLES IN SCHEMA public TO anon;
        GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO anon;
        GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO anon;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO anon;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        GRANT USAGE ON SCHEMA public TO authenticated;
        GRANT ALL ON ALL TABLES IN SCHEMA public TO authenticated;
        GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO authenticated;
        GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO authenticated;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO authenticated;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO authenticated;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO authenticated;
    END IF;
END $$;
"""


def upgrade() -> None:
    if not _is_postgres():
        return  # no-op en SQLite -- RLS no existe
    op.execute(_ENABLE_RLS)
    op.execute(_REVOKE_EXPOSED_ROLES)


def downgrade() -> None:
    if not _is_postgres():
        return  # no-op en SQLite
    op.execute(_REGRANT_EXPOSED_ROLES)
    op.execute(_DISABLE_RLS)
