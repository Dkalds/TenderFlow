# Arquitectura C4 (Mermaid)

Diagramas C4 versionados según [c4model.com](https://c4model.com/). Tres
niveles: Contexto, Contenedores y Componentes.

> Renderiza en GitHub: los bloques ` ```mermaid ` se muestran nativos.

## C1 — Contexto

```mermaid
%%{init: {'theme': 'neutral'}}%%
C4Context
    title Licitaciones SAP — Contexto

    Person(user, "Analista comercial", "Equipo SAP que busca licitaciones del sector público")
    Person(admin, "Administrador", "Gestiona usuarios, modelos y configuración")

    System(licitaciones, "Licitaciones SAP", "Detecta, analiza y alerta sobre licitaciones SAP")

    System_Ext(plataforma, "Plataforma de Contratación del SP", "Fuente oficial CODICE + Atom")
    System_Ext(oauth, "Google OAuth", "Identidad federada")
    System_Ext(otlp, "OTLP collector", "Trazas + métricas")
    System_Ext(slack, "Slack / Email", "Canal de alertas")

    Rel(user, licitaciones, "Consulta el frontend web, exporta informes")
    Rel(admin, licitaciones, "Administra modelos, flags y usuarios")
    Rel(licitaciones, plataforma, "Descarga diaria CODICE + Atom live", "HTTPS")
    Rel(licitaciones, oauth, "Login federado")
    Rel(licitaciones, otlp, "Tracing/metrics", "OTLP/HTTP")
    Rel(licitaciones, slack, "Alertas y digestos", "Webhook")
```

## C2 — Contenedores

```mermaid
%%{init: {'theme': 'neutral'}}%%
C4Container
    title Licitaciones SAP — Contenedores

    Person(user, "Analista comercial")

    System_Boundary(s1, "Licitaciones SAP") {
        Container(web, "Web frontend", "Next.js", "UI analítica y exploración")
        Container(api, "API REST", "FastAPI", "API pública v1 con auth por API-Key")
        Container(scraper, "Scraper", "Python", "CODICE bulk + Atom live")
        Container(sched, "Scheduler", "APScheduler", "KPI precompute, drift, retrain, alertas")
        ContainerDb(db, "SQLite / Turso libSQL", "Database", "Datos operacionales")
        ContainerDb(duckdb, "DuckDB (in-mem)", "Engine", "Queries OLAP sobre attach SQLite")
        ContainerDb(parquet, "Parquet snapshots", "FS", "Materializaciones históricas")
        Container(models, "Model registry + artefactos", "joblib", "Versiones, métricas, drift")
    }

    System_Ext(plataforma, "Plataforma SP")
    System_Ext(otlp, "OTLP")

    Rel(user, web, "HTTPS")
    Rel(user, api, "HTTPS + X-API-Key")
    Rel(web, api, "Consume API REST")
    Rel(api, db, "SQL")
    Rel(scraper, plataforma, "HTTPS")
    Rel(scraper, db, "INSERT/UPDATE")
    Rel(sched, db, "Pre-compute KPI / drift")
    Rel(sched, duckdb, "Materialize Parquet")
    Rel(sched, models, "Re-entrena y publica versión")
    Rel(api, models, "Lee versión activa")
    Rel_R(api, otlp, "Traces")
```

## C3 — Componentes (API REST)

```mermaid
%%{init: {'theme': 'neutral'}}%%
C4Component
    title API REST — Componentes principales

    Container_Boundary(api, "FastAPI") {
        Component(app, "app.py", "FastAPI", "Composición de routers + middlewares")
        Component(mw, "middleware.py", "Starlette MW", "CSP/HSTS, rate-limit, cost, access log")
        Component(auth, "auth.py", "Depends", "X-API-Key + scopes")
        Component(routes_lic, "routes/licitaciones.py", "Router", "Listados, búsqueda, cursor")
        Component(routes_meta, "routes/meta.py", "Router", "Opciones de filtros")
        Component(routes_models, "routes/models.py", "Router", "/v1/models — registry")
        Component(routes_webhooks, "routes/webhooks.py", "Router", "Suscripciones de eventos")
        Component(services_lic, "services/licitaciones.py", "Service", "Reglas y agregaciones")
        Component(repos, "db/repositories/*.py", "Repo", "Persistencia SQL")
    }

    Rel(app, mw, "wraps")
    Rel(app, auth, "depends")
    Rel(app, routes_lic, "mount")
    Rel(app, routes_meta, "mount")
    Rel(app, routes_models, "mount")
    Rel(app, routes_webhooks, "mount")
    Rel(routes_lic, services_lic, "usa")
    Rel(services_lic, repos, "consulta")
```

## Capas lógicas

La codebase se organiza en capas con dependencias unidireccionales:

```
web/        ──► api/
api/        ──► services/ ──► db/ + shared/
scheduler/  ──► services/      (dominio)    (persistencia + utilidades)
```

* `services/` contiene lógica de dominio pura (normalización,
  clasificación, threshold tuning, rate-limit). Sin dependencias UI.
  Ver [[ADR-007-services-domain-layer|ADR-007]].
* `shared/` aloja helpers transversales (auth core, signing, i18n,
  geo, schemas Pandera).
* `web/` consume la API REST y no accede a `services/` o `db/` directamente.

## Notas de mantenimiento

* Actualizar cuando se añada un contenedor (e.g. Redis, ClickHouse).
* Re-renderizar tras cambios estructurales mayores.
* Los componentes opcionales (Sentry, OpenTelemetry, DuckDB) se omiten
  para mantener legibilidad — documentados en ADRs separados.
