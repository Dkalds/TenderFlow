---
rfc: 060
title: Añadir dashboard como scrape target de Prometheus
issue: https://github.com/Dkalds/Licitaciones_sap_SP/issues/60
author: agent:architect
date: 2026-05-24
status: approved
---

## Contexto

Prometheus solo scrapea `scheduler:9091` y `api:8080`. El dashboard (Streamlit en puerto 8501) registra métricas in-process via `observability.runtime_metrics` (FAISS rebuild, etc.) pero no expone un endpoint `/metrics` HTTP, por lo que esas métricas se pierden.

Además, `docker-compose.yml` L158 usa `service_started` para la dependencia de prometheus→scheduler, cuando debería usar `service_healthy` para consistencia con el resto del compose.

## Decisión

1. **Añadir un servidor de métricas al dashboard**: En `dashboard/bootstrap.py`, arrancar `prometheus_client.start_http_server` en un puerto secundario (9092) al inicio del proceso. Esto expone las métricas del registry por defecto sin interferir con Streamlit (puerto 8501).

2. **Añadir scrape target en `observability/prometheus.yml`**: Nuevo job `licitaciones-dashboard` apuntando a `dashboard:9092`.

3. **Exponer puerto 9092 en `docker-compose.yml`**: Añadir el puerto al servicio dashboard (solo interno, sin bind al host).

4. **Corregir `service_started` → `service_healthy`** en la dependencia prometheus→scheduler.

**Qué NO se hace**: No se añaden métricas nuevas; solo se exponen las ya registradas por `runtime_metrics`.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Exponer métricas en el mismo puerto 8501 via middleware Streamlit | Un solo puerto | Streamlit no soporta middleware ASGI custom fácilmente | Complejidad innecesaria |
| Usar textfile collector como el scheduler | Sin puerto extra | Requiere volumen compartido con prometheus, más complejo | Overkill para in-process metrics |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Afecta `dashboard/bootstrap.py` (strict) | Mantener tipos explícitos |
| §3.2 Upsert idempotente | Ninguno | — |
| §3.3 Migraciones append-only | Ninguno | — |
| §3.4 Auto-marking tests | Ninguno | — |
| §3.5 Pydantic v2 DTOs | Ninguno | — |
| §3.6 HMAC/argon2 auth | Ninguno | — |

## Plan de implementación

1. Editar `dashboard/bootstrap.py` — añadir `start_metrics_server()` con `prometheus_client.start_http_server(9092)` protegido por try/except ImportError
2. Editar `observability/prometheus.yml` — añadir job `licitaciones-dashboard`
3. Editar `docker-compose.yml` — exponer puerto 9092 en servicio dashboard + fix `service_started` → `service_healthy`
4. Añadir test unitario para validar que la función de métricas existe y es callable

**Archivos de partida**: `dashboard/bootstrap.py`, `observability/prometheus.yml`, `docker-compose.yml`
**Riesgo estimado**: bajo
**Tiempo estimado**: 1 hora

## Acceptance criteria

- [x] `observability/prometheus.yml` contiene job `licitaciones-dashboard` con target `dashboard:9092`
- [x] `dashboard/bootstrap.py` arranca servidor de métricas en puerto 9092
- [x] `docker-compose.yml` expone puerto 9092 y usa `service_healthy` para scheduler
- [x] `make lint && make typecheck && make test-unit` pasan en verde
- [x] diff-cover ≥ 80% en líneas nuevas

## Notas de review

2026-05-24T00:00Z agent:reviewer — RFC aprobado. Cambio de bajo riesgo, solo infra/config + una función trivial en bootstrap. No afecta invariantes core.
