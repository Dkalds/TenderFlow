# Runbook operativo

Punto de entrada único para operación, on-call y respuesta a incidentes.
Los procedimientos detallados viven en `docs/runbooks/`.

## Resumen de servicios

Producción no corre sobre Docker: la API vive en Render, el frontend en Vercel y
la BD es Supabase Postgres ([[ADR-016-destino-persistencia-supabase|ADR-016]];
SQLite se retiró en [[ADR-021-retirada-sqlite|ADR-021]]). El scheduler no es un
servicio desplegado — son workflows de GitHub Actions
(`SCHEDULER_PLANE=actions`, [[ADR-012-plano-unico-orquestacion|ADR-012]]).

| Servicio | Dónde corre | Health | Logs |
| --- | --- | --- | --- |
| API REST | Render, blueprint `tenderflow-api` | `GET /api/v1/health` | Render → *Logs* |
| Web frontend | Vercel, proyecto `tenderflow` | `GET /` | Vercel → *Runtime Logs* |
| Scheduler / scraper | GitHub Actions — `scrape-daily.yml`, cada 4 h | `scheduler/healthcheck.py`; `healthcheck.yml` cada 6 h | `gh run list --workflow=<wf>.yml`, luego `gh run view <id> --log` |
| DB | Supabase Postgres | `python scripts/doctor.py` | Supabase → *Logs* |
| Prometheus | Render, blueprint `tenderflow-prometheus` (pserv) | — | Render → *Logs* |
| Grafana | Render, blueprint `tenderflow-grafana` | `GET /api/health` | Render → *Logs* |

> **El host real de la API es `https://tenderflow-jrtr.onrender.com`.**
> `tenderflow-api` es el nombre lógico del blueprint, no el hostname;
> `tenderflow-api.onrender.com` resuelve pero no responde. Verificado el
> 2026-08-28 contra la API de Render.

> **Un deploy verde no prueba que la migración de ese PR haya corrido.**
> `migrate.yml` es `workflow_dispatch` deliberadamente (migrar producción es una
> decisión explícita), mientras que la API se redespliega por su cuenta. El
> schema puede ir por detrás de `master`: comprobalo con
> `gh run list --workflow=migrate.yml` y leé el `alembic current` del step
> "Estado actual del schema".

**Desarrollo local.** `docker-compose.yml` levanta `tenderflow-api`,
`tenderflow-web`, `tenderflow-postgres`, `tenderflow-redis`,
`tenderflow-prometheus` y `tenderflow-grafana`; el scheduler solo con
`docker compose --profile scheduler up` (declara `SCHEDULER_PLANE=docker`). Ahí
sí valen `docker logs tenderflow-api` y los `docker compose` de más abajo.

## Playbooks (orden recomendado de consulta)

1. **Backup & restore** — [docs/runbooks/backup-restore.md](runbooks/backup-restore.md)
2. **DLQ replay**       — [docs/runbooks/dlq-replay.md](runbooks/dlq-replay.md)
3. **Rate-limit reset** — [docs/runbooks/rate-limit-reset.md](runbooks/rate-limit-reset.md)
4. **Model rollback**   — [docs/runbooks/model-rollback.md](runbooks/model-rollback.md)
5. **Disaster recovery**— [docs/runbooks/disaster-recovery.md](runbooks/disaster-recovery.md)
6. **Incidentes**       — [docs/runbooks/incident-playbooks.md](runbooks/incident-playbooks.md)

## SLOs vigentes

* API `p95 < 300 ms`, `p99 < 800 ms`, error-rate `< 0.5 %` (ver `docs/sli-slo.md`).
* Scheduler ejecuciones diarias `> 99 %` éxito mensual.
* Drift PSI `< 0.10` para `sap_classifier`; aviso a partir de 0.10, crítico ≥ 0.25.

## Rotaciones planificadas

* `SIGNING_KEYS_JSON`: rotar la clave activa cada 180 días; mantener la
  anterior en el mapa durante 30 días como grace period
  (`shared/signing.py`).
* API keys de cliente: rotación a demanda (`scripts/rotate_api_keys.py`).

## Procedimientos exprés

Salvo el primero, todos son comandos **locales** (`docker compose`, `localhost`).
En producción el equivalente de un `exec scheduler` es lanzar el workflow de
Actions correspondiente con `gh workflow run <wf>.yml`.

### Reiniciar la API en producción
No hay `docker compose` en producción: la API es un servicio de Render. En su
dashboard, *Manual Deploy* → *Restart service*. Verificar:
```bash
curl -fsS https://tenderflow-jrtr.onrender.com/api/v1/health
```

### Forzar re-cómputo de KPIs (local)
```bash
docker compose exec scheduler python -m scheduler.kpi_precompute --force
```

### Activar/Desactivar una versión de modelo
```bash
# Local; contra producción, sustituir el host por el de Render.
curl -fsS -X POST -H "X-API-Key: $API_KEY" \
  http://localhost:8080/api/v1/models/sap_classifier/activate/3
```

### Comprobar drift del clasificador (local)
```bash
docker compose exec scheduler python -c \
  "from scheduler.drift_monitor import run_once; print(run_once())"
```

## Escalado

* P1 (caída total / data loss): on-call → líder técnico.
* P2 (degradación SLO): canal #ops, investigar dentro de 30 min.
* P3 (alerta sostenida >24h sin impacto): backlog del siguiente sprint.

## Cambios recientes (mantenimiento)

* F0: pytest markers `unit|integration|e2e|property|load`. Ejecutar
  subconjuntos vía `make test-unit`, `make test-e2e`, etc.
* F1: clustering refactor (sklearn imports top-level, c-TF-IDF, stopwords
  externas en `shared/stopwords_es.txt`).
* F2: motor analítico DuckDB opcional en `db/analytics.py`.
* F3: `services/threshold_tuning.py` para tuning con coste asimétrico.
* F3: `scheduler/drift_monitor.py` orquesta detección + alertas.
* F4: `shared/signing.py` con rotación `kid`; backend Redis opcional en
  `services/rate_limit_redis.py`.
* F4: Trivy en `.github/workflows/security.yml` para imágenes Docker.
* F5: i18n en `shared/i18n.py` + `shared/i18n_es.json` / `shared/i18n_en.json`.
* F5: Sentry opt-in en `observability/sentry.py`.
* F5: dashboard Grafana RED en `observability/grafana/dashboards/api_red.json`.
* F6: diagramas C4 en `docs/c4-architecture.md`. [[ADR-005-clustering-ctfidf-minibatch|ADR-005]] documenta el
  refactor de clustering.
* F7: capa `services/` como dominio compartido (ver [[ADR-007-services-domain-layer|ADR-007]]).
  `services/normalization.py` y `services/classification.py` concentran
  la lógica reutilizable consumida por API y frontend web.
* F7: `scripts/verify_audit_chain.py` valida íntegramente la cadena de
  `audit_log`: continuidad, HMAC por registro y cabecera final firmada.
* F7: `scripts/check_coverage_per_module.py` aplica umbrales de coverage
  diferenciados por capa (scraper 75 %, services 70 %, web 40 %).
* F7: PKCE (RFC 7636) + validación de Google ID token en
  `shared/auth_core.py` (`generate_pkce_pair`, `verify_pkce`,
  `validate_google_id_token`).
* F7: CI con Bandit (`pyproject.toml [tool.bandit]`) y Trivy
  (escaneo CRITICAL/HIGH sobre la imagen Docker, allowlist en
  `.trivyignore`).

## Verificaciones de salud manuales

### Cadena de auditoría íntegra
```bash
python scripts/verify_audit_chain.py
# Salida esperada: "Estado: ÍNTEGRA"; exit-code 0
```

### Coverage por módulo bajo umbrales
```bash
pytest --cov --cov-report=json
python scripts/check_coverage_per_module.py
# Imprime tabla por prefijo; exit-code = nº de módulos por debajo del umbral
```
