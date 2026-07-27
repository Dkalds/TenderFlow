---
id: ADR-019
title: "Observabilidad desplegada: Prometheus y Grafana en Render"
status: accepted
date: 2026-07-26
deciders: "Daniel Kalitovics"
related:
  - "[[ADR-012-plano-unico-orquestacion]]"
  - "[[ADR-016-destino-persistencia-supabase]]"
tags: [adr, observability, slo]
---

# ADR-019 — Observabilidad desplegada: Prometheus y Grafana en Render

* **Estado:** Aceptado
* **Fecha:** 2026-07-26

## Contexto

`docs/sli-slo.md` definía seis SLOs con umbrales y alertas, y
`observability/alert_rules.yml` sus reglas. Ninguna de las dos cosas se
evaluaba: el único Prometheus del repositorio vivía en `docker-compose.yml`
bajo el perfil `monitoring`, con `observability/prometheus.yml` apuntando a
`api:8080` y `scheduler:9091` — hostnames que solo existen dentro de compose.

En producción, la API expone `/metrics` (vía `prometheus-fastapi-instrumentator`)
y nadie lo consulta. El resultado era **observabilidad declarada pero no
medida**: cinco de seis SLOs sin serie temporal, error budget no computable, y
un documento que daba sensación de cobertura sin tenerla. `configure_sentry()`
también era no-op porque `SENTRY_DSN` no estaba en `render.yaml`.

Había además una restricción estructural que hacía inviable el modelo *pull*:
el plan free de Render hiberna el servicio. Esa restricción ya no aplica.

## Decisión

**Prometheus y Grafana se despliegan como servicios propios en Render**, junto
a la API y en la misma región.

- `tenderflow-prometheus` es un **servicio privado** (`type: pserv`): no se
  expone a internet y solo lo alcanzan los servicios de la cuenta. Disco
  persistente de 10 GB, retención 30 días.
- `tenderflow-grafana` es un servicio web porque hay que abrirlo desde el
  navegador; trae su propia autenticación y `GF_USERS_ALLOW_SIGN_UP=false`.
- `observability/prometheus.render.yml` es la configuración de producción, con
  los nombres de servicio de Render como targets. `observability/prometheus.yml`
  se queda como la de compose local — son entornos distintos y forzar una sola
  config obligaría a plantillas.
- `SENTRY_DSN` se declara en `render.yaml` para que la captura de errores deje
  de ser no-op.

### Lo que deliberadamente NO se hace

**No se despliega un Pushgateway público** para los planos efímeros (scraper,
ML y pliegos en GitHub Actions). Un Pushgateway accesible desde internet es una
superficie de escritura sin autenticación sobre las métricas del sistema, y el
proyecto ya tiene un canal diseñado para eso: la tabla `ops_events`, que
persiste eventos de procesos efímeros y lee `scheduler/healthcheck.py` cada 6h.

Ese canal estaba **roto desde el cutover a Postgres**: `flush_events()` escribía
siempre con `libsql` contra un fichero SQLite local, de modo que en los runners
de GitHub Actions los eventos iban a un fichero que se descarta al terminar el
job, mientras el healthcheck los buscaba en Supabase. Como la función traga
todos los errores por diseño, el fallo era invisible. Se corrige en este mismo
cambio (`_flush_postgres`).

## Consecuencias

**Positivas:**
- Los SLOs de disponibilidad y latencia de API pasan a ser medibles, y las
  reglas de `alert_rules.yml` a evaluarse de verdad.
- Los tripwires de persistencia vuelven a tener señal tras meses sin ella.
- Los dashboards de `observability/grafana/dashboards/` se importan sin cambios.

**Negativas:**
- Dos servicios más que pagar y mantener (Prometheus y Grafana con disco).
- **La latencia del frontend web sigue sin medición.** El frontend se sirve
  fuera de este despliegue, así que Prometheus no lo ve; medirlo requiere RUM
  o un probe sintético. El SLO queda marcado como no medido en `sli-slo.md` en
  vez de fingir cobertura — que es el estado que este ADR viene a corregir.
- La configuración de los servicios de Render **no se ha podido verificar
  desplegando**: se entrega revisada pero sin ejecutar. El primer despliegue
  debe confirmar que Prometheus resuelve `tenderflow-api:8080`.
