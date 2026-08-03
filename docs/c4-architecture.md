# Arquitectura C4 (Mermaid)

Diagramas C4 versionados según [c4model.com](https://c4model.com/). Tres
niveles: Contexto, Contenedores y Componentes.

> Renderiza en GitHub: los bloques ` ```mermaid ` se muestran nativos.

## C1 — Contexto

```mermaid
%%{init: {'theme': 'neutral'}}%%
C4Context
    title TenderFlow — Contexto

    Person(user, "Analista comercial", "Equipo SAP que busca licitaciones del sector público")
    Person(admin, "Administrador", "Gestiona usuarios, modelos y configuración")

    System(licitaciones, "TenderFlow", "Detecta, analiza y alerta sobre licitaciones del sector público")

    System_Ext(fuentes, "Fuentes de contratación (PLACSP, PSCP, TACRC, TED)", "CODICE/UBL + Atom, vía scraper/connectors (ADR-009)")
    System_Ext(oauth, "Google OAuth", "Identidad federada")
    System_Ext(llm, "Proveedor LLM (NVIDIA NIM / OpenAI / Anthropic)", "Síntesis RAG para /api/v1/ask")
    System_Ext(otlp, "OTLP collector", "Trazas + métricas")
    System_Ext(slack, "Slack / Email", "Canal de alertas")

    Rel(user, licitaciones, "Consulta el frontend web, pregunta al asistente, exporta informes")
    Rel(admin, licitaciones, "Administra modelos, flags y usuarios")
    Rel(licitaciones, fuentes, "Descarga bulk + feeds en vivo (cada 4h)", "HTTPS")
    Rel(licitaciones, oauth, "Login federado")
    Rel(licitaciones, llm, "Genera respuestas del asistente RAG", "HTTPS, con presupuesto/circuit-breaker")
    Rel(licitaciones, otlp, "Tracing/metrics", "OTLP/HTTP")
    Rel(licitaciones, slack, "Alertas y digestos", "Webhook")
```

## C2 — Contenedores

```mermaid
%%{init: {'theme': 'neutral'}}%%
C4Container
    title TenderFlow — Contenedores

    Person(user, "Analista comercial")

    System_Boundary(s1, "TenderFlow") {
        Container(web, "Web frontend", "Next.js 16", "UI analítica y exploración")
        Container(api, "API REST", "FastAPI", "API pública v1 con auth por API-Key, incl. /ask (RAG)")
        Container(scraper, "Scraper", "Python", "connectors/: PLACSP bulk+Atom, PSCP, TACRC, TED")
        Container(sched, "Scheduler", "APScheduler", "KPI/aggregates precompute, drift, retrain, alertas")
        ContainerDb(db, "Postgres / Supabase", "Database", "Datos operacionales (ADR-016); motor único también en dev/CI (ADR-018/ADR-021)")
        ContainerDb(duckdb, "DuckDB (in-mem)", "Engine", "Queries OLAP sobre attach de la BD operacional")
        ContainerDb(parquet, "Parquet snapshots", "FS", "Materializaciones históricas")
        Container(models, "Model registry + artefactos", "joblib", "Versiones, métricas, drift")
    }

    System_Ext(fuentes, "Fuentes de contratación")
    System_Ext(llm, "Proveedor LLM")
    System_Ext(otlp, "OTLP")

    Rel(user, web, "HTTPS")
    Rel(user, api, "HTTPS + X-API-Key")
    Rel(web, api, "Consume API REST")
    Rel(api, db, "SQL (psycopg3)")
    Rel(api, llm, "Síntesis RAG para /ask", "HTTPS")
    Rel(scraper, fuentes, "HTTPS")
    Rel(scraper, db, "INSERT/UPDATE (upsert idempotente)")
    Rel(sched, db, "Pre-compute KPI / agregados / drift")
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
        Component(routes_ask, "routes/ask.py", "Router", "/ask — RAG, streaming SSE")
        Component(services_lic, "services/licitaciones.py", "Service", "Reglas y agregaciones")
        Component(services_rag, "services/rag/*.py", "Service", "Chunking + construcción de contexto")
        Component(llm_client, "llm/client.py", "Client", "Cliente unificado + presupuesto (llm/budget.py)")
        Component(repos, "db/repositories/*.py", "Repo", "Persistencia SQL")
    }

    Rel(app, mw, "wraps")
    Rel(app, auth, "depends")
    Rel(app, routes_lic, "mount")
    Rel(app, routes_meta, "mount")
    Rel(app, routes_models, "mount")
    Rel(app, routes_webhooks, "mount")
    Rel(app, routes_ask, "mount")
    Rel(routes_lic, services_lic, "usa")
    Rel(services_lic, repos, "consulta")
    Rel(routes_ask, services_rag, "usa")
    Rel(services_rag, repos, "consulta contexto")
    Rel(routes_ask, llm_client, "usa")
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
