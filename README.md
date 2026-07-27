# TenderFlow

Inteligencia de licitaciones del Sector Público español.

---

## Características principales

| Módulo | Descripción |
|--------|-------------|
| **Scraper multi-fuente** | Framework de conectores ([ADR-009](docs/adr/ADR-009-framework-conectores-multifuente.md)): PLACSP (ZIPs mensuales bulk + feed ATOM en vivo), PSCP y TACRC (activos en el cron diario) y TED (implementado, pendiente de cablear). Parser CODICE/UBL con resiliencia (circuit breaker, reintentos) |
| **Clasificación** | Filtrado por keywords + modelo ML TF-IDF + LogisticRegression entrenado sobre los propios datos |
| **Base de datos** | **Postgres/Supabase en producción** ([ADR-016](docs/adr/ADR-016-destino-persistencia-supabase.md), psycopg3 + pool gestionado). SQLite local como alternativa de desarrollo ([ADR-018](docs/adr/ADR-018-paridad-motor-tests-produccion.md); Turso retirado, [ADR-020](docs/adr/ADR-020-retirada-turso.md)). Upsert idempotente, historial de cambios, DLQ |
| **Web frontend** | Next.js 16 con dashboard analítico (KPIs, pipeline, competidores, tendencias), búsqueda y administración |
| **Asistente RAG (`/api/v1/ask`)** | Preguntas en lenguaje natural sobre licitaciones vía LLM (NVIDIA NIM/DeepSeek por defecto; OpenAI/Anthropic opcionales), streaming SSE, presupuesto/circuit-breaker de gasto |
| **Analítica competitiva** | Detección de bajas anómalas, análisis de mercado, renovaciones y riesgo de cambio de proveedor (`services/competitive/`) |
| **Alertas** | Emails automáticos por watchlist de usuario (CPV, keyword, CCAA, importe mínimo), alertas de competidores y de concept drift del modelo ML |
| **Observabilidad** | Structlog (JSON/consola), Prometheus metrics, healthcheck, tracing OTLP opcional, alertas por nivel de severidad, dashboards Grafana |
| **Autenticación** | Password con rate limiting + Google OAuth 2.0, HMAC-signed CSRF state, TOTP (2FA) |
| **Búsqueda** | Full-text nativo (FTS5 en SQLite / `tsvector`+GIN en Postgres, vía `db/search_backend.py`) + búsqueda semántica opcional con sentence-transformers |

---

## Arquitectura

```
┌───────────────────────────────┐       ┌──────────────────────────┐
│ Fuentes (multi-conector)      │──────▶│  scraper/connectors      │
│ - PLACSP: ZIPs + ATOM en vivo │       │  - descarga + parse      │
│ - PSCP, TACRC, TED            │       │  - filtro keywords       │
└───────────────────────────────┘       │  - clasificador ML       │
                                        └──────────┬───────────────┘
                                                   │  upsert idempotente
                                                   ▼
                              ┌────────────────────────────────────┐
                              │  Postgres / Supabase (producción)   │
                              │  SQLite local (desarrollo, ADR-018) │
                              │  (historial de cambios, DLQ)        │
                              └──────────┬───────────────────────────┘
                                         │
                     ┌───────────────────┼──────────────────┬──────────────┐
                     ▼                   ▼                  ▼              ▼
          ┌──────────────┐   ┌────────────────────┐  ┌──────────────┐ ┌────────────┐
          │ GitHub       │   │  API FastAPI ◀──▶   │  │ Alertas      │ │ LLM /ask   │
          │ Actions cron │   │  Next.js UI (KPIs)  │  │ email/SMTP   │ │ (RAG, SSE) │
          └──────────────┘   └────────────────────┘  └──────────────┘ └────────────┘
```

Diagramas C4 completos (contexto, contenedores, componentes) en
[docs/c4-architecture.md](docs/c4-architecture.md).

---

## Estructura del proyecto

```
tenderflow/
├── config/                       # Configuración modular
│   ├── settings.py               #   Variables de entorno (pydantic-settings)
│   ├── keywords.py               #   SAP_KEYWORDS, TECHNOLOGY_KEYWORDS
│   ├── constants.py              #   URLs PLACSP, CPV_PREFIXES_TI, campos histórico
│   └── secrets.py                #   Gestión segura de secretos
├── shared/                       # Utilidades cross-cutting (sin lógica de negocio)
│   ├── auth_core.py              #   Crypto de auth (argon2/bcrypt, HMAC, PKCE)
│   ├── dto.py                    #   DTOs Pydantic v2 (contrato API ↔ web)
│   ├── geo.py                    #   NUTS3 → CCAA
│   ├── i18n.py                   #   Internacionalización (es/en)
│   ├── schemas.py                #   Esquemas pandera para validación de DataFrames
│   ├── signing.py                #   Rotación de claves de firma (kid/JWKS)
│   ├── csrf.py                   #   HMAC-signed CSRF state
│   ├── ssrf.py                   #   Validación de URLs salientes (documentos, webhooks)
│   ├── cache_signal.py           #   Señal de invalidación scraper → frontend
│   └── ...                       #   cache, crypto, dates, export_safety, identity, password_policy
├── services/                     # Capa de dominio (lógica de negocio pura)
│   ├── licitaciones.py           #   Reglas y agregaciones de licitaciones
│   ├── normalization.py          #   Normalización de empresas y NIFs
│   ├── classification.py         #   Clasificación por CPV, módulos, tecnología
│   ├── clusters.py               #   Clustering de licitaciones
│   ├── analytics_engine.py       #   Motor analítico DuckDB
│   ├── rate_limiting.py          #   Rate limiting (SQLite backend)
│   ├── rate_limit_redis.py       #   Rate limiting (Redis backend, opcional)
│   ├── analytics/                #   Overview, pipeline, scoring, forecast, tendencias, geografía
│   ├── competitive/               #   Bajas anómalas, análisis de mercado, renovaciones
│   ├── investigador/             #   Motor de búsqueda FTS5/tsvector
│   ├── ml/                       #   Modelos de scoring/baja/retención, calibración, drift
│   ├── rag/                      #   Chunking + construcción de contexto para `/ask`
│   └── ...                       #   admin, auth, gdpr, health, security, watchlist
├── db/                           # Persistencia y acceso a datos
│   ├── connection.py             #   Pool de conexión (Postgres/psycopg3, SQLite local)
│   ├── database.py               #   Fachada principal (init, connect, upsert)
│   ├── search_backend.py         #   Abstracción FTS: FTS5 (SQLite) / tsvector+GIN (Postgres)
│   ├── upsert.py                 #   Upsert idempotente con historial
│   ├── migrations.py             #   Migraciones DDL caseras (legacy, v1–v32)
│   ├── repositories/             #   Patrón Repository (licitaciones, adjudicaciones, ...)
│   ├── alembic/                  #   Migraciones Alembic (sistema canónico, DDL versionadas)
│   ├── certs/                    #   CA de Supabase para `sslmode=verify-full`
│   ├── watchlist.py              #   Persistencia de watchlist
│   ├── dlq.py                    #   Dead Letter Queue
│   ├── rate_limits.py            #   Rate limiting persistente en BD
│   ├── model_registry.py         #   Registro de versiones de modelos ML
│   ├── feature_flags.py          #   Feature flags
│   ├── audit.py                  #   Log de auditoría (SHA-256 encadenado)
│   └── ...                       #   analytics, events, users, sessions, webhooks, totp
├── api/                          # API REST (FastAPI)
│   ├── app.py                    #   Composición de routers + middlewares
│   ├── auth.py                   #   Autenticación por X-API-Key + scopes
│   ├── middleware.py             #   CSP/HSTS, rate-limit, cost, access log
│   ├── errors.py                 #   Errores RFC 7807 (Problem Details)
│   └── routes/                   #   licitaciones, ask (RAG), analytics, competitive, search, ...
├── scraper/                      # Pipeline de extracción de datos
│   ├── pipeline.py               #   Orquestador principal (bulk + daily)
│   ├── connectors/                #   Framework multi-fuente (ADR-009): placsp, pscp, tacrc, ted
│   ├── bulk_downloader.py        #   Descarga ZIPs mensuales de PLACSP
│   ├── codice_parser.py          #   Parser ATOM/CODICE (formato UBL)
│   ├── atom_live.py              #   Feed ATOM en vivo (cada 4h)
│   ├── document_fetcher.py       #   Descarga de pliegos/documentos anexos
│   ├── filters.py                #   Detección de keywords por tecnología
│   ├── ml_classifier.py          #   Clasificador ML TF-IDF + LogisticRegression
│   ├── ml_training.py            #   Entrenamiento y re-cómputo de ml_proba
│   ├── ml_pipeline.py            #   Pipeline ML de extremo a extremo
│   └── resilience.py             #   Circuit breaker, reintentos, timeouts
├── scheduler/                    # Tareas programadas
│   ├── loop.py                   #   Bucle principal del scheduler (Docker)
│   ├── run_update.py             #   Entry point para cron / GitHub Actions
│   ├── jobs/                      #   Definición de jobs individuales
│   ├── kpi_precompute.py         #   Pre-cómputo de KPIs pesados
│   ├── aggregates_precompute.py  #   Pre-cómputo de agregados analíticos
│   ├── watchlist_alerts.py       #   Alertas por watchlist (batch optimizado)
│   ├── competitor_alerts.py      #   Alertas de competidores/renovaciones
│   ├── drift_monitor.py          #   Detección de concept drift + alertas
│   ├── anomaly_alerts.py         #   Alertas de anomalías (frescura, cobertura)
│   ├── healthcheck.py            #   Verificación de frescura de datos
│   ├── retention.py              #   Retención/purga de datos según política
│   └── dlq_retry.py              #   Reintento automático de DLQ
├── observability/                # Logging, métricas, trazas
│   ├── logging.py                #   Structlog (JSON/consola), redacción de secretos
│   ├── alerts.py                 #   Envío de alertas por email / nivel
│   ├── metrics.py                #   Métricas de sistema (kpi_snapshots)
│   ├── prometheus.py             #   Métricas Prometheus (textfile + HTTP)
│   ├── tracing.py                #   OpenTelemetry (OTLP, opcional)
│   ├── sentry.py                 #   Sentry (opt-in)
│   └── grafana/                  #   Dashboards Grafana (RED, SLO)
├── llm/                          # Integración con LLMs (opcional, endpoint /ask)
│   ├── client.py                 #   Cliente unificado
│   ├── budget.py                 #   Presupuesto/circuit-breaker de gasto
│   ├── prompts.py                #   Plantillas de prompts RAG
│   └── providers/                #   NVIDIA NIM (OpenAI-compatible), OpenAI, Anthropic
├── scripts/                      # Scripts de mantenimiento
│   ├── doctor.py                 #   Verificación de entorno
│   ├── backup_db.py              #   Backup de la BD (cifrado GPG/AES-256)
│   ├── retrain.py                #   Reentrenamiento del modelo ML
│   ├── rotate_api_keys.py        #   Rotación de API keys
│   ├── migrate_sqlite_to_pg.py   #   ETL de migración a Postgres/Supabase
│   ├── verify_pg_parity.py       #   Verificación de paridad tras el cutover
│   ├── check_frontend_invariants.py  # Integridad analítica del frontend (ADR-014)
│   └── ...                       #   dedupe, retention, coverage, eval_rag_generation
├── docs/                         # Documentación técnica
│   ├── adr/                      #   Architecture Decision Records (ADR-001..016)
│   ├── runbooks/                 #   Playbooks operativos (backup, DLQ, DR, migración, ...)
│   ├── c4-architecture.md        #   Diagramas C4 (Mermaid)
│   ├── database-schema.md        #   Esquema ER + tablas + queries
│   ├── api-design.md             #   Convenciones y contratos de la API REST
│   ├── testing.md                #   Auto-marking, fixtures, cobertura
│   ├── sli-slo.md                #   SLIs/SLOs del sistema
│   └── SECURITY.md               #   Prácticas de seguridad y rotación
├── tests/                        # Tests (unit, integration, e2e, property, load)
├── .github/workflows/            # CI/CD
│   ├── ci.yml                    #   Lint, tipos, tests, pre-commit, audit, docker build
│   ├── security.yml              #   Semgrep SAST + Trivy + rotation reminder
│   ├── scrape.yml                #   Bulk mensual (diario 06:00 UTC)
│   ├── scrape-daily.yml          #   Feed ATOM/conectores en vivo (cada 4h)
│   ├── healthcheck.yml           #   Healthcheck (cada 6h)
│   ├── train-model.yml           #   Entrenamiento programado del clasificador
│   └── ...                       #   backup, changelog, release, release-sdk
├── docker/                       # Dockerfiles (multi-stage) + entrypoints
│   ├── Dockerfile.api            #   Imagen de la API/scheduler
│   └── Dockerfile.web            #   Imagen del frontend Next.js
├── docker-compose.yml            # web + api + scheduler (+ profile monitoring opcional)
├── docker-compose.override.yml   # Overrides locales (no versionar cambios sensibles)
├── render.yaml                   # Despliegue declarativo en Render.com (alternativa a Docker propio)
└── data/                         # BD SQLite + modelos + métricas (gitignored)
```

---

## Instalación

### Instalación estándar

```bash
git clone https://github.com/Dkalds/TenderFlow.git
cd TenderFlow
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux / macOS
pip install -e .
```

### Con búsqueda semántica (opcional, ~2 GB adicionales por PyTorch)

```bash
pip install -e ".[ml]"
```

### Con Docker

```bash
docker compose up -d
```

La web estará disponible en http://localhost:3000 y la API en http://localhost:8080.
El scheduler ejecuta actualizaciones automáticamente en el mismo stack.

---

## Configuración

Copia `.env.example` a `.env` y rellena los valores (`cp .env.example .env`).
Extracto de las variables más relevantes para empezar:

```dotenv
# ── Entorno ─────────────────────────────────────────────
# Default: prod (fail-safe). Usar dev solo en local.
ENV=dev

# ── Base de datos (elige una opción) ────────────────────

# Opción A — SQLite local (por defecto, sin configuración adicional).
# Es una comodidad de desarrollo (ADR-018), no la referencia de producción.
# DB_PATH=data/licitaciones.db

# Opción B — Postgres / Supabase (ADR-016, producción) — PRECEDENCIA sobre SQLite.
# Usar el Supavisor session pooler (puerto 5432, IPv4). En prod/staging exigir
# sslmode=verify-full + DATABASE_SSL_ROOT_CERT (CA de Supabase).
DATABASE_URL=postgresql://<user>:<pass>@<host>:5432/<db>?sslmode=verify-full

# ── OAuth Google (opcional) ──────────────────────────────
GOOGLE_CLIENT_ID=<client-id>.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=<client-secret>
OAUTH_REDIRECT_URI=http://localhost:3000
OAUTH_ALLOWED_EMAILS=persona@empresa.com,otra@empresa.com
OAUTH_ALLOWED_DOMAINS=empresa.com
OAUTH_ADMIN_EMAILS=admin@empresa.com
# Clave independiente para firmar tokens CSRF (recomendado en producción):
# python -c "import secrets; print(secrets.token_hex(32))"
SIGNING_KEY=<clave-aleatoria-32-chars>

# ── Asistente RAG /api/v1/ask (opcional) ─────────────────
# Proveedor por defecto: NVIDIA NIM (API compatible con OpenAI, modelo deepseek).
# NVIDIA_API_KEY=nvapi-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# Alternativos: OPENAI_API_KEY, ANTHROPIC_API_KEY

# ── Alertas por email (opcional) ─────────────────────────
ALERT_EMAIL_TO=destino@ejemplo.com
ALERT_SMTP_USER=remitente@gmail.com
ALERT_SMTP_PASSWORD=<app-password-gmail>
```

`config/settings.py` declara muchas más variables (Redis, rate limiting,
TOTP/2FA, webhooks, auditoría, CORS, tracing OTLP, tuning de ML/anomalías) con
defaults seguros — consulta `.env.example` para la lista completa comentada.

> **Importante:** `.env` está en `.gitignore`. Nunca lo commitees.

---

## Uso

### 1. Primera carga histórica

```bash
python -m scheduler.run_update --backfill 2024 1
```

Descarga todos los meses desde enero 2024 hasta hoy.

### 2. Actualización incremental (últimos 3 meses)

```bash
python -m scheduler.run_update
```

Operación **idempotente**: usa upsert por `id_externo`. Ejecutarlo varias
veces no duplica registros.

### 3. Actualización ligera (feed ATOM en vivo)

```bash
python -m scheduler.run_update --daily
```

### 4. Entrenar el clasificador ML

```bash
python -m scraper.ml_classifier train
```

Requiere al menos 50 registros en la BD. El modelo se guarda en
`data/models/sap_classifier.pkl`.

---

## Despliegue

### Docker (autohospedado)

```bash
cp .env.example .env   # edita con tus credenciales
docker compose up -d
```

El `docker-compose.yml` levanta tres servicios principales que comparten el mismo
volumen de datos: `web` (`docker/Dockerfile.web`), `api` (`docker/Dockerfile.api`)
y `scheduler` (mismo build que `api`, cron de scraping). Opcionalmente, con
`--profile monitoring`, también Prometheus y Grafana. `docker-compose.override.yml`
permite overrides locales sin tocar el compose base.

Variables recomendadas para despliegue Docker:

```dotenv
DATABASE_URL=postgresql://<user>:<pass>@<host>:5432/<db>?sslmode=verify-full
API_HMAC_SECRET=<secreto-hmac-32+-chars>
FORWARDED_ALLOW_IPS=<ip-o-rango-del-reverse-proxy>
GF_SECURITY_ADMIN_PASSWORD=<password-admin-grafana>
```

Los workflows de `.github/workflows/` siguen disponibles para scraping,
healthchecks y despliegues automatizados.

### Render.com (PaaS, alternativa a Docker propio)

`render.yaml` define el servicio `tenderflow-api` (build vía
`docker/Dockerfile.api`) con las variables de entorno de producción declaradas
como `sync: false` (se configuran en el dashboard de Render, nunca en el repo).
Conectá el repositorio en Render y usa "Blueprint" para aplicar `render.yaml`
directamente.

---

## Seguridad

### Autenticación

| Mecanismo | Descripción |
|-----------|-------------|
| Password | Comparación con `hmac.compare_digest`. Rate limiting progresivo (bloqueo `2^n` segundos tras 3 intentos). Timeout de sesión 8h |
| Google OAuth | HMAC-SHA256 state con nonce + timestamp. Clave de firma independiente (`SIGNING_KEY`) del client secret |
| TOTP (2FA) | Secretos cifrados con Fernet (`TOTP_ENCRYPTION_KEY`), obligatorio en `ENV=prod` |

### Protecciones generales

| Área | Medida |
|------|--------|
| Inyección SQL | Queries parametrizadas (shim qmark→`%s` en Postgres, ver [ADR-016](docs/adr/ADR-016-destino-persistencia-supabase.md)); acceso a BD solo vía `db/repositories/*` |
| XSS | HTML dinámico escapado con `html.escape()` |
| SSRF | `shared/ssrf.py` valida URLs salientes (documentos, webhooks); `WEBHOOK_ALLOWED_HOSTS`/`DOCUMENT_ALLOWED_HOSTS` como allowlist |
| XXE (XML) | Parser lxml con `resolve_entities=False`, `no_network=True` |
| Tamaño de descarga | ZIP ≤ 200 MB, XML ≤ 150 MB por fichero |
| Serialización ML | `joblib` en lugar de `pickle` para el clasificador |
| Secretos en logs | Structlog redacta automáticamente tokens, passwords y API keys |
| Auditoría | Log de eventos encadenado con SHA-256 (`db/audit.py`), verificable con `scripts/verify_audit_chain.py` |
| TLS a BD | `DATABASE_URL` exige `sslmode=verify-full` en prod/staging contra hosts remotos (`config/settings.py`) |

### Rotación de credenciales

Matriz completa (qué rotar, cuándo, quién y dónde) en
[docs/SECURITY.md](docs/SECURITY.md). Si una credencial de BD se compromete:

**Postgres/Supabase** (`DATABASE_URL` comprometida):
1. Supabase Dashboard → Project → Database → **Reset database password**.
2. Reconstruir `DATABASE_URL` con la nueva password → actualizar `.env` y secrets de GitHub/Render.

---

## Personalizar keywords

Las keywords para cada tecnología están en `config/keywords.py`:

- `SAP_KEYWORDS` — módulos, suite cloud, infraestructura SAP
- `TECHNOLOGY_KEYWORDS` — SAP, Salesforce, Oracle, Microsoft, ServiceNow, Workday, IBM, OpenText, Unit4, Meta4, Sopra, Sage, Infor

Para añadir una tecnología nueva, añade una entrada al dict `TECHNOLOGY_KEYWORDS`.

---

## CI / Calidad de código

```bash
# Linting y formato
ruff check .
ruff format .

# Tipos (todo el repo)
mypy .

# Tests con cobertura (umbral: 70%, branch coverage activado)
pytest

# Pre-commit hooks
pre-commit run --all-files

# Auditoría de dependencias
pip-audit --strict --desc
```

O simplemente `make check` (lint + typecheck + tests unitarios) —
también disponible como slash-command `/check` en Claude Code.

Para cambios en `web/`, además:

```bash
make web-lint        # ESLint
make web-typecheck   # tsc --noEmit
npm --prefix web run test          # Vitest (thresholds en vitest.config.ts)
make web-test-e2e    # Playwright
```

El pipeline de CI (`.github/workflows/ci.yml`) incluye además un job de
`docker build` que verifica que la imagen compila correctamente en cada push,
y `security.yml` corre Semgrep SAST + Trivy sobre la imagen.

---

## Marco legal

Los datos se reutilizan al amparo de:

- **Ley 37/2007** de reutilización de información del sector público
- **Real Decreto 1495/2011**
- **Ley 9/2017** de Contratos del Sector Público

Fuente oficial: Plataforma de Contratación del Sector Público
(https://contrataciondelestado.es).

Esta aplicación **no suplanta** a la fuente oficial; sirve únicamente
para fines de análisis estadístico e inteligencia comercial.

---

## Limitaciones conocidas

- La URL de los ZIP mensuales puede cambiar; verificar contra
  hacienda.gob.es si fallan las descargas.
- El parser CODICE asume estructura estándar; entradas malformadas
  se loggean y se omiten sin interrumpir el proceso.
- Los datos de meses recientes pueden tardar en publicarse
  (el ZIP del mes M suele aparecer a mediados del mes M+1).
- La búsqueda de texto (`/search`) usa FTS5/BM25 (SQLite) o `tsvector`+GIN
  (Postgres) por defecto; `faiss-cpu` se eliminó en Fase 3 (2026-07-04).
  La similitud semántica basada en embeddings (sentence-transformers) requiere
  instalar el extra `[ml]` y sigue en uso en clasificación/clustering.
