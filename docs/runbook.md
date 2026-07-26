# Runbook operativo

Punto de entrada único para operación, on-call y respuesta a incidentes.
Los procedimientos detallados viven en `docs/runbooks/`.

## Resumen de servicios

| Servicio    | Proceso/Container         | Health                | Logs                       |
| ----------- | ------------------------- | --------------------- | -------------------------- |
| API REST    | `licitaciones-api`        | `GET /api/v1/health`  | `docker logs api`          |
| Web frontend | `licitaciones-web`       | `GET /`               | `docker logs licitaciones-web` |
| Scheduler    | `licitaciones-scheduler` | exit-code & metrics   | `docker logs licitaciones-scheduler` |
| Scraper      | cron daily / manual      | `scheduler/healthcheck.py` | `docker logs licitaciones-scheduler` |
| DB SQLite   | volumen `data/`           | `python scripts/doctor.py` | `data/backfill.log`   |

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

### Reiniciar la API en producción
```bash
docker compose restart api
# Verificar:
curl -fsS http://localhost:8080/api/v1/health/ready
```

### Forzar re-cómputo de KPIs
```bash
docker compose exec scheduler python -m scheduler.kpi_precompute --force
```

### Activar/Desactivar una versión de modelo
```bash
curl -fsS -X POST -H "X-API-Key: $API_KEY" \
  http://localhost:8080/api/v1/models/sap_classifier/activate/3
```

### Comprobar drift del clasificador
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
* F7: `scripts/verify_audit_chain.py` valida la cadena de hashes del
  `audit_log` (SHA-256 encadenado con genesis).
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
python scripts/verify_audit_chain.py --db-path data/licitaciones.db
# Salida esperada: "0 filas corruptas"; exit-code 0
```

### Coverage por módulo bajo umbrales
```bash
pytest --cov --cov-report=json
python scripts/check_coverage_per_module.py
# Imprime tabla por prefijo; exit-code = nº de módulos por debajo del umbral
```
