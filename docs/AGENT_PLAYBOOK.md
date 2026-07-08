# Agent Playbook

Guía operativa completa para agentes trabajando en `licitaciones-sap`. Complementa [AGENTS.md](../AGENTS.md) (que es el doc breve siempre-en-contexto) con detalle accionable: mapa de paquetes, workflows típicos, patterns por área y glosario del dominio.

---

## 1. Mapa detallado de paquetes

| Paquete | Propósito | Entry / fachada | Typing strict | Docs relacionados |
|---|---|---|---|---|
| `config/` | Settings (pydantic-settings), keywords SAP, constantes PLACSP, secrets | `config/settings.py` | Sí | [ADR-004](adr/[[ADR-004-sqlite-turso-vs-postgres|ADR-004]]-sqlite-turso-vs-postgres.md) |
| `shared/` | auth_core, dto, geo (NUTS3→CCAA), i18n, schemas (pandera), signing (JWKS), types | `shared/dto.py`, `shared/schemas.py` | Sí | [SECURITY.md](SECURITY.md) |
| `services/` | Lógica de dominio pura: licitaciones, normalization, classification, clusters, analytics_engine (DuckDB), rate_limiting, investigador (FTS5) | `services/licitaciones.py` | Sí (core) | [ADR-007](adr/[[ADR-007-services-domain-layer|ADR-007]]-services-domain-layer.md), [ADR-005](adr/[[ADR-005-clustering-ctfidf-minibatch|ADR-005]]-clustering-ctfidf-minibatch.md) |
| `db/` | SQLite/Turso, upsert idempotente, alembic migraciones, repositorios | `db/database.py` (fachada) → `db/connection.py`, `db/schema.py`, `db/upsert.py`; repos en `db/repositories/` | Solo `db.database`, `db.users` | [database-schema.md](database-schema.md), [ADR-001](adr/[[ADR-001-sql-crudo-vs-orm|ADR-001]]-sql-crudo-vs-orm.md), [ADR-003](adr/[[ADR-003-migraciones-caseras-plus-alembic|ADR-003]]-migraciones-caseras-plus-alembic.md) |
| `api/` | FastAPI REST `/api/v1/*` con X-API-Key, ETag, rate limit, CORS, exception handlers | `api/app.py`; rutas en `api/routes/{health,licitaciones,search,exports,me,meta,feedback,webhooks,...}.py` | No (overrides activos) | [ADR-006](adr/[[ADR-006-etag-pdf-export-ratelimit-redis|ADR-006]]-etag-pdf-export-ratelimit-redis.md) |
| `web/` | Next.js 16 frontend: dashboard analítico, KPIs, búsqueda, administración | `web/src/app/` | — | — |
| `scraper/` | Pipeline PLACSP: descarga ZIP/ATOM, parser CODICE/UBL, circuit breaker, filtros keywords, clasificador ML | `scraper/pipeline.py`; ML en `scraper/ml_classifier.py`, `scraper/ml_pipeline.py` (SQL manual, S608 suppressed) | Selectivo | — |
| `scheduler/` | Jobs cron: `run_update` (scraper), `kpi_precompute`, `loop` | `scheduler/loop.py`, `scheduler/run_update.py` | Sí | — |
| `llm/` | Cliente y providers LLM (opcional) | `llm/client.py`, `llm/providers/` | — | — |
| `observability/` | structlog config, Prometheus metrics, healthcheck, dashboards Grafana | `observability/logging.py` | — | [sli-slo.md](sli-slo.md) |
| `tests/` | pytest con auto-marking, fixtures aisladas (tmp_db), markers unit/integration/e2e/property/load | `tests/conftest.py` | — | — |

---

## 2. Workflows

### 2.1 Añadir un endpoint a la API

1. **Define el contrato**: añade el DTO request/response en `shared/dto.py` (Pydantic v2).
2. **Repositorio**: si lee/escribe datos nuevos, añade método en `db/repositories/<entidad>.py` (patrón existente: ver `db/repositories/licitaciones.py`). Si requiere SQL nuevo, mantén upsert idempotente.
3. **Lógica de dominio**: añade función en `services/<dominio>.py`. No mezcles SQL directo en la ruta; pasa por el servicio.
4. **Ruta**: crea o edita el router en `api/routes/<recurso>.py`. Inyectá `Depends(get_api_key)` si requiere auth. Registralo en `api/app.py` (sección `include_router`).
5. **Errores**: si hay condiciones nuevas de error, registra el handler en `api/errors.py` (no lances HTTPException con strings sueltos).
6. **Tests**: crea `tests/test_<recurso>_api.py` con `fastapi.testclient.TestClient`. Si hace BD, usa fixture `tmp_db` de `conftest.py`. El marker se aplica solo si el nombre del archivo encaja con un token de `_INTEGRATION_TOKENS`.
7. **Documenta**: actualiza el docstring de módulo de `api/app.py` (lista de endpoints en la cabecera).
8. **Post-flight**: `/check` → `graphify update .`.

### 2.2 Añadir una página al frontend

1. **Nueva ruta**: crea directorio en `web/src/app/(dashboard)/<nombre>/page.tsx`.
2. **Componentes reutilizables**: van en `web/src/components/`. UI primitivos en `web/src/components/ui/`.
3. **Carga de datos**: usa los hooks de TanStack Query en `web/src/hooks/`. API client en `web/src/lib/api-client.ts`.
4. **Tests**: tests e2e en `web/src/test/` con Playwright.

### 2.3 Añadir un job al scraper

1. **Filtro keywords**: si filtra por tecnología nueva, añade lista en `config/keywords.py` (patrón: `SAP_KEYWORDS`, `TECHNOLOGY_KEYWORDS`).
2. **Pipeline**: extendé `scraper/pipeline.py` o crea módulo nuevo. Mantén el patrón: descarga → parse → filtrar → clasificar → upsert.
3. **Upsert**: usa `db.upsert` (idempotente). Si falla, va a DLQ automáticamente. Ver runbook [dlq-replay.md](runbooks/dlq-replay.md).
4. **Circuit breaker / reintentos**: usa los wrappers existentes en `scraper/` (no implementes uno nuevo).
5. **Tests integration**: `tests/test_<pipeline>_integration.py` (auto-marker `integration` si el nombre encaja).
6. **Schedule**: registrá en `scheduler/run_update.py` y si corresponde en `.github/workflows/scrape*.yml` (**requiere confirmación humana**).

### 2.4 Fix de bug

1. **Reproducir con test primero**: añadí test que falla con el bug actual (`tests/test_<area>_<bug>.py`). Marker apropiado.
2. **Localiza la causa**: `graphify query "<síntoma>"` o `graphify path "<entry>" "<componente>"`.
3. **Fix mínimo**: cambio puntual; no aproveches para refactor.
4. **Verifica**: el test añadido pasa, `/check` verde, no rompiste otros tests.
5. **Post-flight**: `graphify update .`.
6. **Commit**: convencional. Sin `--no-verify`.

### 2.5 Refactor / mover archivos

1. **Antes**: corre `/check` para tener una baseline verde.
2. **Mueve / renombra**.
3. **Actualiza imports**: usa Edit en cada caller (graphify path te dice cuáles).
4. **Post-flight obligatorio**: `graphify update . --force` (porque eliminás nodos viejos).
5. **Verifica**: `/check` verde + ningún `from <old-path>` en grep.
6. **ADR**: si cambiás boundaries entre paquetes (p.ej. mover lógica de `db/` a `services/`), abrí un ADR en `docs/adr/`.

---

## 3. Patterns por área

| Decisión | Regla |
|---|---|
| ¿SQL crudo o ORM? | SQL crudo con repositorios finos (ver [ADR-001](adr/[[ADR-001-sql-crudo-vs-orm|ADR-001]]-sql-crudo-vs-orm.md)). En `scraper/ml_*` se permite SQL manual (S608 ya suppressed). |
| ¿Cómo importar desde `db/`? | **Siempre** `from db.database import X` (fachada única). Nunca `from db.connection import ...` ni `from db.upsert import ...` directamente desde código fuera de `db/`. Así los importadores quedan aislados de la organización interna. Ver docstring de `db/database.py` para el catálogo completo de símbolos por submódulo. |
| ¿Servicio vs repositorio directo en la ruta? | Siempre vía servicio. La ruta solo orquesta auth, validación, serialización. |
| ¿Cache en frontend? | Invalidación cross-process vía `shared/cache_signal.py` para refrescar datos server-side tras cada scraping. |
| ¿Cómo añado settings? | Campo nuevo en `config/settings.py` con `Field(...)` + default seguro + entry en `.env.example`. Nunca leer `os.environ` directo. |
| ¿Cómo añado un test slow? | Nombrá el archivo con token `performance` o `load`, o marca explícito con `@pytest.mark.slow`. `make test` excluye `integration_e2e` por defecto. |
| ¿Cómo validar un DataFrame? | Schema `pandera` en `shared/schemas.py`. No `assert` manuales. |
| ¿Rate limit? | `services/rate_limiting.py` (SQLite) o `services/rate_limit_redis.py` (Redis, opcional). No reinventar. |
| ¿Auth en endpoint nuevo? | `Depends(get_api_key)` + scope si aplica (ver `api/routes/webhooks.py` como referencia). |

---

## 4. Glosario del dominio

| Término | Significado |
|---|---|
| **PLACSP** | Plataforma de Contratación del Sector Público (España) — fuente de las licitaciones. |
| **CODICE / UBL** | Formato XML estándar europeo en que PLACSP publica los anuncios. |
| **CPV** | Common Procurement Vocabulary — códigos UE para clasificar bienes/servicios licitados. `CPV_PREFIXES_TI` en `config/constants.py` filtra prefijos relacionados con tecnología. |
| **CCAA** | Comunidad Autónoma — mapeada desde NUTS3 vía `shared/geo.py`. |
| **NUTS3** | Nomenclatura europea de unidades territoriales nivel 3 (provincia ES). |
| **Licitación** | Anuncio de contratación pública (pre-info, anuncio, adjudicación, formalización). |
| **Adjudicación** | Decisión de a qué empresa se asigna la licitación. Tabla separada en BD. |
| **DLQ** | Dead Letter Queue — registros que el upsert no pudo procesar. Reintento manual con runbook [dlq-replay.md](runbooks/dlq-replay.md). |
| **KPI precompute** | Job batch que pre-calcula métricas para el dashboard (evita queries pesadas en runtime). Ver `scheduler/kpi_precompute.py`. |
| **Watchlist** | Suscripción de usuario a criterios (CPV, keyword, CCAA, importe mínimo) → email automático. |
| **FAISS** | Índice vectorial para similitud semántica entre licitaciones (sentence-transformers + faiss-cpu, opcional). |
| **FTS5** | Full-text search de SQLite, usado por `services/investigador/`. |
| **Concept drift** | Detección de cambios en distribución de keywords/labels — `scheduler/concept_drift.py`. |
| **ETag** | Header HTTP para cache de exports PDF (ver [ADR-006](adr/[[ADR-006-etag-pdf-export-ratelimit-redis|ADR-006]]-etag-pdf-export-ratelimit-redis.md)). |

---

## 5. Cuándo NO seguir este playbook

- El usuario pide explícitamente otra cosa.
- Hay un ADR posterior que contradice algo aquí (los ADRs son la fuente de verdad sobre decisiones arquitectónicas; este playbook describe el estado vigente).
- El código contradice este playbook **consistentemente**: probablemente el playbook está desactualizado → marcá el desajuste y proponé update.
