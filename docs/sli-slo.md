# SLI/SLO — Licitaciones SAP

Definición de los indicadores de nivel de servicio (SLI) y objetivos (SLO) del sistema.

---

## Resumen ejecutivo

| Servicio | SLO | Periodo de medición |
|----------|-----|---------------------|
| Disponibilidad del dashboard | ≥ 99% | 30 días |
| Frescura de datos | ≤ 36h sin scrape exitoso | 7 días |
| Latencia de carga del dashboard | P95 < 3 s | 7 días |
| Tasa de éxito del pipeline | ≥ 95% de runs | 30 días |
| Cobertura de datos (importe presente) | ≥ 80% | 30 días |
| Tiempo de respuesta API REST | P99 < 500 ms | 7 días |

---

## SLI/SLO detallados

### 1. Disponibilidad del dashboard

| Campo | Valor |
|-------|-------|
| **SLI** | `(tiempo_total - tiempo_inaccesible) / tiempo_total × 100` |
| **SLO** | ≥ 99% mensual |
| **Medición** | Healthcheck externo cada 5 minutos (ver `scheduler/healthcheck.py`) |
| **Alerta** | PagerDuty / email si baja de 99% en ventana de 1h |
| **Error budget** | 7.2 min/día, 3.6h/mes |

### 2. Frescura de datos

| Campo | Valor |
|-------|-------|
| **SLI** | Horas transcurridas desde el último `extraction_run` con `status=ok` |
| **SLO** | Último run exitoso hace ≤ 36h en cualquier momento |
| **Medición** | `SELECT MAX(ended_at) FROM extraction_runs WHERE status='ok'` |
| **Alerta** | Notificación si `NOW() - MAX(ended_at) > 36h` (ver `scheduler/anomaly_alerts.py`) |
| **Mitigación** | Re-ejecutar scraper manual o via `make scrape` |

### 3. Latencia de carga del dashboard

| Campo | Valor |
|-------|-------|
| **SLI** | Tiempo de respuesta HTTP P50 / P95 / P99 de la ruta principal Streamlit |
| **SLO** | P95 < 3 s en cargas con caché caliente |
| **Medición** | Prometheus + Grafana (ver `observability/prometheus.yml`) |
| **Alerta** | Si P95 > 5 s durante 5 minutos consecutivos |
| **Optimizaciones activas** | `@st.cache_resource`, `_load_raw` + `_enrich_dataframe` separados, paginación server-side |

### 4. Tasa de éxito del pipeline de scraping

| Campo | Valor |
|-------|-------|
| **SLI** | `COUNT(status='ok') / COUNT(*) × 100` en `extraction_runs` últimos 30d |
| **SLO** | ≥ 95% de runs exitosos |
| **Medición** | Dashboard "Calidad de Datos" → KPI "Éxito pipeline 30d" |
| **Alerta** | Si tasa cae por debajo de 90% en ventana deslizante de 7 días |
| **Mitigación** | Revisar DLQ en panel de Administración → reintentar fallos |

### 5. Cobertura de datos — importe presente

| Campo | Valor |
|-------|-------|
| **SLI** | `COUNT(importe IS NOT NULL) / COUNT(*) × 100` sobre licitaciones activas |
| **SLO** | ≥ 80% de licitaciones con importe presente |
| **Medición** | `dashboard/stats.calidad_dato()` → `pct_importe` |
| **Alerta** | Email automático si baja de 75% (ver `scheduler/anomaly_alerts.py`) |

### 6. Tiempo de respuesta API REST

| Campo | Valor |
|-------|-------|
| **SLI** | Latencia HTTP de `GET /api/v1/licitaciones` P99 |
| **SLO** | P99 < 500 ms con datasets de hasta 10.000 licitaciones |
| **Medición** | OpenTelemetry → Prometheus (ver `observability/tracing.py`) |
| **Alerta** | Si P99 > 1 s durante 5 minutos |

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
