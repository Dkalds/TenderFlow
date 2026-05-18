# Licitaciones SAP — Sector Público España

Sistema de inteligencia comercial que extrae automáticamente las licitaciones
publicadas en la **Plataforma de Contratación del Sector Público (PLACSP)**
relacionadas con proyectos de software enterprise (SAP, Salesforce, Oracle,
Microsoft Dynamics y otros) y las presenta en un dashboard interactivo con
análisis estadístico, alertas y exportación.

---

## Características principales

| Módulo | Descripción |
|--------|-------------|
| **Scraper** | Descarga ZIPs mensuales (bulk) y feed ATOM en vivo de PLACSP. Parser CODICE/UBL con resiliencia (circuit breaker, reintentos) |
| **Clasificación** | Filtrado por keywords + modelo ML TF-IDF + LogisticRegression entrenado sobre los propios datos |
| **Base de datos** | SQLite local o Turso cloud (réplica embebida). Upsert idempotente, historial de cambios, DLQ |
| **Dashboard** | Streamlit con KPIs, mapas, gráficos Plotly, comparador de periodos, watchlist, exportación PDF/Excel |
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
                              │  SQLite local / Turso    │
                              │  (historial de cambios)  │
                              └──────────┬───────────────┘
                                         │
                          ┌──────────────┼──────────────┐
                          ▼              ▼              ▼
              ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
              │ GitHub       │  │ Streamlit UI │  │ Alertas      │
              │ Actions cron │  │ KPIs+gráficos│  │ email/SMTP   │
              └──────────────┘  └──────────────┘  └──────────────┘
```

---

## Estructura del proyecto

```
licitaciones-sap/
├── config/                       # Configuración modular
│   ├── settings.py               #   Variables de entorno (pydantic-settings)
│   ├── keywords.py               #   SAP_KEYWORDS, TECHNOLOGY_KEYWORDS
│   └── constants.py              #   URLs PLACSP, CPV_PREFIXES_TI, campos histórico
├── shared/
│   └── geo.py                    # NUTS3 → CCAA (compartido entre scraper y dashboard)
├── db/
│   ├── database.py               # SQLite/Turso, upsert, historial, extracciones
│   ├── migrations.py             # Migraciones DDL idempotentes
│   ├── watchlist.py              # Persistencia de watchlist de usuario
│   ├── dlq.py                    # Dead Letter Queue para items fallidos
│   └── rate_limits.py            # Rate limiting en BD
├── scraper/
│   ├── pipeline.py               # Orquestador principal (bulk + daily)
│   ├── bulk_downloader.py        # Descarga ZIPs mensuales de PLACSP
│   ├── codice_parser.py          # Parser ATOM/CODICE (formato UBL)
│   ├── atom_live.py              # Feed ATOM en vivo (cada 4h)
│   ├── filters.py                # Detección de keywords por tecnología
│   ├── ml_classifier.py          # Clasificador ML TF-IDF + LogisticRegression
│   └── resilience.py             # Circuit breaker, reintentos, timeouts
├── dashboard/
│   ├── app.py                    # Entry point Streamlit
│   ├── auth.py                   # Password + Google OAuth 2.0
│   ├── data_loader.py            # Carga y enriquecimiento con caché
│   ├── classifiers.py            # CPV, módulos SAP, tipo de proyecto
│   ├── normalize.py              # Normalización de empresas y NIFs
│   ├── forecast.py               # Predicción de tendencias
│   ├── faiss_index.py            # Búsqueda semántica con FAISS (opcional)
│   ├── embeddings.py             # Generación de embeddings (opcional)
│   ├── kpi_bar.py                # Barra de KPIs reutilizable
│   ├── stats/                    # Funciones estadísticas (kpis, por_mes, ...)
│   ├── components/               # Cards, KPIs, navegación, toasts, iconos
│   ├── filters/                  # Estado de filtros y sidebar
│   ├── pages/                    # Una página Streamlit por sección
│   ├── theme/                    # Tokens de diseño, CSS, plantilla Plotly
│   └── utils/                    # Exportación PDF/Excel, formato, seguridad
├── scheduler/
│   ├── run_update.py             # Entry point para cron / GitHub Actions
│   ├── healthcheck.py            # Verificación de frescura de datos
│   ├── watchlist_alerts.py       # Alertas por watchlist (batch optimizado)
│   └── kpi_precompute.py         # Pre-cómputo de KPIs pesados
├── observability/
│   ├── logging.py                # Structlog configurado, redacción de secretos
│   ├── alerts.py                 # Envío de alertas por email / nivel
│   └── prometheus.py             # Métricas Prometheus (textfile + HTTP)
├── .github/workflows/
│   ├── ci.yml                    # Lint, tipos, tests, pre-commit, audit, docker build
│   ├── scrape.yml                # Bulk mensual (diario 06:00 UTC)
│   ├── scrape-daily.yml          # Feed ATOM en vivo (cada 4h)
│   └── healthcheck.yml           # Healthcheck (cada 6h)
├── Dockerfile                    # Multi-stage build (deps + runtime)
├── docker-compose.yml            # dashboard + scheduler compartiendo volumen
└── data/                         # BD SQLite + ZIPs descargados (gitignored)
```

---

## Instalación

### Instalación estándar

```bash
git clone https://github.com/Dkalds/Licitaciones_sap_SP.git
cd licitaciones-sap
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

El dashboard estará disponible en http://localhost:8501.
El scheduler ejecuta actualizaciones automáticamente en el mismo stack.

---

## Configuración

Crea un archivo `.env` en la raíz del proyecto:

```dotenv
# ── Entorno ─────────────────────────────────────────────
ENV=dev   # "prod" obliga a definir DASHBOARD_PASSWORD

# ── Base de datos (elige una opción) ────────────────────

# Opción A — SQLite local (por defecto, sin configuración adicional)
# DB_PATH=data/licitaciones.db

# Opción B — Turso cloud (réplica embebida local + sync automático)
TURSO_DATABASE_URL=libsql://<tu-db>.turso.io
TURSO_AUTH_TOKEN=<token-con-permisos-rw>

# ── Dashboard ────────────────────────────────────────────
DASHBOARD_PASSWORD=<contraseña-segura-32-chars>   # vacío = sin autenticación

# ── OAuth Google (opcional) ──────────────────────────────
GOOGLE_CLIENT_ID=<client-id>.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=<client-secret>
OAUTH_REDIRECT_URI=http://localhost:8501
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
> Si usas Streamlit Cloud, define estas variables en *App settings → Secrets*.

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

### 4. Lanzar el dashboard

```bash
streamlit run dashboard/app.py
```

Abre http://localhost:8501.

### 5. Entrenar el clasificador ML

```bash
python -m scraper.ml_classifier train
```

Requiere al menos 50 registros en la BD. El modelo se guarda en
`data/models/sap_classifier.pkl`.

---

## Despliegue

### Opción A — Streamlit Cloud + Turso (recomendado, sin servidores)

1. **Turso**: crea una base de datos en https://turso.tech y obtén
   `TURSO_DATABASE_URL` y `TURSO_AUTH_TOKEN`.

2. **Streamlit Cloud**: https://share.streamlit.io → "New app"
   - Repo: tu fork, branch `master`, main file: `dashboard/app.py`
   - *App settings → Secrets*: añade todas las variables del `.env`

3. **GitHub Actions**: configura los secrets en el repositorio
   (*Settings → Secrets and variables → Actions*) y los workflows
   de `.github/workflows/` corren automáticamente.

| Workflow | Frecuencia | Descripción |
|----------|------------|-------------|
| `scrape.yml` | Diario 06:00 UTC | Bulk mensual (últimos 3 meses) |
| `scrape-daily.yml` | Cada 4 horas | Feed ATOM en vivo |
| `healthcheck.yml` | Cada 6 horas | Verificación de frescura de datos |

También puedes ejecutarlos manualmente desde la pestaña **Actions**.

### Opción B — Docker (autohospedado)

```bash
cp .env.example .env   # edita con tus credenciales
docker compose up -d
```

El `docker-compose.yml` levanta dos servicios que comparten el mismo
volumen de datos: `dashboard` (Streamlit) y `scheduler` (cron de scraping).

Variables recomendadas para despliegue Docker:

```dotenv
API_HMAC_SECRET=<secreto-hmac-32+-chars>
FORWARDED_ALLOW_IPS=<ip-o-rango-del-reverse-proxy>
GF_SECURITY_ADMIN_PASSWORD=<password-admin-grafana>
```

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

Si el token de Turso se compromete:
1. Panel Turso → tu base de datos → **Settings → Tokens** → Revocar
2. Generar nuevo token → actualizar `.env` y secrets de GitHub

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
mypy dashboard/ scraper/ db/ scheduler/ observability/ config/

# Tests con cobertura (umbral: 80%)
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
