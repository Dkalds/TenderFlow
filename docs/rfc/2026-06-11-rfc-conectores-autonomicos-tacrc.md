---
rfc: 20260611-1
title: Fase 5 — Conectores autonómicos (PSCP Catalunya primero) y resoluciones TACRC
issue: N/A (roadmap interno, Crítica 4 cobertura de datos)
author: agent:architect
date: 2026-06-11
status: implemented (v1)
supersedes:
---

## Contexto

[[ADR-009-framework-conectores-multifuente|ADR-009]] estableció el framework de conectores multi-fuente (`scraper/connectors/base.py`:
contrato `Connector` + `run_connector` con cursores, upsert idempotente, DLQ,
resolución de empresas e invalidación de caché) y lo validó con TED
(`scraper/connectors/ted.py`, ~69 avisos en la primera pasada, 38/39 enlazados
al maestro). Quedaron dos huecos de cobertura:

1. **Plataformas autonómicas.** PLACSP no agrega de forma completa ni puntual
   la contratación de las CCAA con plataforma propia. La mayor es **PSCP
   Catalunya** (Plataforma de Serveis de Contractació Pública), que publica su
   histórico completo como open data. Le siguen Euskadi (Open Data Euskadi) y
   otras menores.
2. **Resoluciones de recursos (TACRC).** El Tribunal Administrativo Central de
   Recursos Contractuales publica resoluciones que afectan al ciclo de vida de
   contratos ya ingeridos: suspensiones, anulaciones de adjudicación,
   retroacciones. Hoy somos ciegos a ellas; un contrato "adjudicado" puede
   estar recurrido y la Fase 4 (`contrato_eventos`) no lo refleja.

Además, [[ADR-009-framework-conectores-multifuente|ADR-009]] dejó **pendiente el dedupe cross-fuente**. Con TED el solape
era marginal; con PSCP es estructural: los órganos catalanes publican en PSCP
y una parte también llega a PLACSP. Sin dedupe, las métricas competitivas
(cuota, HHI, renovaciones) contarían el mismo contrato dos veces. Este RFC lo
convierte en bloqueante de la fase.

## Decisión

### 5.1 Conector PSCP Catalunya (`scraper/connectors/pscp.py`)

- Implementa el contrato `Connector` con `source_id = "pscp"`; ids
  namespaced `pscp:<id_natural>` y `fuente='pscp'` (patrón [[ADR-009-framework-conectores-multifuente|ADR-009]]).
- **Transporte**: API Socrata del portal de transparencia de la Generalitat
  (`analisi.transparenciacatalunya.cat`), dataset de publicaciones de la PSCP.
  Paginación SoQL (`$limit`/`$offset` u `$order` + cursor por fecha de
  publicación), filtro incremental `$where` por fecha con 1 día de solape
  (mismo patrón que `_since` en TED). Sin autenticación obligatoria; app token
  opcional vía settings si aparece rate limiting.
- **Regla operativa (lección TED)**: los nombres de dataset y de campos NO se
  fijan en este RFC; el primer paso de implementación es sondear la API viva y
  validar cada campo contra respuestas reales antes de escribir el mapeo.
- Mapeo a `Licitacion`/`ParsedTender` existente: títulos/órganos en catalán se
  ingieren tal cual (el clasificador ML char_wb tolera catalán; ver riesgo en
  Acceptance). Adjudicaciones con NIF cuando el dataset lo exponga →
  resolución de empresas estándar.
- Job incremental diario añadido a `scrape-daily.yml` tras el de TED.

### 5.2 Dedupe cross-fuente (desbloquea el pendiente de [[ADR-009-framework-conectores-multifuente|ADR-009]])

- Nueva tabla `licitaciones_duplicados (licitacion_id TEXT PK, canonical_id
  TEXT NOT NULL, clave_match TEXT, confianza REAL, detectado_en TEXT)` —
  SCHEMA + migración Alembic idempotente (patrón triple-DDL).
- **Clave débil de matching**: órgano normalizado (lower, sin acentos, sin
  formas societarias) + número de expediente nacional extraído del id/campo
  fuente + CPV a 4 dígitos. Match exacto de clave → duplicado con
  confianza 1.0; match de órgano+expediente sin CPV → 0.8 y va a cola de
  revisión humana (reutiliza el patrón `empresa_review_queue`, nueva tabla
  `dedupe_review_queue` o columna status en la propia tabla — decidir en
  implementación, preferencia: status en la propia tabla).
- **Canónico = PLACSP** cuando existe (es la fuente con más detalle de
  adjudicación); si no, la fila más antigua.
- Las consultas analíticas (`services/competitive/*`, materializaciones)
  excluyen filas presentes en `licitaciones_duplicados` como no-canónicas.
  Se centraliza en un helper SQL (`AND l.id_externo NOT IN (SELECT
  licitacion_id FROM licitaciones_duplicados)`) para no repetir la cláusula.
- Job de detección post-ingesta enganchado en `_post_ingestion` del runner
  (solo evalúa filas nuevas de la pasada, no full scan).

### 5.3 Resoluciones TACRC (`scraper/connectors/tacrc.py` + tabla nueva)

- TACRC **no produce licitaciones**: produce resoluciones. No se fuerza en
  `ParsedTender`; se crea un camino de ingesta ligero propio que SÍ reutiliza
  cursores (`ingestion_cursors`, source `tacrc`) y DLQ.
- Nueva tabla `resoluciones_recurso (id INTEGER PK, tribunal TEXT NOT NULL
  DEFAULT 'tacrc', numero_resolucion TEXT NOT NULL, numero_recurso TEXT,
  fecha TEXT, expediente TEXT, organo TEXT, sentido TEXT
  /* estimado|desestimado|inadmitido|desistimiento */, url_pdf TEXT,
  resumen TEXT, licitacion_id TEXT REFERENCES licitaciones(id_externo),
  fecha_extraccion TEXT NOT NULL, UNIQUE(tribunal, numero_resolucion))`.
- **Vinculación a licitaciones**: matching débil por expediente + órgano
  normalizado (la misma normalización que 5.2). Sin match → la resolución se
  guarda igualmente con `licitacion_id NULL` (valor propio: feed de
  jurisprudencia consultable).
- **Integración Fase 4**: una resolución vinculada con sentido `estimado`
  genera un `contrato_eventos` tipo `recurso` (nuevo tipo en `_TIPOS_VALIDOS`
  de `api/routes/eventos.py` y en `services/contract_events.py`), visible en
  la línea de tiempo del frontend sin cambios adicionales (el componente
  `EventosTimeline` hace fallback al tipo crudo si no conoce la etiqueta).
- **Fuente de datos**: índice público de resoluciones del Ministerio de
  Hacienda. Si solo hay HTML+PDF (probable), el conector parsea el índice
  HTML; la extracción del texto del PDF queda fuera de alcance v1 (solo
  metadatos + URL).
- API: `GET /api/v1/resoluciones?organo=&sentido=&desde=` y bloque
  "Recursos" en el detail panel cuando existan resoluciones vinculadas.

### Qué NO se hace en esta fase

- No se retrofitea el pipeline PLACSP al contrato `Connector` (sigue pendiente
  de [[ADR-009-framework-conectores-multifuente|ADR-009]], con sus tests como red de seguridad).
- No se añaden Euskadi ni otras autonómicas: PSCP valida el patrón; las demás
  son copias mecánicas que se priorizarán por volumen real una vez medido el
  solape PSCP↔PLACSP.
- No se hace merge físico de filas duplicadas: solo marcado + exclusión en
  analytics (reversible).
- No se extrae texto completo de PDFs TACRC (v1 = metadatos).

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Scraping HTML de la web PSCP en vez de Socrata | No depende del dataset open data | Frágil, paginación hostil, sin contrato estable | Socrata es API estable, versionada y con histórico completo |
| Merge físico de duplicados cross-fuente (borrar fila no canónica) | Tablas más limpias | Irreversible; pierde el detalle específico de cada fuente; rompe FKs/history | Marcado + exclusión es reversible y auditable |
| Dedupe por similitud fuzzy de títulos | Más recall | Falsos positivos caros (fusionar contratos distintos); coste O(n²) | La clave órgano+expediente+CPV es determinista; fuzzy solo como cola de revisión |
| Forzar TACRC dentro de `ParsedTender` | Reutiliza el 100% del runner | Modelo semánticamente incorrecto (una resolución no es una licitación); contaminaría licitaciones | Tabla propia + reutilización selectiva (cursores, DLQ) |
| Esperar al retrofit PLACSP antes de añadir fuentes | Un solo camino de ingesta | Bloquea cobertura (el valor de negocio) por una refactor interna | El runner ya está probado con TED; el retrofit es ortogonal |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Módulos nuevos `scraper/connectors/pscp.py`, `tacrc.py`, `services/dedupe.py` | Tipados desde el inicio; mypy en pre-commit |
| §3.2 Upsert idempotente | PSCP usa el upsert existente; TACRC nueva tabla con `UNIQUE(tribunal, numero_resolucion)` + INSERT OR REPLACE | Test de roundtrip de idempotencia |
| §3.3 Migraciones append-only | Nuevas v39 (`licitaciones_duplicados`), v40 (`resoluciones_recurso`) | Patrón triple-DDL: SCHEMA + Alembic idempotente (IF NOT EXISTS + guards PRAGMA) |
| §3.4 Auto-marking tests | Ninguno | — |
| §3.5 Pydantic v2 DTOs | Nuevos DTOs para `/resoluciones` | Mismo patrón que `api/routes/eventos.py` |
| §3.6 HMAC/argon2 auth | Ninguno (endpoints tras `require_any_auth`) | — |

## Plan de implementación

1. **Sondeo API viva PSCP** — script desechable que valida dataset id, campos,
   paginación y volumen; fija el mapeo definitivo. (Sin código de producción.)
2. **`scraper/connectors/pscp.py`** + tests con fixtures de respuestas reales
   (patrón `tests/test_connectors.py`).
3. **Dedupe**: migración v39 + `services/dedupe.py` (normalización de órgano,
   extracción de expediente, clave de match, `detect_duplicates(after_id)`) +
   hook en `_post_ingestion` + exclusión en `services/competitive/*`.
4. **Backfill PSCP** (`python -m scraper.connectors.pscp --desde 2024-01-01`)
   y medición del solape real PSCP↔PLACSP → calibra el umbral de confianza.
5. **TACRC**: migración v40 + conector (índice HTML → metadatos) + vinculación
   débil + evento `recurso` en contract_events + endpoint `/resoluciones`.
6. **Scheduler**: jobs incrementales PSCP y TACRC en `scrape-daily.yml`.
7. **Frontend**: badge "Recurrido" + bloque de resoluciones en detail panel;
   filtro por `fuente` en las vistas que ya muestran la columna.

**Archivos de partida**: `scraper/connectors/base.py`, `scraper/connectors/ted.py`,
`db/schema.py`, `db/alembic/versions/v38_contrato_eventos.py` (plantilla),
`services/contract_events.py`, `services/competitive/`, `tests/test_connectors.py`.
**Riesgo estimado**: medio (dependencia de APIs externas no contratadas;
calibración del dedupe necesita datos reales).
**Tiempo estimado**: 4–6 días (PSCP+dedupe 2–3, TACRC 2, scheduler+frontend 1).

## Acceptance criteria

- [ ] `run_connector(PscpConnector())` ingiere incrementalmente con cursor persistente y DLQ; segunda ejecución sin datos nuevos = 0 cambios (idempotencia).
- [ ] Filas PSCP entran con `id_externo` prefijado `pscp:` y `fuente='pscp'`; resolución de empresas las enlaza al maestro.
- [ ] Solape PSCP↔PLACSP medido y documentado; duplicados confianza 1.0 marcados automáticamente; las queries de `services/competitive/` no cuentan duplicados (test con par sintético).
- [ ] Resoluciones TACRC ingeridas con metadatos + URL; vinculadas ≥1 caso real a una licitación existente; resolución estimatoria genera evento `recurso` visible en `GET /licitaciones/{id}/eventos`.
- [ ] Clasificador ML evaluado sobre una muestra PSCP en catalán (precision spot-check manual ≥ razonable); si degrada, se registra issue para re-entrenar con muestra bilingüe.
- [ ] `make lint && make typecheck && make test-unit` pasan en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

**Implementación v1 (2026-06-11, rama `claude/adoring-cray-olrwcr`):**

- **5.1 PSCP**: `scraper/connectors/pscp.py` + `scripts/probe_pscp.py`. El
  entorno de implementación no tenía acceso de red al dominio Socrata, así
  que el paso 1 (sondeo de la API viva) queda materializado como script: el
  dataset se fija por entorno (`PSCP_DATASET_ID`) tras correr el probe, y el
  mapeo usa listas de candidatos por concepto (`_FIELD_CANDIDATES`) que el
  probe contrasta contra el dataset real. El conector falla con mensaje claro
  si el dataset no está configurado.
- **5.2 Dedupe**: migración v39 + `services/dedupe.py`. La cola de revisión
  usa columna `status` en la propia tabla (la preferencia del RFC). Solo los
  `confirmed` se excluyen de analytics; los `pending` cuentan hasta revisión.
- **5.3 TACRC**: migración v40 (incluye rebuild guardado de
  `contrato_eventos` para ampliar el CHECK con `recurso`) +
  `services/resoluciones.py` + `scraper/connectors/tacrc.py`. La URL del
  índice también es config (`TACRC_INDEX_URL`) con `--check` de validación.
- **Scheduler**: pasos en `scrape-daily.yml` condicionados a
  `vars.PSCP_DATASET_ID` / `vars.TACRC_INDEX_URL` y `continue-on-error`.
- **Frontend**: badge "Recurrido" + bloque Recursos en el detail panel y tipo
  `recurso` en el timeline. El filtro por `fuente` del paso 7 no se
  implementó: ninguna vista actual muestra esa columna.
- **Validación de fuentes (2026-06-11, probe ejecutado en máquina local con
  egress HTTP real):**
  - **PSCP — dataset `ybgg-dgi6` validado ✓**. Campos reales confirmados
    contra la API Socrata. Dos mismatches en `_FIELD_CANDIDATES` corregidos:
    - `importe`: `pressupost_licitacio` no existía; campos reales son
      `pressupost_licitacio_sense` (sin IVA) y `pressupost_licitacio_amb`.
    - `importe_adjudicacion`: `import_adjudicacio_sense_iva` no existía;
      campo real es `import_adjudicacio_sense`.
    - Resto de 12 conceptos: OK, primeros candidatos coinciden exactamente.
  - **PSCP — mejoras derivadas del probe**: se aprovechan campos reales que
    el mapeo inicial no usaba (`codi_nuts` → NUTS por fila con fallback ES51,
    `ofertes_rebudes` → `n_ofertas_recibidas`, `data_publicacio_*` de cada
    fase como candidatos de fecha), y el fetch incremental pasa al campo de
    sistema Socrata `:updated_at` — cada fila es una publicación de fase con
    SU propio campo de fecha, y `:updated_at` es el único común y no nulo.
  - **TACRC — `BuscadordeResoluciones.aspx` NO funciona**: SharePoint
    JS-rendered, 0 resoluciones parseadas con lxml. Índice alternativo
    encontrado: **`Resoluciones-Pleno.aspx`** — HTML estático con 17 PDFs
    embebidos; parser extrae 17 resoluciones (exit 0). Actualizado como
    default en `config/settings.py`.
    - Limitación: solo resoluciones doctrinales del Pleno. Las resoluciones
      individuales de recurso (el volumen principal) requieren un índice
      estático aún no identificado (el buscador no es rascable sin JS);
      el conector tiene `--check --dump` para diagnosticar candidatos, y la
      petición real del buscador es localizable en DevTools → Network.
  - **TACRC — parser endurecido con el patrón real de los PDFs publicados**
    (`Recurso NNNN-AAAA (Res NNNN) DD-MM-AAAA.pdf`): número de recurso con
    guion normalizado a `NNN/AAAA`, resolución desde `(Res NNNN)` con año
    inferido y fecha desde el href decodificado (test con URL real).
- **Acceptance pendiente de datos reales**:
  - Backfill PSCP + medición del solape PSCP↔PLACSP.
  - Vinculación de ≥1 caso TACRC real (las 17 resoluciones de Pleno son
    doctrinales; el vínculo depende de expedientes comunes en BD).
  - Spot-check del clasificador en catalán (requiere muestra PSCP ingerida).
  - El resto de criterios quedan cubiertos por tests (`test_connectors_pscp.py`,
    `test_dedupe.py`, `test_resoluciones_tacrc.py`).
