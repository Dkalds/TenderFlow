-- Rol de privilegios mínimos para la app/scheduler/scraper (F3d, roadmap del
-- runbook de migración de persistencia — docs/runbooks/migracion-persistencia.md
-- Paso 9 / "Roadmap F3d+").
--
-- Hoy toda la infraestructura (app, scheduler, scraper, alembic, backup) comparte
-- una única DATABASE_URL con el rol dueño del schema (privilegios altos: DDL,
-- ownership). Este script separa responsabilidades: `tenderflow_app` es un rol
-- de solo-DML (SELECT/INSERT/UPDATE/DELETE + secuencias) sin capacidad de crear
-- ni alterar tablas — si esa credencial se filtra, el daño se limita a los datos,
-- no al schema.
--
-- ⚠️ DEPENDENCIA CON RLS (v52_rls_lockdown): esa migración habilita
-- ROW LEVEL SECURITY sin FORCE. El rol DUEÑO de las tablas (con el que conecta
-- hoy la app) *bypassa* RLS por diseño — por eso v52 no rompió nada al aplicarse.
-- `tenderflow_app` NO es dueño de las tablas: en cuanto se cree, sin políticas
-- explícitas para él, RLS lo deja en **deny-all** (las mismas reglas que dejan a
-- anon/authenticated sin acceso). Este script añade las políticas RLS
-- permisivas específicas de `tenderflow_app` en la sección 3 — sin ellas, la app
-- quedaría rota en cuanto se apunte DATABASE_URL a este rol.
--
-- Cómo ejecutar (acción manual del usuario — gate secrets+ops, AGENTS.md §6):
--   1. Generar una password fuerte: openssl rand -base64 32
--   2. Sustituir el placeholder <GENERAR_PASSWORD_FUERTE> abajo con esa password.
--   3. Ejecutar contra Supabase con el rol ADMIN (dueño del schema, DATABASE_ADMIN_URL):
--        psql "$DATABASE_ADMIN_URL" -f scripts/setup_pg_roles.sql
--   4. Construir la nueva DATABASE_URL de la app con este rol:
--        postgresql://tenderflow_app:<password>@<host>:5432/postgres?sslmode=verify-full
--   5. Actualizar el secret DATABASE_URL (Render + GitHub Actions) con esa URL.
--      Guardar DATABASE_ADMIN_URL (el rol dueño original) como secret aparte,
--      SOLO para correr `alembic upgrade head` — nunca en el runtime de la app.
--   6. Verificar (ver checklist psql en el runbook, Paso 9):
--        psql "$DATABASE_URL" -c "SELECT current_user"          -- tenderflow_app
--        psql "$DATABASE_URL" -c "CREATE TABLE t(x int)"        -- debe FALLAR (sin DDL)
--        psql "$DATABASE_URL" -c "SELECT count(*) FROM licitaciones"  -- debe funcionar
--
-- Idempotente: seguro de re-ejecutar (CREATE ROLE / CREATE POLICY guardados).

-- ── 1. Rol de aplicación ────────────────────────────────────────────────────

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tenderflow_app') THEN
        CREATE ROLE tenderflow_app LOGIN PASSWORD '<GENERAR_PASSWORD_FUERTE>';  -- pragma: allowlist secret
    END IF;
END $$;

-- Timeouts por rol — evita que una query/transacción colgada de la app
-- retenga locks o conexiones del pool indefinidamente.
ALTER ROLE tenderflow_app SET statement_timeout = '30s';
ALTER ROLE tenderflow_app SET idle_in_transaction_session_timeout = '60s';

-- ── 2. Privilegios DML (sin DDL, sin ownership) ─────────────────────────────

GRANT USAGE ON SCHEMA public TO tenderflow_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO tenderflow_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO tenderflow_app;

-- Tablas creadas DESPUÉS de este script (por futuras migraciones alembic, que
-- corren con el rol dueño/ADMIN) heredan el mismo acceso automáticamente.
-- Alcance: objetos creados por el rol que EJECUTA este bloque — correr este
-- script conectado como el rol ADMIN/dueño (ver instrucciones arriba) para que
-- el alcance sea correcto.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tenderflow_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO tenderflow_app;

-- ── 3. Políticas RLS para tenderflow_app (dependencia de v52_rls_lockdown) ──
-- Sin esto, tenderflow_app (no-dueño) queda deny-all en cuanto RLS está activo.
-- Política permisiva total: tenderflow_app es un rol de confianza interno (la
-- app entera), no un rol expuesto públicamente como anon/authenticated — el
-- control de acceso real vive en la capa de aplicación (auth_core, scopes),
-- no en RLS por-fila. RLS aquí solo existe para cerrar la Data API pública.

DO $$
DECLARE r RECORD;
BEGIN
    FOR r IN
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public' AND tablename <> 'alembic_version'
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
            WHERE schemaname = 'public' AND tablename = r.tablename
              AND policyname = 'tenderflow_app_full_access'
        ) THEN
            EXECUTE format(
                'CREATE POLICY tenderflow_app_full_access ON public.%I '
                'FOR ALL TO tenderflow_app USING (true) WITH CHECK (true)',
                r.tablename
            );
        END IF;
    END LOOP;
END $$;

-- ── Verificación rápida post-ejecución ──────────────────────────────────────
-- SELECT rolname, rolconnlimit FROM pg_roles WHERE rolname = 'tenderflow_app';
-- SELECT tablename, policyname FROM pg_policies WHERE policyname = 'tenderflow_app_full_access';
