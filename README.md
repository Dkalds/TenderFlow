# TenderFlow

Inteligencia de licitaciones del Sector Público español.

---

## Características principales

| Módulo | Descripción |
|--------|-------------|
| **Scraper** | Descarga ZIPs mensuales (bulk) y feed ATOM en vivo de PLACSP. Parser CODICE/UBL con resiliencia (circuit breaker, reintentos) |
| **Clasificación** | Filtrado por keywords + modelo ML TF-IDF + LogisticRegression entrenado sobre los propios datos |
| **Base de datos** | Postgres/Supabase en producción, SQLite local en desarrollo. Upsert idempotente, historial de cambios, DLQ |
| **Web frontend** | Next.js con interfaz principal para explorar la plataforma y consumir la API |
| **Alertas** | Emails automáticos por watchlist de usuario (CPV, keyword, CCAA, importe mínimo) |
| **Observabilidad** | Structlog (JSON/consola), Prometheus metrics, healthcheck, alertas por nivel de severidad |
| **Autenticación** | Password con rate limiting + Google OAuth 2.0, HMAC-signed CSRF state |
| **Búsqueda semántica** | sentence-transformers + FAISS para similitud de licitaciones (opcional, ver deps) |

---

## Arquitectura

```
┌─────────────────────────┐       ┌──────────────────────┐
│ PLACSP open data        │──────▶│  scraper/pipeline    │
│ - ZIPs mensuales (bulk) │       │  - descarga + parse  │
│ - Feed ATOM en vivo     │       │  - filtro keywords   │
└─────────────────────────┘       │  - clasificador ML   │
                                  └──────────┬───────────┘
                                             │  upsert idempotente
                                             ▼
                              ┌──────────────────────────┐
                              │  Postgres / SQLite local │
                              │  (historial de cambios)  │
                              └──────────┬───────────────┘
                                         │
                          ┌──────────────┼──────────────┐
                          ▼              ▼              ▼
              ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
              │ GitHub       │  │  Next.js UI  │  │ Alertas      │
              │ Actions cron │  │ KPIs+gráficos│  │ email/SMTP   │
              └──────────────┘  └──────────────┘  └──────────────┘
```

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
│   ├── types.py                  #   TypedDicts y alias compartidos
│   └── cache_signal.py           #   Señal de invalidación scraper → frontend
├── services/                     # Capa de dominio (lógica de negocio pura)
│   ├── licitaciones.py           #   Reglas y agregaciones de licitaciones
│   ├── normalization.py          #   Normalización de empresas y NIFs
│   ├── classification.py         #   Clasificación por CPV, módulos, tecnología
│   ├── clusters.py               #   Clustering de licitaciones
│   ├── analytics_engine.py       #   Motor analítico DuckDB
│   ├── rate_limiting.py          #   Rate limiting (SQLite backend)
│   ├── rate_limit_redis.py       #   Rate limiting (Redis backend, opcional)
│   ├── investigador/             #   Motor de búsqueda FTS5
│   └── ...                       #   admin, auth, gdpr, health, security, watchlist
├── db/                           # Persistencia y acceso a datos
│   ├── connection.py             #   Conexión SQLite/Postgres con pool
│   ├── database.py               #   Fachada principal (init, connect, upsert)
│   ├── upsert.py                 #   Upsert idempotente con historial
│   ├── migrations.py             #   Migraciones DDL caseras (v1–v20)
│   ├── repositories/             #   Patrón Repository (licitaciones, adjudicaciones, ...)
│   ├── alembic/                  #   Migraciones Alembic (DDL versionadas)
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
│   └── routes/                   #   Endpoints: licitaciones, meta, models, webhooks, ...
├── scraper/                      # Pipeline de extracción de datos
│   ├── pipeline.py               #   Orquestador principal (bulk + daily)
│   ├── bulk_downloader.py        #   Descarga ZIPs mensuales de PLACSP
│   ├── codice_parser.py          #   Parser ATOM/CODICE (formato UBL)
│   ├── atom_live.py              #   Feed ATOM en vivo (cada 4h)
│   ├── filters.py                #   Detección de keywords por tecnología
│   ├── ml_classifier.py          #   Clasificador ML TF-IDF + LogisticRegression
│   ├── ml_training.py            #   Entrenamiento y re-cómputo de ml_proba
│   ├── ml_pipeline.py            #   Pipeline ML de extremo a extremo
│   └── resilience.py             #   Circuit breaker, reintentos, timeouts
├── scheduler/                    # Tareas programadas
│   ├── loop.py                   #   Bucle principal del scheduler (Docker)
│   ├── run_update.py             #   Entry point para cron / GitHub Actions
│   ├── kpi_precompute.py         #   Pre-cómputo de KPIs pesados
│   ├── watchlist_alerts.py       #   Alertas por watchlist (batch optimizado)
│   ├── drift_monitor.py          #   Detección de concept drift + alertas
│   ├── anomaly_alerts.py         #   Alertas de anomalías (frescura, cobertura)
│   ├── healthcheck.py            #   Verificación de frescura de datos
│   └── dlq_retry.py              #   Reintento automático de DLQ
├── observability/                # Logging, métricas, trazas
│   ├── logging.py                #   Structlog (JSON/consola), redacción de secretos
│   ├── alerts.py                 #   Envío de alertas por email / nivel
│   ├── metrics.py                #   Métricas de sistema (kpi_snapshots)
│   ├── prometheus.py             #   Métricas Prometheus (textfile + HTTP)
│   ├── tracing.py                #   OpenTelemetry (OTLP, opcional)
│   ├── sentry.py                 #   Sentry (opt-in)
│   └── grafana/                  #   Dashboards Grafana (RED, SLO)
├── llm/                          # Integración con LLMs (opcional)
│   ├── client.py                 #   Cliente unificado
│   └── providers/                #   OpenAI, Anthropic
├── scripts/                      # Scripts de mantenimiento
│   ├── doctor.py                 #   Verificación de entorno
│   ├── backup_db.py              #   Backup de la BD
│   ├── retrain.py                #   Reentrenamiento del modelo ML
│   ├── rotate_api_keys.py        #   Rotación de API keys
│   └── ...                       #   dedupe, retention, coverage
├── docs/                         # Documentación técnica
│   ├── adr/                      #   Architecture Decision Records (ADR-001..007)
│   ├── runbooks/                 #   Playbooks operativos (backup, DLQ, DR, ...)
│   ├── c4-architecture.md        #   Diagramas C4 (Mermaid)
│   ├── database-schema.md        #   Esquema ER + tablas + queries
│   ├── sli-slo.md                #   SLIs/SLOs del sistema
│   └── SECURITY.md               #   Prácticas de seguridad y rotación
├── tests/                        # Tests (unit, integration, e2e, property, load)
├── .github/workflows/            # CI/CD
│   ├── ci.yml                    #   Lint, tipos, tests, pre-commit, audit, docker build
│   ├── security.yml              #   Semgrep SAST + Trivy + rotation reminder
│   ├── scrape.yml                #   Bulk mensual (diario 06:00 UTC)
│   ├── scrape-daily.yml          #   Feed ATOM en vivo (cada 4h)
│   ├── healthcheck.yml           #   Healthcheck (cada 6h)
│   ├── train-model.yml           #   Entrenamiento programado del clasificador
│   └── ...                       #   backup, changelog, release, release-sdk
├── Dockerfile                    # Multi-stage build (deps + runtime)
├── docker-compose.yml            # web + api + scheduler (+ monitoring opcional)
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

Crea un archivo `.env` en la raíz del proyecto:

```dotenv
# ── Entorno ─────────────────────────────────────────────
ENV=dev

# ── Base de datos (elige una opción) ────────────────────

# Opción A — SQLite local (por defecto, sin configuración adicional).
# Es una comodidad de desarrollo, no la referencia de producción.
# DB_PATH=data/licitaciones.db

# Opción B — Postgres / Supabase (producción)
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

# ── Alertas por email (opcional) ─────────────────────────
ALERT_EMAIL_TO=destino@ejemplo.com
ALERT_SMTP_USER=remitente@gmail.com
ALERT_SMTP_PASSWORD=<app-password-gmail>
```

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
volumen de datos: `web` (Next.js), `api` (FastAPI REST) y `scheduler`
(cron de scraping). Opcionalmente, con `--profile monitoring`, también
Prometheus y Grafana.

Variables recomendadas para despliegue Docker:

```dotenv
API_HMAC_SECRET=<secreto-hmac-32+-chars>
FORWARDED_ALLOW_IPS=<ip-o-rango-del-reverse-proxy>
GF_SECURITY_ADMIN_PASSWORD=<password-admin-grafana>
```

Los workflows de `.github/workflows/` siguen disponibles para scraping,
healthchecks y despliegues automatizados.

---

## Seguridad

### Autenticación

| Mecanismo | Descripción |
|-----------|-------------|
| Password | Comparación con `hmac.compare_digest`. Rate limiting progresivo (bloqueo `2^n` segundos tras 3 intentos). Timeout de sesión 8h |
| Google OAuth | HMAC-SHA256 state con nonce + timestamp. Clave de firma independiente (`SIGNING_KEY`) del client secret |

### Protecciones generales

| Área | Medida |
|------|--------|
| Inyección SQL | Queries parametrizadas con `?`; columnas derivadas de dataclass fields (constantes internas) |
| XSS | HTML dinámico escapado con `html.escape()` |
| Validación de URLs | `safe_url()` rechaza esquemas `javascript:` |
| XXE (XML) | Parser lxml con `resolve_entities=False`, `no_network=True` |
| Tamaño de descarga | ZIP ≤ 200 MB, XML ≤ 150 MB por fichero |
| Serialización ML | `joblib` en lugar de `pickle` para el clasificador |
| Secretos en logs | Structlog redacta automáticamente tokens, passwords y API keys |

### Rotación de credenciales

Si una credencial de BD se compromete:
1. Panel Supabase → tu proyecto → **Database → Roles** → rotar password
2. Reconstruir `DATABASE_URL` con la password nueva → actualizar `.env` y secrets de GitHub

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

# Tipos
mypy scraper/ db/ scheduler/ observability/ config/ api/ shared/

# Tests con cobertura (umbral: 50%)
pytest

# Pre-commit hooks
pre-commit run --all-files

# Auditoría de dependencias
pip-audit -r requirements.txt
```

El pipeline de CI incluye además un job de `docker build` que verifica
que la imagen compila correctamente en cada push.

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
- La búsqueda semántica (FAISS) requiere instalar el extra `[ml]`
  y genera embeddings en la primera carga (~30 s con GPU, ~5 min sin GPU).
