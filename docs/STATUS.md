---
tags: [status, generado]
---

# Estado del proyecto (derivado del código)

<!-- generado por scripts/gen_status.py — no editar a mano -->

Generado: 2026-08-28

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
| `anomaly_checks` | pipeline | CANONICAL_STEPS[anomaly_checks] |
| `drift_report` | pipeline | CANONICAL_STEPS[drift_checks] |

**12 jobs, todos con plano verificado.**

## Ratchet TID251 — acceso directo a BD fuera de repositories

**32 archivos** en whitelist (solo puede decrecer).

- `api/routes/empresas.py`
- `api/routes/eventos.py`
- `api/routes/exports.py`
- `api/routes/watchlist_rules.py`
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

## Motor de la suite de tests (ADR-018)

✅ la suite corre contra Postgres y el job es bloqueante

## Superficie de la API

**163 endpoints** expuestos.

<details><summary>Ver listado</summary>

| Método | Ruta |
|---|---|
| GET | `/` |
| GET | `/api/docs` |
| GET | `/api/openapi.json` |
| GET | `/api/redoc` |
| GET | `/api/v1/adjudicaciones` |
| GET | `/api/v1/admin/solicitudes-acceso` |
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
| GET | `/api/v1/competitive/hhi` |
| GET | `/api/v1/competitive/renovaciones` |
| GET | `/api/v1/competitive/renovaciones/resumen` |
| GET | `/api/v1/competitive/watchlist` |
| POST | `/api/v1/competitive/watchlist` |
| DELETE | `/api/v1/competitive/watchlist/{empresa_id}` |
| GET | `/api/v1/empresas` |
| GET | `/api/v1/empresas/reviews` |
| POST | `/api/v1/empresas/reviews/{review_id}` |
| GET | `/api/v1/empresas/stats` |
| GET | `/api/v1/empresas/{empresa_id}` |
| GET | `/api/v1/eventos` |
| POST | `/api/v1/exports` |
| GET | `/api/v1/exports/calendario.ics` |
| GET | `/api/v1/exports/download` |
| DELETE | `/api/v1/exports/{job_id}` |
| GET | `/api/v1/exports/{job_id}` |
| GET | `/api/v1/feature-flags` |
| PUT | `/api/v1/feature-flags` |
| POST | `/api/v1/feedback` |
| GET | `/api/v1/feedback/model-info` |
| GET | `/api/v1/feedback/queue` |
| GET | `/api/v1/feedback/stats` |
| GET | `/api/v1/health` |
| GET | `/api/v1/health/live` |
| GET | `/api/v1/health/ready` |
| GET | `/api/v1/licitaciones` |
| POST | `/api/v1/licitaciones/bulk-get` |
| GET | `/api/v1/licitaciones/cursor` |
| POST | `/api/v1/licitaciones/search` |
| GET | `/api/v1/licitaciones/stream` |
| GET | `/api/v1/licitaciones/{id_externo:path}` |
| GET | `/api/v1/licitaciones/{id_externo:path}/documentos` |
| GET | `/api/v1/licitaciones/{id_externo:path}/explain` |
| GET | `/api/v1/licitaciones/{id_externo:path}/ficha-pliego` |
| POST | `/api/v1/licitaciones/{id_externo:path}/ficha-pliego/extract` |
| POST | `/api/v1/licitaciones/{id_externo:path}/resumen` |
| GET | `/api/v1/licitaciones/{id_externo:path}/tech-scores` |
| GET | `/api/v1/licitaciones/{id_externo:path}/tecnologias` |
| GET | `/api/v1/licitaciones/{id_externo}` |
| GET | `/api/v1/licitaciones/{licitacion_id:path}/escenarios-precio` |
| GET | `/api/v1/licitaciones/{licitacion_id:path}/eventos` |
| GET | `/api/v1/licitaciones/{licitacion_id:path}/prediccion-baja` |
| DELETE | `/api/v1/me` |
| GET | `/api/v1/me/data` |
| GET | `/api/v1/me/keys` |
| POST | `/api/v1/me/keys/rotate` |
| DELETE | `/api/v1/me/profile` |
| GET | `/api/v1/me/profile` |
| PUT | `/api/v1/me/profile` |
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
| GET | `/api/v1/organizations/{organization_id}/members` |
| POST | `/api/v1/organizations/{organization_id}/members` |
| PUT | `/api/v1/organizations/{organization_id}/members/{member_user_id}` |
| GET | `/api/v1/predicciones/calibracion` |
| GET | `/api/v1/publico/hubs` |
| GET | `/api/v1/publico/licitaciones` |
| GET | `/api/v1/publico/licitaciones/{ref}` |
| GET | `/api/v1/publico/sitemap/entradas` |
| GET | `/api/v1/publico/sitemap/resumen` |
| POST | `/api/v1/publico/solicitudes-acceso` |
| GET | `/api/v1/pursuits` |
| POST | `/api/v1/pursuits` |
| GET | `/api/v1/pursuits/agenda` |
| GET | `/api/v1/pursuits/metrics` |
| GET | `/api/v1/pursuits/{pursuit_id}` |
| PATCH | `/api/v1/pursuits/{pursuit_id}` |
| GET | `/api/v1/radar/dismissals` |
| POST | `/api/v1/radar/dismissals` |
| DELETE | `/api/v1/radar/dismissals/{id_externo:path}` |
| GET | `/api/v1/resoluciones` |
| GET | `/api/v1/saved-filters` |
| POST | `/api/v1/saved-filters` |
| DELETE | `/api/v1/saved-filters/{filter_id}` |
| POST | `/api/v1/search/semantic` |
| GET | `/api/v1/security/audit/verify` |
| POST | `/api/v1/security/client-error` |
| POST | `/api/v1/security/csp-report` |
| POST | `/api/v1/security/leaked-key` |
| GET | `/api/v1/watchlist/feed.xml` |
| GET | `/api/v1/watchlist/items` |
| POST | `/api/v1/watchlist/items` |
| DELETE | `/api/v1/watchlist/items/{id_externo:path}` |
| GET | `/api/v1/watchlist/rules` |
| POST | `/api/v1/watchlist/rules` |
| POST | `/api/v1/watchlist/rules/preview` |
| DELETE | `/api/v1/watchlist/rules/{rule_id}` |
| PUT | `/api/v1/watchlist/rules/{rule_id}` |
| GET | `/api/v1/watchlist/rules/{rule_id}/matches` |
| GET | `/api/v1/webhooks` |
| POST | `/api/v1/webhooks` |
| GET | `/api/v1/webhooks/event-types` |
| DELETE | `/api/v1/webhooks/{webhook_id}` |
| GET | `/api/v1/webhooks/{webhook_id}` |
| PATCH | `/api/v1/webhooks/{webhook_id}` |
| GET | `/api/v1/webhooks/{webhook_id}/deliveries` |
| POST | `/api/v1/webhooks/{webhook_id}/ping` |
| GET | `/docs/oauth2-redirect` |
| GET | `/metrics` |

</details>
