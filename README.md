# Licitaciones SAP — Sector Público España

Aplicación que extrae automáticamente las licitaciones publicadas en la
**Plataforma de Contratación del Sector Público (PLACSP)** relacionadas
con proyectos **SAP** y muestra estadísticas en un dashboard interactivo.

## Arquitectura

```
┌─────────────────────────┐       ┌──────────────────┐
│ PLACSP open data (ZIP)  │──────▶│ scraper/pipeline │
│ hacienda.gob.es         │       │ (descarga+parse) │
└─────────────────────────┘       └────────┬─────────┘
                                           │
                                  filtra SAP keywords
                                           ▼
                          ┌────────────────────────────┐
                          │  SQLite local / Turso cloud │
                          │  (upsert idempotente)       │
                          └──────────────┬─────────────┘
                                         │
                          ┌──────────────┼─────────────┐
                          ▼                            ▼
                ┌──────────────────┐         ┌──────────────────┐
                │ GitHub Actions   │         │ Streamlit UI     │
                │ (cron diario)    │         │ KPIs + gráficos  │
                └──────────────────┘         └──────────────────┘
```

## Estructura

```
licitaciones-sap/
├── config.py                # Keywords SAP, rutas, URLs, límites
├── requirements.txt
├── .env                     # Variables de entorno (NO commitear)
├── db/
│   └── database.py          # SQLite/Turso + upsert + log extracciones
├── scraper/
│   ├── bulk_downloader.py   # Descarga ZIPs mensuales del PLACSP
│   ├── codice_parser.py     # Parser ATOM/CODICE (UBL)
│   ├── filters.py           # Detección de keywords SAP
│   └── pipeline.py          # Orquestación end-to-end
├── dashboard/
│   ├── app.py               # Streamlit dashboard (punto de entrada)
│   ├── auth.py              # Autenticación con rate limiting y timeout
│   ├── data_loader.py       # Carga y enriquecimiento de datos
│   ├── classifiers.py       # CPV, módulos, tipo de proyecto
│   ├── normalize.py         # Normalización de empresas y NIFs
│   ├── forecast.py          # Predicción de tendencias
│   ├── components/          # Cards, KPIs, navegación, tablas
│   ├── filters/             # Estado de filtros y sidebar
│   ├── pages/               # Una página por sección del dashboard
│   ├── theme/               # Tokens de diseño, CSS, plantilla Plotly
│   └── utils/               # Exportación, formato, seguridad
├── scheduler/
│   ├── run_update.py        # Entry point para cron / GitHub Actions
│   ├── healthcheck.py       # Verificación de salud del sistema
│   └── watchlist_alerts.py  # Alertas por watchlist de usuario
├── .github/workflows/
│   ├── scrape.yml           # Bulk mensual (diario 06:00 UTC)
│   ├── scrape-daily.yml     # Feed ATOM en vivo (cada 4h)
│   └── healthcheck.yml      # Healthcheck (cada 6h)
└── data/                    # BD SQLite + ZIPs descargados (gitignored)
```

## Instalación

```bash
cd licitaciones-sap
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

## Configuración

Crea un archivo `.env` en la raíz del proyecto con las siguientes variables:

```dotenv
# Base de datos (elige una opción)

# Opción A — SQLite local (por defecto, sin configuración adicional)
# DB_PATH=data/licitaciones.db

# Opción B — Turso cloud (réplica embebida local + sync automático)
TURSO_DATABASE_URL=libsql://<tu-db>.turso.io
TURSO_AUTH_TOKEN=<token-con-permisos-rw>

# Dashboard — dejar vacío para deshabilitar la autenticación
DASHBOARD_PASSWORD=<contraseña-segura>
```

> **Importante:** `.env` está en `.gitignore`. Nunca lo commitees.
> Si usas Streamlit Cloud, define estas variables en
> *App settings → Secrets* (`secrets.toml`).

## Uso

### 1. Primera carga histórica (ej. desde enero 2024)
```bash
python -m scheduler.run_update --backfill 2024 1
```

### 2. Actualización incremental (últimos 3 meses)
```bash
python -m scheduler.run_update
```
Es **idempotente**: usa upsert por `id_externo`, ejecutarlo varias veces
no duplica registros.

### 3. Lanzar el dashboard
```bash
streamlit run dashboard/app.py
```
Abre http://localhost:8501

### 4. Programar actualización automática (GitHub Actions)

Los workflows ya están incluidos en `.github/workflows/`. Solo necesitas
configurar los secrets en tu repositorio de GitHub:

1. Ve a **Settings → Secrets and variables → Actions**
2. Añade estos secrets:
   - `TURSO_DATABASE_URL` — URL de tu base de datos Turso
   - `TURSO_AUTH_TOKEN` — Token de autenticación de Turso
   - `ALERT_EMAIL_TO` (opcional) — Email para alertas
   - `ALERT_SMTP_USER` / `ALERT_SMTP_PASSWORD` (opcional) — Credenciales SMTP

| Workflow | Frecuencia | Descripción |
|----------|------------|-------------|
| `scrape.yml` | Diario 06:00 UTC | Bulk mensual (últimos 3 meses) |
| `scrape-daily.yml` | Cada 4 horas | Feed ATOM en vivo |
| `healthcheck.yml` | Cada 6 horas | Verificación de frescura de datos |

También puedes ejecutarlos manualmente desde la pestaña **Actions** del repo.

## Seguridad

### Autenticación del dashboard
Cuando `DASHBOARD_PASSWORD` está definida, el dashboard muestra una
pantalla de login con las siguientes protecciones:

- **Rate limiting progresivo:** tras 3 intentos fallidos se activa un
  bloqueo de `2^n` segundos (máximo 60 s), visible en pantalla.
- **Timeout de sesión:** las sesiones expiran automáticamente tras
  **8 horas** de inactividad. Configurable con `SESSION_TIMEOUT_SECONDS`
  en `dashboard/auth.py`.
- **Comparación segura:** se usa `hmac.compare_digest` para prevenir
  ataques de temporización.

### Protecciones generales
| Área | Medida |
|---|---|
| Inyección SQL | Queries parametrizadas con `?`; nombres de columna validados con regex |
| XSS | Todo HTML dinámico escapado con `html.escape()` |
| Validación de URLs | `safe_url()` rechaza esquemas `javascript:` |
| XXE (XML) | Parser lxml con `resolve_entities=False`, `no_network=True` |
| Tamaño de descarga | ZIP ≤ 200 MB, XML ≤ 150 MB por fichero |
| Secretos | Cargados exclusivamente desde variables de entorno / `st.secrets` |

### Rotación de credenciales
Si sospechas que el token de Turso está comprometido:
1. Panel Turso → tu base de datos → **Settings → Tokens** → Revocar
2. Generar nuevo token y actualizar `.env`

## Personalizar las keywords SAP

Editar `config.py` → `SAP_KEYWORDS`. Por defecto incluye:
SAP, S/4HANA, ABAP, Fiori, SuccessFactors, Ariba, Concur, módulos
funcionales (FI, CO, MM, SD, HCM, …), etc.

## Marco legal

Los datos se reutilizan al amparo de:
- **Ley 37/2007** de reutilización de información del sector público
- **RD 1495/2011**
- **Ley 9/2017** de Contratos del Sector Público

Fuente oficial: Plataforma de Contratación del Sector Público
(https://contrataciondelestado.es).

Esta aplicación **no suplanta** a la fuente oficial; sirve únicamente
para fines de análisis estadístico.

## Limitaciones conocidas

- La URL de los ZIP mensuales (`BULK_URL_TEMPLATE` en
  `scraper/bulk_downloader.py`) puede cambiar; verificar contra
  hacienda.gob.es si fallan las descargas.
- El parser CODICE asume estructura estándar; si algún XML viene
  malformado, los entries problemáticos se loggean y se omiten.
- Los datos de meses muy recientes pueden tardar en publicarse
  (típicamente el ZIP del mes M aparece a mediados del mes M+1).

## Despliegue (Streamlit Cloud + Turso)

Setup recomendado, sin servidores propios:

- **Dashboard** en [Streamlit Community Cloud](https://share.streamlit.io)
- **Base de datos** en [Turso](https://turso.tech) (SQLite cloud, tier
  gratuito suficiente para este volumen)
- **Scraping diario** en GitHub Actions (workflows incluidos en el repo)

### 1. Conectar el repo a Streamlit Cloud
1. https://share.streamlit.io → "New app"
2. Repo: tu fork, branch `master`, main file: `dashboard/app.py`
3. *App settings → Secrets*: añadir `TURSO_DATABASE_URL`,
   `TURSO_AUTH_TOKEN` y `DASHBOARD_PASSWORD`
4. Deploy. Se instalará desde `requirements.txt` automáticamente.

### 2. Cron diario en GitHub Actions
Los workflows ya están configurados en `.github/workflows/`. Solo
necesitas añadir los secrets en el repositorio:

Repo → **Settings → Secrets and variables → Actions** →
"New repository secret": `TURSO_DATABASE_URL` y `TURSO_AUTH_TOKEN`.

## Próximos pasos sugeridos

- Añadir alertas por email cuando aparezca una licitación SAP
  por encima de cierto importe.
- Exportación programada a Excel/CSV por correo.
- Autenticación multi-usuario con roles si pasa a uso interno de empresa.


## Arquitectura

```
┌─────────────────────────┐       ┌──────────────────┐
│ PLACSP open data (ZIP)  │──────▶│ scraper/pipeline │
│ hacienda.gob.es         │       │ (descarga+parse) │
└─────────────────────────┘       └────────┬─────────┘
                                           │
                                  filtra SAP keywords
                                           ▼
                                  ┌──────────────────┐
                                  │ SQLite (upsert)  │
                                  └────────┬─────────┘
                                           │
                          ┌────────────────┼─────────────┐
                          ▼                              ▼
                ┌──────────────────┐           ┌──────────────────┐
                │ GitHub Actions   │           │ Streamlit UI     │
                │ (cron diario)    │           │ KPIs + gráficos  │
                └──────────────────┘           └──────────────────┘
```

## Estructura

```
licitaciones-sap/
├── config.py                # Keywords SAP, rutas, URLs
├── requirements.txt
├── db/
│   └── database.py          # SQLite + upsert + log de extracciones
├── scraper/
│   ├── bulk_downloader.py   # Descarga ZIPs mensuales del PLACSP
│   ├── codice_parser.py     # Parser ATOM/CODICE (UBL)
│   ├── filters.py           # Detección de keywords SAP
│   └── pipeline.py          # Orquestación end-to-end
├── dashboard/
│   ├── stats.py             # Cálculos (KPIs, agrupaciones)
│   └── app.py               # Streamlit dashboard
├── scheduler/
│   └── run_update.py        # Entry point para cron / GitHub Actions
├── .github/workflows/       # Scraping + healthcheck automatizado
└── data/                    # BD SQLite + ZIPs descargados
```

## Instalación

```bash
cd licitaciones-sap
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

## Uso

### 1. Primera carga histórica (ej. desde enero 2024)
```bash
python -m scheduler.run_update --backfill 2024 1
```

### 2. Actualización incremental (últimos 3 meses)
```bash
python -m scheduler.run_update
```
Es **idempotente**: usa upsert por `id_externo`, así que ejecutarlo
varias veces no duplica registros.

### 3. Lanzar el dashboard
```bash
streamlit run dashboard/app.py
```
Abre http://localhost:8501

### 4. Programar actualización automática (GitHub Actions)
Los workflows están en `.github/workflows/`. Consulta la sección
[Programar actualización automática](#4-programar-actualización-automática-github-actions)
arriba para configurar los secrets.

## Personalizar las keywords SAP

Editar `config.py` → `SAP_KEYWORDS`. Por defecto incluye:
SAP, S/4HANA, ABAP, Fiori, SuccessFactors, Ariba, Concur, módulos
funcionales (FI, CO, MM, SD, HCM, …), etc.

## Marco legal

Los datos se reutilizan al amparo de:
- **Ley 37/2007** de reutilización de información del sector público
- **RD 1495/2011**
- **Ley 9/2017** de Contratos del Sector Público

Fuente oficial: Plataforma de Contratación del Sector Público
(https://contrataciondelestado.es).

Esta aplicación **no suplanta** a la fuente oficial; sirve únicamente
para fines de análisis estadístico.

## Limitaciones conocidas

- La URL de los ZIP mensuales (`BULK_URL_TEMPLATE` en
  `scraper/bulk_downloader.py`) puede cambiar; verificar contra
  hacienda.gob.es si fallan las descargas.
- El parser CODICE asume estructura estándar; si algún XML viene
  malformado, los entries problemáticos se loggean y se omiten.
- Los datos de meses muy recientes pueden tardar en publicarse
  (típicamente el ZIP del mes M aparece a mediados del mes M+1).

## Despliegue (Streamlit Cloud + GitHub Actions)

Setup recomendado, gratis y sin servidores:

- **Dashboard** corriendo en [Streamlit Community Cloud](https://share.streamlit.io)
- **Scraping diario** en GitHub Actions, que commitea la BD actualizada
- Streamlit Cloud detecta el push y refresca

### 1. Conectar el repo a Streamlit Cloud
1. https://share.streamlit.io → "New app"
2. Repo: `Dkalds/Licitaciones_SAP_DASHBOARD`, branch `master`
3. Main file path: `dashboard/app.py`
4. Deploy. Se instalará desde `requirements.txt` automáticamente.

### 2. Cron diario en GitHub Actions
Ya configurado en [`.github/workflows/scrape.yml`](.github/workflows/scrape.yml):
- Diario a las 06:00 UTC
- Lanza `python -m scheduler.run_update --months 3`
- Hace `git commit + push` de `data/licitaciones.db` si ha cambiado

Para que el workflow tenga permiso de push:
1. Repo → Settings → Actions → General
2. *Workflow permissions* → seleccionar **Read and write permissions**

Lanzar manualmente: pestaña *Actions* → "Scrape PLACSP daily" → *Run workflow*.

### Limitaciones de este setup
- La BD vive en el repo (público) → cualquiera puede descargarla. Como
  los datos ya son públicos en PLACSP no es problema legal, pero
  conviene saberlo.
- Si la BD supera ~50 MB, GitHub avisa; >100 MB rechaza el push.
  Al ritmo SAP actual (~ +30 licitaciones/mes), tardarías años.
- Cada commit del bot añade peso al historial git. Si crece mucho,
  squash-merge anual o `git lfs` para el `.db`.
