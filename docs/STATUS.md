---
tags: [status, generado]
---

# Estado del proyecto (derivado del código)

<!-- generado por scripts/gen_status.py — no editar a mano -->

Generado: 2026-09-08

## Paridad de planos de orquestación (ADR-012)

| Job | Plano | Cubierto por |
|---|---|---|
| `daily_atom` | actions | python -m scheduler.run_update |
| `recent_bulk` | manual | python -m scheduler.run_update (workflow_dispatch) |
| `retention_cleanup` | pipeline | CANONICAL_STEPS[retention_cleanup] |
| `ml_scoring_baja` | actions | python -m scheduler.jobs.ml_predicciones |
| `ml_retrain_baja` | actions | python -m scheduler.jobs.ml_predicciones |
| `documentos_embeddings` | actions | python -m scheduler.jobs.documentos_embeddings |
| `dlq_retry` | pipeline | CANONICAL_STEPS[dlq_retry] |
| `digest_daily` | pipeline | CANONICAL_STEPS[digests] |
| `watchlist_rules` | pipeline | CANONICAL_STEPS[watchlist_notify] |
| `llm_tech_labeling` | pipeline | CANONICAL_STEPS[llm_tech_labeling] |
| `llm_models_canary` | pipeline | CANONICAL_STEPS[llm_models_canary] |
| `anomaly_checks` | pipeline | CANONICAL_STEPS[anomaly_checks] |
| `drift_report` | pipeline | CANONICAL_STEPS[drift_checks] |
| `ficha_pliego` | worker | render.yaml (APP_PROFILE=worker) |
| `embeddings_expediente` | worker | render.yaml (APP_PROFILE=worker) |
| `export_pdf` | worker | render.yaml (APP_PROFILE=worker) |
| `paso_pipeline` | pipeline | cierre de la pasada (Actions) |

**17 jobs, todos con plano verificado.**

## Ratchet TID251 — acceso directo a BD fuera de repositories

**28 archivos** en whitelist (solo puede decrecer).

- `scheduler/aggregates_precompute.py`
- `scheduler/anomaly_alerts.py`
- `scheduler/competitor_alerts.py`
- `scheduler/concept_drift.py`
- `scheduler/drift_report.py`
- `scheduler/healthcheck.py`
- `scheduler/kpi_precompute.py`
- `scheduler/retention.py`
- `scheduler/watchlist_rules_alerts.py`
- `scraper/ml_training.py`
- `scraper/tech_classifier.py`
- `scripts/dedupe_licitaciones.py`
- `scripts/fix_dates_adjudicaciones.py`
- `scripts/retrain.py`
- `scripts/rotate_api_keys.py`
- `scripts/seed_dev.py`
- `services/analytics/scoring_signals.py`
- `services/competitive/bajas.py`
- `services/competitive/mercado.py`
- `services/competitive/renovaciones.py`
- `services/contract_events.py`
- `services/deadline_reminders.py`
- `services/dedupe.py`
- `services/entity_resolution.py`
- `services/ml/scoring.py`
- `services/notifications.py`
- `services/resoluciones.py`
- `services/watchlist_rules.py`

## Ratchet `user_key` — identidad derivada del correo (D18, fase 1)

**67 ficheros** de producción usan `user_key` (lista congelada: 67; solo puede decrecer).

`scripts/check_user_key_ratchet.py` falla ante un fichero nuevo que la use. Llega a cero con T4, que migra a `user_id` con columna doble y lectura dual; hasta entonces cambiar de correo pierde los datos que cuelgan de esa clave. No cuenta `tests/` ni `db/alembic/versions/`.

## Motor de la suite de tests (ADR-018)

✅ la suite corre contra Postgres y el job es bloqueante

## Superficie de la API

**246 endpoints** expuestos.

<details><summary>Ver listado</summary>

| Método | Ruta |
|---|---|
| GET | `/` |
| GET | `/api/docs` |
| GET | `/api/openapi.json` |
| GET | `/api/redoc` |
| GET | `/api/v1/adjudicaciones` |
| GET | `/api/v1/admin/solicitudes-acceso` |
| GET | `/api/v1/admin/solicitudes-acceso/grants` |
| DELETE | `/api/v1/admin/solicitudes-acceso/grants/{grant_id}` |
| PATCH | `/api/v1/admin/solicitudes-acceso/{solicitud_id}` |
| GET | `/api/v1/admin/users` |
| GET | `/api/v1/admin/users/{user_id}` |
| PUT | `/api/v1/admin/users/{user_id}/admin` |
| POST | `/api/v1/admin/users/{user_id}/deactivate` |
| GET | `/api/v1/analytics/clusters` |
| GET | `/api/v1/analytics/compare-periods` |
| GET | `/api/v1/analytics/competitors` |
| GET | `/api/v1/analytics/forecast/retendering` |
| GET | `/api/v1/analytics/forecast/volume` |
| GET | `/api/v1/analytics/geography` |
| GET | `/api/v1/analytics/organos` |
| GET | `/api/v1/analytics/organos/{organo}` |
| GET | `/api/v1/analytics/overview` |
| GET | `/api/v1/analytics/pipeline` |
| GET | `/api/v1/analytics/proyectos-modulos` |
| GET | `/api/v1/analytics/quality` |
| GET | `/api/v1/analytics/resumen/desde-mi-ultima-visita` |
| GET | `/api/v1/analytics/resumen/hoy` |
| GET | `/api/v1/analytics/resumen/novedades` |
| GET | `/api/v1/analytics/resumen/sankey` |
| GET | `/api/v1/analytics/resumen/timeline` |
| GET | `/api/v1/analytics/resumen/top` |
| GET | `/api/v1/analytics/scoring` |
| GET | `/api/v1/analytics/source-freshness` |
| GET | `/api/v1/analytics/tecnologias` |
| GET | `/api/v1/analytics/tecnologias/detail` |
| GET | `/api/v1/analytics/trends` |
| GET | `/api/v1/analytics/trends-cpv` |
| GET | `/api/v1/analytics/utes` |
| POST | `/api/v1/ask` |
| GET | `/api/v1/ask/models` |
| POST | `/api/v1/auth/dev-login` |
| POST | `/api/v1/auth/login` |
| POST | `/api/v1/auth/logout` |
| POST | `/api/v1/auth/logout-all` |
| GET | `/api/v1/auth/me` |
| GET | `/api/v1/auth/oauth/google/authorize` |
| GET | `/api/v1/auth/oauth/google/callback` |
| GET | `/api/v1/auth/oauth/{provider}/authorize` |
| GET | `/api/v1/auth/oauth/{provider}/callback` |
| POST | `/api/v1/auth/password-reset/confirm` |
| POST | `/api/v1/auth/password-reset/request` |
| POST | `/api/v1/auth/register` |
| DELETE | `/api/v1/auth/totp` |
| POST | `/api/v1/auth/totp/confirm` |
| POST | `/api/v1/auth/totp/setup` |
| POST | `/api/v1/auth/totp/verify` |
| GET | `/api/v1/competitive/bajas` |
| GET | `/api/v1/competitive/bajas/referencia` |
| GET | `/api/v1/competitive/cuota` |
| GET | `/api/v1/competitive/empresas/{empresa_id}/adjudicaciones` |
| GET | `/api/v1/competitive/empresas/{empresa_id}/perfil` |
| GET | `/api/v1/competitive/empresas/{empresa_key}/contra-mi` |
| GET | `/api/v1/competitive/hhi` |
| GET | `/api/v1/competitive/partners` |
| GET | `/api/v1/competitive/renovaciones` |
| GET | `/api/v1/competitive/renovaciones/resumen` |
| GET | `/api/v1/competitive/watchlist` |
| POST | `/api/v1/competitive/watchlist` |
| DELETE | `/api/v1/competitive/watchlist/{empresa_id}` |
| GET | `/api/v1/cuentas` |
| POST | `/api/v1/cuentas` |
| DELETE | `/api/v1/cuentas/{cuenta_id}` |
| GET | `/api/v1/empresas` |
| GET | `/api/v1/empresas/reviews` |
| POST | `/api/v1/empresas/reviews/{review_id}` |
| GET | `/api/v1/empresas/stats` |
| GET | `/api/v1/empresas/{empresa_id}` |
| GET | `/api/v1/etiquetas` |
| POST | `/api/v1/etiquetas` |
| POST | `/api/v1/etiquetas/aplicar` |
| POST | `/api/v1/etiquetas/por-objeto` |
| POST | `/api/v1/etiquetas/quitar` |
| DELETE | `/api/v1/etiquetas/{etiqueta_id}` |
| GET | `/api/v1/eventos` |
| GET | `/api/v1/exports/calendario.ics` |
| GET | `/api/v1/exports/calendario/enlace` |
| GET | `/api/v1/exports/descargas/{job_id}` |
| GET | `/api/v1/exports/download` |
| GET | `/api/v1/feature-flags` |
| PUT | `/api/v1/feature-flags` |
| POST | `/api/v1/feedback` |
| POST | `/api/v1/feedback/asistente` |
| GET | `/api/v1/feedback/asistente/stats` |
| GET | `/api/v1/feedback/model-info` |
| GET | `/api/v1/feedback/queue` |
| GET | `/api/v1/feedback/stats` |
| GET | `/api/v1/health` |
| GET | `/api/v1/health/live` |
| GET | `/api/v1/health/ready` |
| GET | `/api/v1/jobs/{job_id}` |
| GET | `/api/v1/licitaciones` |
| POST | `/api/v1/licitaciones/bulk-get` |
| POST | `/api/v1/licitaciones/comparar` |
| GET | `/api/v1/licitaciones/cursor` |
| POST | `/api/v1/licitaciones/search` |
| GET | `/api/v1/licitaciones/stream` |
| GET | `/api/v1/licitaciones/{id_externo:path}` |
| GET | `/api/v1/licitaciones/{id_externo:path}/documentos` |
| POST | `/api/v1/licitaciones/{id_externo:path}/embeddings-async` |
| GET | `/api/v1/licitaciones/{id_externo:path}/explain` |
| GET | `/api/v1/licitaciones/{id_externo:path}/ficha-pliego` |
| GET | `/api/v1/licitaciones/{id_externo:path}/ficha-pliego/estado` |
| POST | `/api/v1/licitaciones/{id_externo:path}/ficha-pliego/extract` |
| POST | `/api/v1/licitaciones/{id_externo:path}/ficha-pliego/extract-async` |
| POST | `/api/v1/licitaciones/{id_externo:path}/guion` |
| POST | `/api/v1/licitaciones/{id_externo:path}/reportes` |
| POST | `/api/v1/licitaciones/{id_externo:path}/resumen` |
| GET | `/api/v1/licitaciones/{id_externo:path}/simulador` |
| GET | `/api/v1/licitaciones/{id_externo:path}/tech-scores` |
| GET | `/api/v1/licitaciones/{id_externo:path}/tecnologias` |
| GET | `/api/v1/licitaciones/{id_externo}` |
| GET | `/api/v1/licitaciones/{id_externo}/documentos/{documento_id}/paginas/{page_number}` |
| GET | `/api/v1/licitaciones/{id_externo}/similares` |
| GET | `/api/v1/licitaciones/{licitacion_id:path}/escenarios-precio` |
| GET | `/api/v1/licitaciones/{licitacion_id:path}/eventos` |
| GET | `/api/v1/licitaciones/{licitacion_id:path}/prediccion-baja` |
| DELETE | `/api/v1/me` |
| GET | `/api/v1/me/data` |
| GET | `/api/v1/me/keys` |
| POST | `/api/v1/me/keys` |
| POST | `/api/v1/me/keys/rotate` |
| GET | `/api/v1/me/notification-preferences` |
| PUT | `/api/v1/me/notification-preferences` |
| DELETE | `/api/v1/me/profile` |
| GET | `/api/v1/me/profile` |
| PUT | `/api/v1/me/profile` |
| GET | `/api/v1/me/sessions` |
| DELETE | `/api/v1/me/sessions/{session_id}` |
| GET | `/api/v1/meta/filters` |
| GET | `/api/v1/meta/last-extraction` |
| GET | `/api/v1/models/{name}` |
| POST | `/api/v1/models/{name}/activate/{version}` |
| GET | `/api/v1/models/{name}/versions` |
| GET | `/api/v1/notifications` |
| POST | `/api/v1/notifications/alerts/read` |
| POST | `/api/v1/notifications/read` |
| GET | `/api/v1/organizations` |
| POST | `/api/v1/organizations` |
| GET | `/api/v1/organizations/active` |
| GET | `/api/v1/organizations/gonogo` |
| PUT | `/api/v1/organizations/gonogo` |
| POST | `/api/v1/organizations/invitations/accept` |
| GET | `/api/v1/organizations/{organization_id}/capabilities` |
| PUT | `/api/v1/organizations/{organization_id}/capabilities` |
| POST | `/api/v1/organizations/{organization_id}/delete` |
| GET | `/api/v1/organizations/{organization_id}/deletion-preview` |
| GET | `/api/v1/organizations/{organization_id}/invitations` |
| DELETE | `/api/v1/organizations/{organization_id}/invitations/{invitation_id}` |
| POST | `/api/v1/organizations/{organization_id}/invitations/{invitation_id}/resend` |
| POST | `/api/v1/organizations/{organization_id}/leave` |
| GET | `/api/v1/organizations/{organization_id}/members` |
| POST | `/api/v1/organizations/{organization_id}/members` |
| PUT | `/api/v1/organizations/{organization_id}/members/{member_user_id}` |
| GET | `/api/v1/organizations/{organization_id}/nifs` |
| PUT | `/api/v1/organizations/{organization_id}/nifs` |
| GET | `/api/v1/organizations/{organization_id}/settings` |
| PUT | `/api/v1/organizations/{organization_id}/settings` |
| POST | `/api/v1/organizations/{organization_id}/transfer-ownership` |
| GET | `/api/v1/predicciones/calibracion` |
| GET | `/api/v1/publico/hubs` |
| GET | `/api/v1/publico/licitaciones` |
| GET | `/api/v1/publico/licitaciones/{ref}` |
| GET | `/api/v1/publico/sitemap/entradas` |
| GET | `/api/v1/publico/sitemap/resumen` |
| POST | `/api/v1/publico/solicitudes-acceso` |
| GET | `/api/v1/pursuits` |
| POST | `/api/v1/pursuits` |
| GET | `/api/v1/pursuits/actividad` |
| GET | `/api/v1/pursuits/agenda` |
| DELETE | `/api/v1/pursuits/attachments/{attachment_id}` |
| GET | `/api/v1/pursuits/attachments/{attachment_id}/descarga` |
| PUT | `/api/v1/pursuits/attachments/{attachment_id}/indexable` |
| GET | `/api/v1/pursuits/baja-propia` |
| GET | `/api/v1/pursuits/cartera` |
| GET | `/api/v1/pursuits/direccion` |
| GET | `/api/v1/pursuits/metrics` |
| GET | `/api/v1/pursuits/tasks/agenda` |
| GET | `/api/v1/pursuits/weights-proposal` |
| POST | `/api/v1/pursuits/weights-proposal/apply` |
| GET | `/api/v1/pursuits/{pursuit_id}` |
| PATCH | `/api/v1/pursuits/{pursuit_id}` |
| GET | `/api/v1/pursuits/{pursuit_id}/attachments` |
| POST | `/api/v1/pursuits/{pursuit_id}/attachments` |
| POST | `/api/v1/pursuits/{pursuit_id}/attachments/{attachment_id}/enlace` |
| GET | `/api/v1/pursuits/{pursuit_id}/checklist` |
| GET | `/api/v1/pursuits/{pursuit_id}/comments` |
| POST | `/api/v1/pursuits/{pursuit_id}/comments` |
| DELETE | `/api/v1/pursuits/{pursuit_id}/comments/{comment_id}` |
| GET | `/api/v1/pursuits/{pursuit_id}/ficha.pdf` |
| PUT | `/api/v1/pursuits/{pursuit_id}/gonogo` |
| GET | `/api/v1/pursuits/{pursuit_id}/kit` |
| POST | `/api/v1/pursuits/{pursuit_id}/kit` |
| GET | `/api/v1/pursuits/{pursuit_id}/tasks` |
| POST | `/api/v1/pursuits/{pursuit_id}/tasks` |
| PATCH | `/api/v1/pursuits/{pursuit_id}/tasks/{task_id}` |
| GET | `/api/v1/radar/dismissals` |
| POST | `/api/v1/radar/dismissals` |
| DELETE | `/api/v1/radar/dismissals/{id_externo:path}` |
| GET | `/api/v1/resoluciones` |
| GET | `/api/v1/saved-filters` |
| POST | `/api/v1/saved-filters` |
| DELETE | `/api/v1/saved-filters/{filter_id}` |
| GET | `/api/v1/search/global` |
| POST | `/api/v1/search/semantic` |
| GET | `/api/v1/security/audit/verify` |
| POST | `/api/v1/security/client-error` |
| GET | `/api/v1/security/client-errors` |
| POST | `/api/v1/security/csp-report` |
| POST | `/api/v1/security/leaked-key` |
| GET | `/api/v1/tecnologias` |
| GET | `/api/v1/tecnologias/impacto` |
| PUT | `/api/v1/tecnologias/keywords` |
| GET | `/api/v1/watchlist/feed.xml` |
| GET | `/api/v1/watchlist/items` |
| POST | `/api/v1/watchlist/items` |
| DELETE | `/api/v1/watchlist/items/{id_externo:path}` |
| PUT | `/api/v1/watchlist/items/{id_externo:path}` |
| GET | `/api/v1/watchlist/rules` |
| POST | `/api/v1/watchlist/rules` |
| GET | `/api/v1/watchlist/rules/baja` |
| POST | `/api/v1/watchlist/rules/preview` |
| DELETE | `/api/v1/watchlist/rules/{rule_id}` |
| PUT | `/api/v1/watchlist/rules/{rule_id}` |
| GET | `/api/v1/watchlist/rules/{rule_id}/matches` |
| GET | `/api/v1/webhooks` |
| POST | `/api/v1/webhooks` |
| GET | `/api/v1/webhooks/event-types` |
| GET | `/api/v1/webhooks/global` |
| DELETE | `/api/v1/webhooks/{webhook_id}` |
| GET | `/api/v1/webhooks/{webhook_id}` |
| PATCH | `/api/v1/webhooks/{webhook_id}` |
| GET | `/api/v1/webhooks/{webhook_id}/deliveries` |
| POST | `/api/v1/webhooks/{webhook_id}/deliveries/{delivery_id}/redeliver` |
| POST | `/api/v1/webhooks/{webhook_id}/ping` |
| GET | `/docs/oauth2-redirect` |
| GET | `/metrics` |

</details>
