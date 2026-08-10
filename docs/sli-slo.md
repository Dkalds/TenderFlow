# SLI/SLO — TenderFlow

Definición de los indicadores de nivel de servicio (SLI) y objetivos (SLO) del sistema.

---

## Resumen ejecutivo

| Servicio | SLO | Periodo | Medido por |
|----------|-----|---------|------------|
| Disponibilidad del frontend web | ≥ 99% | 30 días | `up{service="api"}` (Prometheus) |
| Frescura de datos | ≤ 36h sin scrape exitoso | 7 días | `scheduler/healthcheck.py` (cada 6h) |
| Latencia de carga del frontend web | P95 < 3 s | 7 días | ⚠️ **sin medición** — ver nota |
| Tasa de éxito del pipeline | ≥ 95% de runs | 30 días | `extraction_runs` vía healthcheck |
| Cobertura de datos (importe presente) | ≥ 80% | 30 días | `extraction_runs` vía healthcheck |
| Tiempo de respuesta API REST | P99 < 500 ms | 7 días | `http_request_duration_seconds` (Prometheus) |

### Nota sobre la medición real (2026-07-26)

Hasta esta fecha **cinco de los seis SLOs no tenían medición alguna**: el
código expone `/metrics` desde siempre, pero el único Prometheus definido
vivía en `docker-compose.yml` apuntando a hostnames de compose local
(`api:8080`, `scheduler:9091`). En producción nadie scrapeaba nada, así que
el error budget no era computable y las reglas de `observability/alert_rules.yml`
no se evaluaban.

Con el despliegue de Prometheus + Grafana en Render (ADR-019) pasan a medirse
los SLOs de disponibilidad y de latencia de API. Quedan dos matices:

- **Latencia del frontend web**: el frontend se sirve fuera de este
  despliegue, así que Prometheus no lo ve. Requiere RUM (Web Vitals desde el
  navegador) o un probe sintético; hasta entonces el SLO no es medible y está
  marcado como tal en vez de fingir cobertura.
- **Planos efímeros** (scraper, ML y pliegos en GitHub Actions): no son
  scrapeables — el proceso muere al terminar el job y exponer un Pushgateway
  público sería superficie de ataque sin autenticación. Siguen reportando por
  la tabla `ops_events`, que lee `scheduler/healthcheck.py`. Ese canal estaba
  **roto desde el cutover a Postgres** (escribía con `libsql` a un fichero
  local del runner) y se corrigió junto con este cambio.

---

## SLI/SLO detallados

### 1. Disponibilidad del frontend web

| Campo | Valor |
|-------|-------|
| **SLI** | `(tiempo_total - tiempo_inaccesible) / tiempo_total × 100` |
| **SLO** | ≥ 99% mensual |
| **Medición** | Chequeo sintético cada 15 min (`.github/workflows/smoke.yml`) + healthcheck cada 6 h (`healthcheck.yml` → `scheduler/healthcheck.py`) |
| **Alerta** | Email (`observability/alerts.py`) — no hay PagerDuty en este stack. El sondeo cada 15 min acota el tiempo de detección a ~7 min de media; con el cron de 6 h anterior eran ~3 h y este SLO no era computable |
| **Error budget** | 7.2 min/día, 3.6h/mes |

### 2. Frescura de datos

| Campo | Valor |
|-------|-------|
| **SLI** | Horas transcurridas desde el último `extraction_run` con `status=ok` |
| **SLO** | Último run exitoso hace ≤ 36h en cualquier momento |
| **Medición** | `SELECT MAX(ended_at) FROM extraction_runs WHERE status='ok'` |
| **Alerta** | Notificación si `NOW() - MAX(ended_at) > 36h` (ver `scheduler/anomaly_alerts.py`) |
| **Mitigación** | Re-ejecutar scraper manual o via `make scrape` |

### 3. Latencia de carga del frontend web

| Campo | Valor |
|-------|-------|
| **SLI** | Tiempo de respuesta HTTP P50 / P95 / P99 de la ruta principal del frontend web |
| **SLO** | P95 < 3 s en cargas con caché caliente |
| **Medición** | Prometheus + Grafana. Config de producción: `observability/prometheus.render.yml`, horneada en la imagen por `docker/Dockerfile.prometheus` (`prometheus.yml` es la de docker-compose local) |
| **Alerta** | **No implementada** — `observability/alert_rules.yml` no define ninguna regla de latencia HTTP; las 7 vigentes cubren presupuesto LLM, dedupe y pool de Postgres |
| **Optimizaciones activas** | Caché caliente, agregados server-side y paginación server-side |

### 4. Tasa de éxito del pipeline de scraping

| Campo | Valor |
|-------|-------|
| **SLI** | `COUNT(status='ok') / COUNT(*) × 100` en `extraction_runs` últimos 30d |
| **SLO** | ≥ 95% de runs exitosos |
| **Medición** | Panel "Calidad de Datos" → KPI "Éxito pipeline 30d" |
| **Alerta** | Si tasa cae por debajo de 90% en ventana deslizante de 7 días |
| **Mitigación** | Revisar DLQ en panel de Administración → reintentar fallos |

### 5. Cobertura de datos — importe presente

| Campo | Valor |
|-------|-------|
| **SLI** | `COUNT(importe IS NOT NULL) / COUNT(*) × 100` sobre licitaciones activas |
| **SLO** | ≥ 80% de licitaciones con importe presente |
| **Medición** | Query agregada sobre `licitaciones` para calcular `pct_importe` |
| **Alerta** | Email automático si baja de 75% (ver `scheduler/anomaly_alerts.py`) |

### 6. Tiempo de respuesta API REST

| Campo | Valor |
|-------|-------|
| **SLI** | Latencia HTTP de `GET /api/v1/licitaciones` P99 |
| **SLO** | P99 < 500 ms con datasets de hasta 10.000 licitaciones |
| **Medición** | Prometheus (`prometheus-fastapi-instrumentator`, ver `api/app.py`). El tracing OTLP de `observability/tracing.py` es opcional y opera en modo NoOp sin el extra `[tracing]` |
| **Alerta** | **No implementada** (ver SLO 3). Sí existe `PgWriteLatencyHigh` sobre la latencia de escritura a BD |

---

## Error budgets

| SLO | Periodo | Budget total | Budget/día |
|-----|---------|-------------|------------|
| Disponibilidad 99% | 30 días | 7.2 h/mes | 14.4 min/día |
| Frescura ≤36h | Continuo | 0 (hard limit) | — |
| Éxito pipeline 95% | 30 días | 1.5 runs fallidos/30 | — |

---

## Proceso de revisión

- **Cadencia**: Revisión mensual de SLOs durante los primeros 5 días del mes.
- **Responsable**: DevOps / Tech Lead.
- **Fuentes de datos**: Dashboard Grafana `observability/grafana/`, tabla `extraction_runs`, alertas `scheduler/anomaly_alerts.py`.
- **Acción correctiva**: Si un SLO se incumple 2 meses consecutivos, revisar las causas raíz y ajustar el objetivo o implementar mejoras de resiliencia.

---

## Instrumentación disponible

| Señal | Fuente |
|-------|--------|
| Métricas scraper | `observability/prometheus.py` → `data/metrics/scraper.prom` |
| Métricas sistema | `observability/metrics.py` → `kpi_snapshots` |
| Trazas distribuidas | `observability/tracing.py` → OTLP endpoint |
| Logs estructurados | `observability/logging.py` → structlog JSON |
| Alertas de anomalías | `scheduler/anomaly_alerts.py` → email |
| Healthcheck externo | `scheduler/healthcheck.py` |
