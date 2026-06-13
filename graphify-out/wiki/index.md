# Wiki — Navegación broad

Índice ligero del knowledge graph para orientarse rápido **sin leer los 146K de [GRAPH_REPORT.md](../GRAPH_REPORT.md)**.

> **Para preguntas específicas usá:**
> - `graphify query "<pregunta>"` — subgrafo focalizado
> - `graphify path "<A>" "<B>"` — relación entre dos símbolos
> - `graphify explain "<concepto>"` — concepto con vecindad
>
> Este índice complementa esos comandos: lo usás cuando todavía no sabés qué preguntar.

---

## Por paquete (entry points + comando sugerido)

| Paquete | Entry point | Para profundizar |
|---|---|---|
| `api/` | `api/app.py` (FastAPI factory) | `graphify explain "api/app.py"` |
| `dashboard/` | `dashboard/app.py` (Streamlit) | `graphify explain "dashboard/router.py"` |
| `services/` | `services/licitaciones.py` (core de dominio) | `graphify explain "services/licitaciones.py"` |
| `db/` | `db/database.py` (fachada) → `db/connection.py`, `db/schema.py`, `db/upsert.py` | `graphify explain "db/upsert.py"` |
| `scraper/` | `scraper/pipeline.py` | `graphify explain "scraper/pipeline.py"` |
| `scheduler/` | `scheduler/loop.py`, `scheduler/run_update.py` | `graphify explain "scheduler/run_update.py"` |
| `config/` | `config/settings.py` (pydantic-settings) | `graphify explain "config/settings.py"` |
| `shared/` | `shared/dto.py` (Pydantic v2), `shared/schemas.py` (pandera), `shared/auth_core.py` | `graphify explain "shared/dto.py"` |
| `observability/` | `observability/logging.py` (structlog), `observability/metrics.py` (Prometheus) | `graphify explain "observability/logging.py"` |
| `llm/` | `llm/client.py` | `graphify explain "llm/client.py"` |
| `tests/` | `tests/conftest.py` (auto-marking) | — |

---

## Por concepto del dominio

| Concepto | Comando sugerido |
|---|---|
| Cómo el scraper guarda en BD | `graphify path "scraper/pipeline.py" "db/upsert.py"` |
| Cómo el dashboard lee datos | `graphify path "dashboard/app.py" "db/repositories/licitaciones.py"` |
| Flujo auth en la API | `graphify explain "api/routes/security.py"` |
| Cómo se calculan los KPIs | `graphify explain "scheduler/kpi_precompute.py"` |
| Cómo funciona el upsert idempotente | `graphify explain "db/upsert.py"` |
| Clasificación ML de licitaciones | `graphify explain "scraper/ml_classifier.py"` |
| Búsqueda semántica | `graphify path "services/investigador" "dashboard/embeddings.py"` |
| Watchlist / alertas email | `graphify explain "services/watchlist"` |
| Rate limiting | `graphify path "api/middleware" "services/rate_limiting.py"` |
| Migraciones | `graphify explain "db/alembic"` |
| Health / readiness | `graphify explain "api/routes/health.py"` |
| DLQ | `graphify explain "db/upsert.py"` + ver runbook [dlq-replay](../../docs/runbooks/dlq-replay.md) |

---

## Por capa (C4 nivel 3)

Detalle visual en [docs/c4-architecture.md](../../docs/c4-architecture.md).

```
PLACSP (open data)
   │
   ▼
[scraper/]  pipeline → ml_classifier → filters
   │  (upsert idempotente)
   ▼
[db/]  database (facade) → connection / schema / upsert / repositories
   │
   ├──────────────────────┬─────────────────────┐
   ▼                      ▼                     ▼
[scheduler/]        [services/]            [api/]
 run_update          licitaciones           routes/*
 kpi_precompute      classification         middleware
 loop                clusters               errors
                     analytics_engine
                     investigador (FTS5)
                          │
                          ▼
                    [dashboard/]
                     pages / components / filters
                     embeddings + FAISS (opt)
                     theme / router
```

---

## Cuándo usar este wiki vs otros recursos

| Necesidad | Recurso |
|---|---|
| Empezar a trabajar en un área nueva | Este wiki + `/area <paquete>` |
| Pregunta concreta sobre relaciones | `graphify query/path/explain` (no este wiki) |
| Decisión arquitectónica | [docs/adr/](../../docs/adr/) |
| Workflow paso a paso (añadir endpoint, fix bug) | [docs/AGENT_PLAYBOOK.md](../../docs/AGENT_PLAYBOOK.md) |
| Lista exhaustiva de nodos/edges | [GRAPH_REPORT.md](../GRAPH_REPORT.md) (solo si lo anterior no alcanza) |

---

## Mantenimiento

Este wiki es **manual**. Actualizalo cuando:
- Aparece un paquete top-level nuevo.
- Cambia el entry point de un paquete.
- Aparece un concepto del dominio relevante que no está mapeado.

Para regenerar el graph: `graphify update .` o `/graph-refresh`.
