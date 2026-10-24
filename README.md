# TenderFlow

Inteligencia de licitaciones del Sector Público español.

TenderFlow reúne en una sola base los anuncios de PLACSP, TED y las plataformas
autonómicas, detecta los que son de tecnología, y da a un equipo comercial lo que
necesita para decidir a cuáles presentarse y prepararlos: búsqueda, alertas,
análisis de competencia y de mercado, un pipeline de oportunidades con matriz
GO/NO-GO y un asistente que responde en lenguaje natural citando los pliegos.

Cada decisión estructural, con su porqué, está en [`docs/adr/`](docs/adr/README.md);
el índice de toda la documentación, en [`docs/README.md`](docs/README.md).

---

## Qué hace

| Módulo | Descripción |
|--------|-------------|
| **Ingesta multi-fuente** | Framework de conectores ([ADR-009](docs/adr/ADR-009-framework-conectores-multifuente.md)): PLACSP (feed ATOM en vivo en la pasada de cada 4 h; si el ATOM no avanza en seis pasadas, el carril cae al ZIP mensual del mes en curso; ZIPs bulk a demanda vía `scrape-bulk.yml`), TED, Galicia y Euskadi activos en cada pasada; PSCP y TACRC (índice del Pleno o, por años, el completo) se activan cuando sus variables de fuente están configuradas; las plataformas autonómicas agregadas y los contratos menores de PLACSP están escritos y **apagados** hasta revisar D16 ([cómo se encienden](docs/runbooks/fuentes-opcionales.md)). Parser CODICE/UBL con resiliencia (circuit breaker, reintentos, DLQ) |
| **Clasificación** | Filtro por keywords en castellano, catalán, euskera y gallego + clasificadores TF-IDF + LogisticRegression entrenados sobre los propios datos (`services/ml/`) + etiquetado por LLM de la señal tecnológica |
| **Base de datos** | **Postgres** en producción, CI y desarrollo — motor único ([ADR-016](docs/adr/ADR-016-destino-persistencia-supabase.md) Supabase, psycopg3 + pool gestionado; Turso retirado en [ADR-020](docs/adr/ADR-020-retirada-turso.md) y SQLite en [ADR-021](docs/adr/ADR-021-retirada-sqlite.md)). Upsert batcheado e idempotente, historial de cambios, detección de duplicados entre fuentes |
| **Consola web** | Next.js 16: resumen y KPIs, detalle de expedientes, mercado, competencia, Radar de priorización, cuentas objetivo, watchlist, Dirección y administración (`/ops`) |
| **Oportunidades** | Pipeline del expediente al cierre: matriz GO/NO-GO, tareas, comentarios, adjuntos, simulador de precio y renovaciones de cartera (`services/pursuits*.py`, `services/go_no_go*.py`) |
| **Investigador y asistente RAG** | Búsqueda full-text (`tsvector` + GIN, vía `db/search_backend.py`) y preguntas en lenguaje natural (`/api/v1/ask`) vía LLM (NVIDIA NIM/DeepSeek por defecto; OpenAI/Anthropic opcionales), con streaming SSE y presupuesto/circuit-breaker de gasto |
| **Analítica competitiva** | Bajas anómalas, cuota de mercado, renovaciones y riesgo de cambio de proveedor (`services/competitive/`) |
| **Alertas y avisos** | Watchlist por CPV, keyword, CCAA o importe; alertas de competidores; campana de notificaciones; digests diarios y semanales; informes programados; webhooks |
| **Multi-organización** | Equipos con roles, y aislamiento de datos en dos capas: filtro de aplicación + RLS por tenant ([ADR-034](docs/adr/ADR-034-rls-por-tenant.md)) |
| **Web pública** | Fichas indexables del **anuncio** de licitación, con cita de la fuente y fecha de actualización (ver [Marco legal](#marco-legal)) |
| **MCP interno** | Servidor MCP de solo lectura para que el equipo consulte la base desde Claude u otro cliente MCP ([ADR-036](docs/adr/ADR-036-acceso-interno-por-mcp.md), [runbook](docs/runbooks/mcp-interno.md)) |
| **Observabilidad** | Structlog (JSON/consola), métricas Prometheus, Alertmanager, dashboards Grafana, tracing OTLP y Sentry opcionales ([ADR-019](docs/adr/ADR-019-observabilidad-desplegada.md)) |
| **Autenticación** | Password con recuperación de un solo uso + Google OAuth 2.0 con grants dinámicos auditables, HMAC-signed CSRF state y TOTP (2FA) |

Los recorridos completos de usuario, con su test, están en
[docs/casos-de-uso.md](docs/casos-de-uso.md).

---

## Arquitectura

```mermaid
graph TD
    Fuentes["Fuentes oficiales<br/>PLACSP · TED · PSCP · TACRC · Galicia · Euskadi"]
    Actions["GitHub Actions<br/>plano de cron (ADR-012)"]
    Scraper["scraper/<br/>conectores + parser CODICE/UBL"]
    DB[("Postgres / Supabase<br/>motor único, RLS por tenant")]
    API["api/<br/>FastAPI · /api/v1"]
    Web["web/<br/>Next.js 16"]
    MCP["mcp_server/<br/>MCP interno, solo lectura"]
    LLM["Proveedor LLM<br/>NVIDIA NIM · OpenAI · Anthropic"]
    Obs["Observabilidad<br/>Prometheus · Alertmanager · Grafana"]
    Usuario["Usuario<br/>(navegador)"]
    Integracion["Integración externa<br/>X-API-Key"]
    Admin["Admin<br/>(Claude u otro cliente MCP)"]

    Actions -->|"cada 4 h"| Scraper
    Fuentes -->|"ATOM · ZIP mensual · APIs"| Scraper
    Scraper -->|"upsert idempotente"| DB
    Usuario -->|"HTTPS"| Web
    Web -->|"contratos OpenAPI tipados"| API
    Integracion --> API
    API <--> DB
    API -->|"/ask, con presupuesto de gasto"| LLM
    Admin -->|"OAuth 2.1"| MCP
    MCP -->|"rol tenderflow_mcp"| DB
    Obs -->|"scrape GET /metrics"| API
```

- **Capas con imports hacia abajo**: `config < observability < shared < llm < db
  < services < scraper < scheduler < api < mcp_server`. Todo el SQL vive en
  `db/` ([ADR-022](docs/adr/ADR-022-frontera-de-persistencia.md)), `services/`
  es biblioteca de dominio ([ADR-024](docs/adr/ADR-024-services-biblioteca-no-frontera.md))
  y `web/` solo habla con `api/`. `scripts/check_layers.py` lo verifica.
- **Un solo plano de orquestación por entorno**
  ([ADR-012](docs/adr/ADR-012-plano-unico-orquestacion.md)): en producción
  son los workflows de GitHub Actions; en local, el servicio `scheduler` de
  `docker-compose.yml`. Nunca los dos contra la misma base.
- **El MCP es un servicio aparte** con su propio OAuth y un rol de Postgres que
  solo ve las tablas y columnas del catálogo (`mcp_server/catalogo.py`): el
  límite del SQL lo pone Postgres, no el código.

Diagramas C4 completos (contexto, contenedores, componentes) en
[docs/c4-architecture.md](docs/c4-architecture.md); el esquema real de la base,
en [docs/database-schema.md](docs/database-schema.md).

### Una pasada de ingesta

`scrape-daily.yml` corre cada 4 h y la parte en dos mitades, para que el cierre
vea los datos de todas las fuentes y no solo los de PLACSP:

```mermaid
graph LR
    Fuente["Fuente<br/>ATOM · ZIP · API"] -->|"descarga + parse"| Parse["Licitación normalizada<br/>codice_parser.py · connectors/"]
    Parse --> Filtro["Filtro tecnológico<br/>keywords multilingües"]
    Filtro -->|"upsert idempotente"| DB[("Postgres")]
    Filtro -.->|"fila que viola una restricción"| DLQ[("DLQ<br/>reintento en el cierre")]
    DB --> Cierre["Cierre<br/>run_update --fase cierre"]
    Cierre --> ML["Scoring ML<br/>+ señal tecnológica"]
    Cierre --> KPI["KPIs y agregados<br/>precalculados"]
    Cierre --> Avisos["Alertas, eventos,<br/>digests e informes"]
    Cierre --> Mant["Reintento DLQ · anomalías<br/>retención · drift"]
```

| Paso | Qué hace | Dónde |
|---|---|---|
| **Ingesta PLACSP** | Feed ATOM en vivo; si no avanza, ZIP mensual del mes en curso | `run_update --daily --fase ingesta` |
| **Conectores** | TED, Galicia, Euskadi, empresas vigiladas; PSCP, TACRC y los opcionales si su variable está configurada | `python -m scraper.connectors.<fuente>` |
| **Cierre** | La secuencia canónica de pasos post-ingesta, cada uno marcado como bloqueante o advisory | `run_update --daily --fase cierre` · `CANONICAL_STEPS` en `scheduler/pipeline_runs.py` |
| **Healthcheck** | Frescura de los datos; alerta si falla | `python -m scheduler.healthcheck --alert` |

Reejecutar una pasada no duplica nada: el upsert va por `id_externo`
(`db/upsert.py`), y los duplicados entre fuentes se marcan en
`licitaciones_duplicados` en vez de borrarse.

---

## Producción

| Servicio | Dónde corre | Health |
|---|---|---|
| API REST | Render, `tenderflow-api` | `GET /api/v1/health` |
| Web | Vercel, proyecto `tenderflow` (`web/vercel.json`, región `fra1`) | `GET /` |
| Ingesta y jobs | GitHub Actions (`scrape-daily.yml` cada 4 h, `ml-scoring.yml`, …) | `healthcheck.yml` cada 6 h |
| Base de datos | Supabase Postgres | `python scripts/doctor.py` |
| MCP interno | Render, `tenderflow-mcp` | `GET /healthz` |
| Observabilidad | Render: `tenderflow-prometheus`, `tenderflow-alertmanager`, `tenderflow-grafana` | `GET /api/health` (Grafana) |

```mermaid
graph LR
    Push["push / pull request"] --> CI["ci.yml<br/>lint · mypy · tests Postgres<br/>fuzzing · E2E · Trivy"]
    CI -->|"merge"| Master["master"]
    Master -->|"deploy.yml, a mano"| API["Render<br/>tenderflow-api"]
    API --> Verif["healthcheck · alineación<br/>de schema · smoke"]
    Verif -->|"si pasa"| MCP["Render<br/>tenderflow-mcp"]
    Master -->|"migrate.yml, a mano"| DB[("Supabase<br/>alembic upgrade head")]
    Master -->|"autoDeploy de Render"| Obs["Render<br/>Prometheus · Alertmanager · Grafana"]
    Master -->|"integración Git de Vercel"| Web["Vercel<br/>web"]
    Push -.->|"preview por rama"| Web
```

- **`deploy.yml` es el único disparador** de la API y del MCP: los dos tienen
  `autoDeploy: false` en `render.yaml`, así que un push a `master` no despliega
  un commit sin verificar. El MCP sale del mismo commit, y solo si la API pasó
  su verificación.
- **Migrar producción es una decisión explícita**: `migrate.yml` solo se lanza a
  mano. Un deploy verde no prueba que la migración de ese PR haya corrido.
- **La observabilidad sí se redespliega sola**: su configuración va horneada en
  la imagen, y una regla de alerta editada solo llega con un build nuevo.
- **La web también**: Vercel despliega a producción cada push a `master` y
  publica una preview por rama, que enlaza en el propio PR. No pasa por
  `deploy.yml`, así que un merge llega al frontend aunque la API no se haya
  redesplegado todavía.

Procedimientos de operación e incidentes en [docs/runbooks/](docs/runbooks/README.md).

---

## Estructura del proyecto

```
tenderflow/
├── config/              Settings (pydantic-settings), semilla de keywords, constantes PLACSP
├── observability/       Structlog, métricas Prometheus, alertas, Sentry, OTLP, dashboards Grafana
├── shared/              Utilidades sin lógica de negocio: auth_core, dto (contrato API↔web), csrf,
│                        signing (JWKS), ssrf, geo (NUTS3→CCAA), object_store, …
├── llm/                 Cliente LLM unificado, providers y presupuesto de gasto (budget.py)
├── db/                  Todo el SQL: conexión y pools, upsert idempotente, repositories/,
│                        migraciones Alembic (alembic/), auditoría encadenada, DLQ
├── services/            Dominio: licitaciones, oportunidades, GO/NO-GO, avisos, analytics/,
│                        competitive/, investigador/ (FTS), ml/ (clasificadores y modelos), rag/
├── scraper/             Ingesta: connectors/ (una fuente por módulo), parser CODICE/UBL,
│                        feed ATOM, ZIPs bulk, documentos, filtro tecnológico, resiliencia
├── scheduler/           Orquestación: run_update, pipeline_runs (pasos de cierre), jobs/,
│                        precomputes, alertas, drift, retención, worker de la cola
├── api/                 FastAPI: app.py, middlewares, auth por X-API-Key, routes/
├── mcp_server/          MCP interno de solo lectura: OAuth propio (auth/), tools/, catálogo
├── web/                 Frontend Next.js (src/app/: consola en (dashboard)/, web pública en (publico)/)
├── scripts/             Doctor, ratchets de CI, generadores de docs, evaluaciones, mantenimiento
├── tests/               pytest con auto-marking (unit, integration, e2e, property, load)
├── docs/                ADRs, runbooks, RFCs, casos de uso, esquema, SLI/SLO, seguridad, legal
├── docker/              Dockerfiles multi-stage (api, web, prometheus, alertmanager) + entrypoints
├── .github/workflows/   CI, seguridad, ingesta, scoring y entrenamiento ML, deploy, migraciones
├── docker-compose.yml   Stack local (web + api + postgres; perfiles scheduler, redis, monitoring)
└── render.yaml          Blueprint de Render (API, MCP y observabilidad)
```

El mapa de paquetes con sus entry points y documentación está en
[docs/AGENT_PLAYBOOK.md](docs/AGENT_PLAYBOOK.md); los conteos (tests, endpoints,
jobs, ratchets), en [docs/STATUS.md](docs/STATUS.md), que genera `make status`.

---

## Puesta en marcha en local

Requiere Python 3.11+ (CI y producción usan 3.13, el de `.python-version`),
Node para `web/` y Docker para Postgres.

```bash
git clone https://github.com/Dkalds/TenderFlow.git
cd TenderFlow
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
pip install -e ".[pliegos]"         # extracción de PDF: la piden sus tests
cp .env.example .env                # ENV=dev y DATABASE_URL local, ver «Configuración»
docker compose up -d postgres
```

Extras opcionales de `pyproject.toml`: `[ml]` (embeddings con sentence-transformers,
~2 GB por PyTorch), `[llm]`, `[tracing]`, `[analytics]`, `[crypto]`.

Para arrancar las piezas por separado:

```bash
make api                            # FastAPI en modo desarrollo
cd web && npm ci && cd ..
make web-dev                        # Next.js en http://localhost:3000
```

O el stack entero en Docker:

```bash
docker compose up -d                          # web (:3000) + api (:8080) + postgres
docker compose --profile scheduler up -d      # + scheduler (SCHEDULER_PLANE=docker)
docker compose --profile monitoring up -d     # + Prometheus y Grafana
```

En Windows, la ruta mínima en PowerShell está en
[docs/windows-happy-path.md](docs/windows-happy-path.md).

---

## Configuración

`.env.example` es la lista completa comentada. Extracto de las variables más
relevantes para empezar:

```dotenv
# ── Entorno ─────────────────────────────────────────────
# Default: prod (fail-safe). Usar dev solo en local.
ENV=dev

# ── Base de datos — Postgres es el único motor (ADR-021) ─

# Dev local: `docker compose up -d postgres` levanta el servicio del compose.
#   DATABASE_URL=postgresql://tenderflow:tenderflow@localhost:5432/tenderflow?sslmode=disable  # pragma: allowlist secret
# (sslmode=disable solo vale contra localhost; se rechaza para hosts remotos.)

# Producción — Supabase (ADR-016). Usar el Supavisor session pooler (5432,
# IPv4). En prod/staging exigir sslmode=verify-full + DATABASE_SSL_ROOT_CERT.
DATABASE_URL=postgresql://<user>:<pass>@<host>:5432/<db>?sslmode=verify-full

# ── OAuth Google (opcional) ──────────────────────────────
GOOGLE_CLIENT_ID=<client-id>.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=<client-secret>
OAUTH_REDIRECT_URI=http://localhost:3000
# Las dos listas son el arranque: el resto de accesos se concede y se revoca desde
# Ops › Administración › Solicitudes de acceso (docs/runbooks/conceder-acceso.md).
OAUTH_ALLOWED_EMAILS=persona@empresa.com,otra@empresa.com
OAUTH_ALLOWED_DOMAINS=empresa.com
OAUTH_ADMIN_EMAILS=admin@empresa.com
# Clave independiente para firmar tokens CSRF (obligatoria en producción):
# python -c "import secrets; print(secrets.token_hex(32))"
SIGNING_KEY=<clave-aleatoria-32-chars>

# ── Asistente RAG /api/v1/ask (opcional) ─────────────────
# Proveedor por defecto: NVIDIA NIM (API compatible con OpenAI, modelo deepseek).
# NVIDIA_API_KEY=nvapi-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# Alternativos: OPENAI_API_KEY, ANTHROPIC_API_KEY
# NVIDIA retira modelos sin aviso. El catálogo vivo se consulta sin auth:
#   curl -s https://integrate.api.nvidia.com/v1/models | grep -o '"id":"[^"]*"'

# ── Alertas por email (opcional) ─────────────────────────
ALERT_EMAIL_TO=destino@ejemplo.com
ALERT_SMTP_USER=remitente@gmail.com
ALERT_SMTP_PASSWORD=<app-password-gmail>
```

`config/settings.py` declara muchas más (Redis, rate limiting, TOTP/2FA,
webhooks, auditoría, CORS, tracing OTLP, tuning de ML y anomalías) con defaults
seguros. Las obligatorias en producción tienen que estar declaradas en
`render.yaml`: `make check-env-parity` lo verifica.

> **Importante:** `.env` está en `.gitignore`. Nunca lo commitees.

---

## Uso

```bash
python -m scheduler.run_update --backfill 2024 1   # primera carga: de enero 2024 a hoy
python -m scheduler.run_update                     # refresca los últimos 3 meses (--months N)
python -m scheduler.run_update --daily             # carril ligero: feed ATOM en vivo
python scripts/ml_clasificadores.py train          # entrena el clasificador SAP
```

Todas son **idempotentes**: el upsert va por `id_externo`, y ejecutarlas varias
veces no duplica registros. El clasificador necesita al menos 50 registros
etiquetados y se guarda en `data/models/sap_classifier.pkl`.

---

## Calidad y CI

```bash
make check           # lint + typecheck + tests unitarios y de integración, fail-fast
make test-unit       # bucle rápido, sin BD
make lint            # ruff
make typecheck       # mypy strict en todo el código de producción
```

Los tests usan **solo Postgres** y leen `TEST_DATABASE_URL`; cada test recibe un
schema aislado. CI exige un 78 % de cobertura con branch coverage.

Para cambios en `web/`:

```bash
make web-lint        # ESLint
make web-typecheck   # tsc --noEmit
make web-test        # Vitest, con gate de suite realmente ejecutada
make web-test-e2e    # Playwright
```

Además de los tests, varios ratchets fallan si el repo empeora: dirección de
imports (`make check-layers`), contrato API↔web (`make check-api-contract`),
operaciones nuevas de la API sin motivo (`make check-api-surface`), integridad
analítica del frontend (`make check-frontend-invariants`), superficie pública
(`make check-public-surface`) y casos de uso sin recorrido (`make check-casos-uso`).
`make help` lista todos los targets.

`ci.yml` corre en cada push y PR: lint, typecheck y pre-commit; tests contra
Postgres; fuzzing del contrato con Schemathesis; migraciones online; auditoría de
dependencias y bandit; build de Docker + Trivy; drift de codegen; compatibilidad
del contrato API; y el frontend (typecheck, lint, tests, build y E2E de Playwright
contra un backend real). `security.yml` añade Semgrep y el recordatorio de rotación.

Cómo se trabaja en el repo (instrucciones para personas y agentes) en
[CONTRIBUTING.md](CONTRIBUTING.md) y [AGENTS.md](AGENTS.md).

---

## Seguridad

### Autenticación

| Mecanismo | Descripción |
|-----------|-------------|
| Password | Comparación con `hmac.compare_digest`. Rate limiting progresivo (bloqueo `2^n` segundos tras 3 intentos). Sesión deslizante: caduca tras 24 h sin actividad (`SESSION_IDLE_HOURS`, cada petición la renueva) con techo absoluto de 30 días desde el login (`SESSION_ABSOLUTE_DAYS`); «recordar este equipo» alarga la ventana de inactividad (`SESSION_REMEMBER_DAYS`) sin mover el techo |
| Google OAuth | HMAC-SHA256 state con nonce + timestamp. Clave de firma independiente (`SIGNING_KEY`) del client secret |
| TOTP (2FA) | Secretos cifrados con Fernet (`TOTP_ENCRYPTION_KEY`), obligatorio en `ENV=prod` |
| Recuperación local | Token aleatorio de un uso; sólo se persiste SHA-256, caduca en 30 min y revoca todas las sesiones al cambiar la contraseña |
| API keys | `X-API-Key` con scopes, rotables con `scripts/rotate_api_keys.py` |
| MCP interno | OAuth 2.1 propio con login de Google solo para admins; rol de Postgres de solo lectura ([ADR-036](docs/adr/ADR-036-acceso-interno-por-mcp.md)) |

### Protecciones generales

| Área | Medida |
|------|--------|
| Inyección SQL | Queries parametrizadas ([ADR-025](docs/adr/ADR-025-construccion-de-sql-y-pools.md)); todo el SQL vive en `db/` |
| Aislamiento entre organizaciones | Filtro de aplicación + RLS por tenant en Postgres ([ADR-034](docs/adr/ADR-034-rls-por-tenant.md)) |
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

El diccionario vigente vive en la tabla `tecnologias_keywords` y se edita desde
`/ops` sin desplegar; `config/keywords.py` es la **semilla** (lo que se vuelca
cuando la tabla está vacía y el respaldo si la BD no responde):

- `SAP_KEYWORDS` — módulos, suite cloud, infraestructura SAP
- `TECHNOLOGY_KEYWORDS` — un label → lista de keywords, de dos tipos:
  - **Fabricantes**: SAP, Salesforce, Oracle, Microsoft, ServiceNow, Workday,
    IBM, OpenText, Unit4, Meta4, Sopra, Sage, Infor. Nombran productos de un
    vendor.
  - **Categorías** (desde 2026-09-14): ERP, CRM, CLOUD_INFRA, CIBERSEGURIDAD,
    DATOS_IA, DESARROLLO, GIS, SANIDAD_DIGITAL, ADMIN_ELECTRONICA. Nombran qué
    se compra sin decir de quién, siempre dentro de TI.
- `TECH_CATEGORIAS` — etiqueta legible de cada label (UI y analítica),
  `TECH_LABEL_TIPO` — si es `fabricante` o `categoria` — y
  `TECH_DEFINICIONES` — qué cubre cada label, en una frase que viaja en la
  pregunta del etiquetado por LLM.

Las categorías llevan el vocabulario en **castellano, catalán, euskera y
gallego** cuando la forma difiere («desarrollo de software»,
«desenvolupament de programari», «software garapena», «desenvolvemento de
software»): la PSCP, Euskadi y Galicia publican en sus lenguas y un diccionario
solo en castellano no los veía. Los términos son sintagmas, no palabras sueltas
(«datos» o «software» a secas casarían con todo); los acrónimos cortos (`erp`,
`gis`) valen porque el filtro compila con límites de palabra.

Para añadir un label nuevo, añade la entrada a `TECHNOLOGY_KEYWORDS` **y** a
`TECH_CATEGORIAS`, `TECH_LABEL_TIPO` y `TECH_DEFINICIONES` (el módulo falla al
importar si los cuatro no coinciden), y resiembra (`POST /api/v1/tecnologias/keywords/sembrar` o desde
`/ops`). Cualquier cambio de la semilla cambia `filter_version` (hash del
contenido) y corta las series analíticas en esa fecha, por diseño (ADR-014).
Lista completa con el motivo de cada label en
[docs/taxonomia-tecnologica.md](docs/taxonomia-tecnologica.md).

---

## Marco legal

Los datos se reutilizan al amparo de:

- **Ley 37/2007** de reutilización de información del sector público
- **Real Decreto 1495/2011**
- **Ley 9/2017** de Contratos del Sector Público

Fuentes oficiales: Plataforma de Contratación del Sector Público
(https://contrataciondelestado.es) y base de datos TED de la Unión Europea.

Esta aplicación **no suplanta** a la fuente oficial: para preparar o presentar
una oferta, los documentos válidos son los del perfil del contratante.

**Reutilización pública.** Además del uso analítico interno, TenderFlow publica
una superficie indexable con el **anuncio** de licitación (objeto, órgano,
presupuesto, CPV, plazos y lotes). La Ley 37/2007 lo permite condicionado a
citar la fuente, indicar la fecha de la última actualización y no desnaturalizar
el dato: cada ficha pública cumple las tres cosas, y el marco completo está en
`/aviso-legal` (`web/src/app/(publico)/aviso-legal/page.tsx`).

**Qué no se publica.** Nada de la tabla `adjudicaciones` —ni denominación, ni
NIF, ni importes adjudicados—, porque un adjudicatario puede ser una persona
física y el sistema no distingue persona física de jurídica; publicarlo sería
un tratamiento de datos personales sin base jurídica suficiente. Tampoco sale
nada derivado del pipeline propio (scoring ML, linaje del filtro, predicciones).
La proyección pública es una allowlist explícita en
`db/repositories/publico.py`, y `make check-public-surface` la verifica en CI.

El registro de tratamientos (art. 30 RGPD) y el anexo de encargo para clientes
B2B están en [docs/legal/](docs/legal/registro-tratamientos.md).

---

## Limitaciones conocidas

- La URL de los ZIP mensuales puede cambiar; verificar contra
  hacienda.gob.es si fallan las descargas.
- El parser CODICE asume estructura estándar; entradas malformadas
  se loggean y se omiten sin interrumpir el proceso.
- Los datos de meses recientes pueden tardar en publicarse
  (el ZIP del mes M suele aparecer a mediados del mes M+1).
- `licitaciones.importe` es histórico y mezcla bases con y sin IVA; las columnas
  `importe_base_sin_iva`, `importe_con_iva` y `valor_estimado` se pueblan al
  re-ingerir ([ADR-032](docs/adr/ADR-032-semantica-del-importe-y-maestro-de-organos.md)).
- La similitud semántica basada en embeddings (sentence-transformers) requiere
  el extra `[ml]`; sin él, la búsqueda sigue funcionando sobre `tsvector`.
