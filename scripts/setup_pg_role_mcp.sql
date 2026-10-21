-- GENERADO por scripts/gen_mcp_grants.py a partir de mcp_server/catalogo.py.
-- No lo edites a mano: cambia el catálogo y regenera con
--   python scripts/gen_mcp_grants.py
-- (`--check` falla en CI/tests si este fichero está desfasado).
--
-- Rol `tenderflow_mcp` del MCP interno de solo lectura: SELECT sobre las tablas
-- de datos de mercado y de cliente del catálogo, nada sobre credenciales ni
-- secretos (api_keys, sessions, TOTP, tokens, tablas OAuth del MCP, cadena de
-- auditoría), y sin columnas con hashes de contraseña o secretos de webhook.
-- Transacciones de solo lectura, timeouts y 5 conexiones como máximo.
--
-- Cómo ejecutar (acción manual del usuario — gate secrets+ops, AGENTS.md §6):
--   1. Generar una password fuerte: openssl rand -base64 32
--   2. Sustituir el placeholder <GENERAR_PASSWORD_FUERTE> abajo con esa password.
--   3. Aplicar antes las migraciones (`alembic upgrade head`): el script exige que
--      existan todas las tablas visibles del catálogo y aborta si falta alguna.
--   4. Ejecutar contra Supabase con el rol ADMIN (dueño del schema, DATABASE_ADMIN_URL),
--      de forma atómica (sin estos flags un error a medias deja el rol sin permisos):
--        psql -v ON_ERROR_STOP=1 --single-transaction "$DATABASE_ADMIN_URL" \
--             -f scripts/setup_pg_role_mcp.sql
--   5. Construir MCP_DATABASE_URL con este rol:
--        postgresql://tenderflow_mcp:<password>@<host>:5432/postgres?sslmode=verify-full
--
-- Idempotente: seguro de re-ejecutar (con los flags de arriba, todo o nada). Los GRANT parten de un REVOKE completo, así
-- que una tabla o columna que el catálogo oculte después pierde el acceso.
-- Fallo cerrado: no hay ALTER DEFAULT PRIVILEGES; una tabla nueva es invisible
-- para este rol hasta clasificarla en el catálogo y regenerar este fichero.

-- ── 1. Rol ──────────────────────────────────────────────────────────────────

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tenderflow_mcp') THEN
        CREATE ROLE tenderflow_mcp LOGIN PASSWORD '<GENERAR_PASSWORD_FUERTE>';  -- pragma: allowlist secret
    END IF;
END $$;

-- ── 2. Límites del rol ──────────────────────────────────────────────────────
DO $$ BEGIN IF (SELECT rolsuper FROM pg_roles WHERE rolname = 'tenderflow_mcp') THEN RAISE EXCEPTION 'tenderflow_mcp no puede ser superusuario'; END IF; END $$;
ALTER ROLE "tenderflow_mcp" NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 5;
ALTER ROLE "tenderflow_mcp" SET default_transaction_read_only = on;
ALTER ROLE "tenderflow_mcp" SET statement_timeout = '15s';
ALTER ROLE "tenderflow_mcp" SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE "tenderflow_mcp" SET work_mem = '32MB';
ALTER ROLE "tenderflow_mcp" SET search_path = pg_catalog, public;
ALTER ROLE "tenderflow_mcp" SET extra_float_digits = 3;

-- ── 3. Privilegios de lectura y política RLS ───────────────────────────────
DO $$
DECLARE faltan text;
BEGIN
    SELECT string_agg(t, ', ' ORDER BY t) INTO faltan
    FROM unnest(ARRAY['adjudicaciones', 'contrato_eventos', 'extracciones_retirada', 'extraction_runs', 'failed_extractions', 'ingestion_cursors', 'licitacion_criterios_adjudicacion', 'licitacion_garantias', 'licitacion_solvencia', 'licitaciones', 'licitaciones_duplicados', 'licitaciones_history', 'lotes', 'resoluciones_recurso', 'source_ingestion_health', 'documento_chunks', 'documento_pages', 'documentos', 'tender_fact_sheets', 'empresa_aliases', 'empresa_review_queue', 'empresas', 'grupos_empresariales', 'mat_clusters', 'organo_aliases', 'organo_review_queue', 'organos', 'ute_miembros', 'contratos_cartera', 'cuenta_organos', 'cuentas_objetivo', 'etiquetas', 'etiquetas_aplicadas', 'go_no_go_scores', 'go_no_go_weights', 'organization_certifications', 'organization_invitations', 'organization_memberships', 'organization_nifs', 'organization_references', 'organization_report_schedules', 'organization_revenues', 'organization_team_profiles', 'organizations', 'plantillas_aplicadas', 'plantillas_organizacion', 'pursuit_attachments', 'pursuit_comment_mentions', 'pursuit_comments', 'pursuit_events', 'pursuit_tasks', 'pursuits', 'access_grants', 'access_log', 'api_key_tiers', 'audit_log', 'csp_violations', 'solicitudes_acceso', 'users', 'follows', 'notification_preferences', 'notification_reads', 'pending_digests', 'radar_dismissals', 'saved_filters', 'user_event_prefs', 'user_notifications', 'user_profiles', 'watchlist_cpv', 'watchlist_empresas', 'watchlist_items', 'watchlist_rules', 'webhook_deliveries', 'webhooks', 'asistente_feedback', 'feature_store', 'licitacion_tecnologia_pliego', 'licitacion_tecnologia_score', 'ml_feedback', 'model_versions', 'predicciones_baja', 'predicciones_retencion', 'tasas_anulacion_organo', 'tecnologias_keywords', 'client_errors', 'domain_event_dispatches', 'domain_events', 'feature_flags', 'job_locks', 'jobs', 'kpi_snapshots', 'ops_events']) AS t
    WHERE to_regclass(format('%I.%I', 'public', t)) IS NULL;
    IF faltan IS NOT NULL THEN
        RAISE EXCEPTION
            'tenderflow_mcp: faltan tablas visibles en public: %. '
            'Aplica antes `alembic upgrade head`.', faltan;
    END IF;
END $$;
REVOKE ALL ON ALL TABLES IN SCHEMA "public" FROM "tenderflow_mcp";
REVOKE CREATE ON SCHEMA "public" FROM "tenderflow_mcp";
GRANT USAGE ON SCHEMA "public" TO "tenderflow_mcp";
GRANT SELECT ON "public"."adjudicaciones" TO "tenderflow_mcp";
GRANT SELECT ON "public"."contrato_eventos" TO "tenderflow_mcp";
GRANT SELECT ON "public"."extracciones_retirada" TO "tenderflow_mcp";
GRANT SELECT ON "public"."extraction_runs" TO "tenderflow_mcp";
GRANT SELECT ON "public"."failed_extractions" TO "tenderflow_mcp";
GRANT SELECT ON "public"."ingestion_cursors" TO "tenderflow_mcp";
GRANT SELECT ON "public"."licitacion_criterios_adjudicacion" TO "tenderflow_mcp";
GRANT SELECT ON "public"."licitacion_garantias" TO "tenderflow_mcp";
GRANT SELECT ON "public"."licitacion_solvencia" TO "tenderflow_mcp";
GRANT SELECT ON "public"."licitaciones" TO "tenderflow_mcp";
GRANT SELECT ON "public"."licitaciones_duplicados" TO "tenderflow_mcp";
GRANT SELECT ON "public"."licitaciones_history" TO "tenderflow_mcp";
GRANT SELECT ON "public"."lotes" TO "tenderflow_mcp";
GRANT SELECT ON "public"."resoluciones_recurso" TO "tenderflow_mcp";
GRANT SELECT ON "public"."source_ingestion_health" TO "tenderflow_mcp";
GRANT SELECT ON "public"."documento_chunks" TO "tenderflow_mcp";
GRANT SELECT ON "public"."documento_pages" TO "tenderflow_mcp";
GRANT SELECT ON "public"."documentos" TO "tenderflow_mcp";
GRANT SELECT ON "public"."tender_fact_sheets" TO "tenderflow_mcp";
GRANT SELECT ON "public"."empresa_aliases" TO "tenderflow_mcp";
GRANT SELECT ON "public"."empresa_review_queue" TO "tenderflow_mcp";
GRANT SELECT ON "public"."empresas" TO "tenderflow_mcp";
GRANT SELECT ON "public"."grupos_empresariales" TO "tenderflow_mcp";
GRANT SELECT ON "public"."mat_clusters" TO "tenderflow_mcp";
GRANT SELECT ON "public"."organo_aliases" TO "tenderflow_mcp";
GRANT SELECT ON "public"."organo_review_queue" TO "tenderflow_mcp";
GRANT SELECT ON "public"."organos" TO "tenderflow_mcp";
GRANT SELECT ON "public"."ute_miembros" TO "tenderflow_mcp";
GRANT SELECT ON "public"."contratos_cartera" TO "tenderflow_mcp";
GRANT SELECT ON "public"."cuenta_organos" TO "tenderflow_mcp";
GRANT SELECT ON "public"."cuentas_objetivo" TO "tenderflow_mcp";
GRANT SELECT ON "public"."etiquetas" TO "tenderflow_mcp";
GRANT SELECT ON "public"."etiquetas_aplicadas" TO "tenderflow_mcp";
GRANT SELECT ON "public"."go_no_go_scores" TO "tenderflow_mcp";
GRANT SELECT ON "public"."go_no_go_weights" TO "tenderflow_mcp";
GRANT SELECT ON "public"."organization_certifications" TO "tenderflow_mcp";
GRANT SELECT ("id", "organization_id", "email", "role", "invited_by_user_id", "created_at", "expires_at", "accepted_at", "accepted_user_id", "revoked_at", "revoked_by_user_id") ON "public"."organization_invitations" TO "tenderflow_mcp";
GRANT SELECT ON "public"."organization_memberships" TO "tenderflow_mcp";
GRANT SELECT ON "public"."organization_nifs" TO "tenderflow_mcp";
GRANT SELECT ON "public"."organization_references" TO "tenderflow_mcp";
GRANT SELECT ON "public"."organization_report_schedules" TO "tenderflow_mcp";
GRANT SELECT ON "public"."organization_revenues" TO "tenderflow_mcp";
GRANT SELECT ON "public"."organization_team_profiles" TO "tenderflow_mcp";
GRANT SELECT ON "public"."organizations" TO "tenderflow_mcp";
GRANT SELECT ON "public"."plantillas_aplicadas" TO "tenderflow_mcp";
GRANT SELECT ON "public"."plantillas_organizacion" TO "tenderflow_mcp";
GRANT SELECT ON "public"."pursuit_attachments" TO "tenderflow_mcp";
GRANT SELECT ON "public"."pursuit_comment_mentions" TO "tenderflow_mcp";
GRANT SELECT ON "public"."pursuit_comments" TO "tenderflow_mcp";
GRANT SELECT ON "public"."pursuit_events" TO "tenderflow_mcp";
GRANT SELECT ON "public"."pursuit_tasks" TO "tenderflow_mcp";
GRANT SELECT ON "public"."pursuits" TO "tenderflow_mcp";
GRANT SELECT ON "public"."access_grants" TO "tenderflow_mcp";
GRANT SELECT ON "public"."access_log" TO "tenderflow_mcp";
GRANT SELECT ON "public"."api_key_tiers" TO "tenderflow_mcp";
GRANT SELECT ON "public"."audit_log" TO "tenderflow_mcp";
GRANT SELECT ON "public"."csp_violations" TO "tenderflow_mcp";
GRANT SELECT ON "public"."solicitudes_acceso" TO "tenderflow_mcp";
GRANT SELECT ("id", "email", "oauth_provider", "oauth_sub", "display_name", "created_at", "is_admin", "deactivated_at", "admin_granted_by", "email_verified_at") ON "public"."users" TO "tenderflow_mcp";
GRANT SELECT ON "public"."follows" TO "tenderflow_mcp";
GRANT SELECT ON "public"."notification_preferences" TO "tenderflow_mcp";
GRANT SELECT ON "public"."notification_reads" TO "tenderflow_mcp";
GRANT SELECT ON "public"."pending_digests" TO "tenderflow_mcp";
GRANT SELECT ON "public"."radar_dismissals" TO "tenderflow_mcp";
GRANT SELECT ON "public"."saved_filters" TO "tenderflow_mcp";
GRANT SELECT ON "public"."user_event_prefs" TO "tenderflow_mcp";
GRANT SELECT ON "public"."user_notifications" TO "tenderflow_mcp";
GRANT SELECT ON "public"."user_profiles" TO "tenderflow_mcp";
GRANT SELECT ON "public"."watchlist_cpv" TO "tenderflow_mcp";
GRANT SELECT ON "public"."watchlist_empresas" TO "tenderflow_mcp";
GRANT SELECT ON "public"."watchlist_items" TO "tenderflow_mcp";
GRANT SELECT ON "public"."watchlist_rules" TO "tenderflow_mcp";
GRANT SELECT ON "public"."webhook_deliveries" TO "tenderflow_mcp";
GRANT SELECT ("id", "name", "event_types", "active", "created_at", "last_triggered_at", "last_status", "failure_count", "organization_id", "created_by", "formato") ON "public"."webhooks" TO "tenderflow_mcp";
GRANT SELECT ON "public"."asistente_feedback" TO "tenderflow_mcp";
GRANT SELECT ON "public"."feature_store" TO "tenderflow_mcp";
GRANT SELECT ON "public"."licitacion_tecnologia_pliego" TO "tenderflow_mcp";
GRANT SELECT ON "public"."licitacion_tecnologia_score" TO "tenderflow_mcp";
GRANT SELECT ON "public"."ml_feedback" TO "tenderflow_mcp";
GRANT SELECT ON "public"."model_versions" TO "tenderflow_mcp";
GRANT SELECT ON "public"."predicciones_baja" TO "tenderflow_mcp";
GRANT SELECT ON "public"."predicciones_retencion" TO "tenderflow_mcp";
GRANT SELECT ON "public"."tasas_anulacion_organo" TO "tenderflow_mcp";
GRANT SELECT ON "public"."tecnologias_keywords" TO "tenderflow_mcp";
GRANT SELECT ON "public"."client_errors" TO "tenderflow_mcp";
GRANT SELECT ON "public"."domain_event_dispatches" TO "tenderflow_mcp";
GRANT SELECT ON "public"."domain_events" TO "tenderflow_mcp";
GRANT SELECT ON "public"."feature_flags" TO "tenderflow_mcp";
GRANT SELECT ON "public"."job_locks" TO "tenderflow_mcp";
GRANT SELECT ON "public"."jobs" TO "tenderflow_mcp";
GRANT SELECT ON "public"."kpi_snapshots" TO "tenderflow_mcp";
GRANT SELECT ON "public"."ops_events" TO "tenderflow_mcp";
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['adjudicaciones', 'contrato_eventos', 'extracciones_retirada', 'extraction_runs', 'failed_extractions', 'ingestion_cursors', 'licitacion_criterios_adjudicacion', 'licitacion_garantias', 'licitacion_solvencia', 'licitaciones', 'licitaciones_duplicados', 'licitaciones_history', 'lotes', 'resoluciones_recurso', 'source_ingestion_health', 'documento_chunks', 'documento_pages', 'documentos', 'tender_fact_sheets', 'empresa_aliases', 'empresa_review_queue', 'empresas', 'grupos_empresariales', 'mat_clusters', 'organo_aliases', 'organo_review_queue', 'organos', 'ute_miembros', 'contratos_cartera', 'cuenta_organos', 'cuentas_objetivo', 'etiquetas', 'etiquetas_aplicadas', 'go_no_go_scores', 'go_no_go_weights', 'organization_certifications', 'organization_invitations', 'organization_memberships', 'organization_nifs', 'organization_references', 'organization_report_schedules', 'organization_revenues', 'organization_team_profiles', 'organizations', 'plantillas_aplicadas', 'plantillas_organizacion', 'pursuit_attachments', 'pursuit_comment_mentions', 'pursuit_comments', 'pursuit_events', 'pursuit_tasks', 'pursuits', 'access_grants', 'access_log', 'api_key_tiers', 'audit_log', 'csp_violations', 'solicitudes_acceso', 'users', 'follows', 'notification_preferences', 'notification_reads', 'pending_digests', 'radar_dismissals', 'saved_filters', 'user_event_prefs', 'user_notifications', 'user_profiles', 'watchlist_cpv', 'watchlist_empresas', 'watchlist_items', 'watchlist_rules', 'webhook_deliveries', 'webhooks', 'asistente_feedback', 'feature_store', 'licitacion_tecnologia_pliego', 'licitacion_tecnologia_score', 'ml_feedback', 'model_versions', 'predicciones_baja', 'predicciones_retencion', 'tasas_anulacion_organo', 'tecnologias_keywords', 'client_errors', 'domain_event_dispatches', 'domain_events', 'feature_flags', 'job_locks', 'jobs', 'kpi_snapshots', 'ops_events'] LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
            WHERE schemaname = 'public' AND tablename = t
              AND policyname = 'tenderflow_mcp_read' AND 'tenderflow_mcp' = ANY (roles)
        ) THEN
            EXECUTE format(
                'CREATE POLICY tenderflow_mcp_read ON %I.%I FOR SELECT TO %I USING (true)',
                'public', t, 'tenderflow_mcp'
            );
        END IF;
    END LOOP;
END $$;
