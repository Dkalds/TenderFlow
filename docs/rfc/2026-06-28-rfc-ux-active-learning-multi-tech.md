---
rfc: pendiente
title: "UX · Active Learning — más contexto por item, etiquetado multi-tecnología y desglose de probabilidades por clase"
issue: pendiente (crear issue y renumerar)
author: agent:architect
date: 2026-06-28
status: draft
area: web/active-learning · api/feedback · scraper/tech_classifier
supersedes: docs/rfc/2026-06-16-rfc-ux-active-learning.md (partially-implemented; este lo concreta sobre los puntos 2 — multi-clase — y añade el desglose de probabilidades por tecnología)
---

## Contexto

Hoy `https://tenderflowesp.vercel.app/active-learning` (código en
`web/src/app/(dashboard)/active-learning/page.tsx`) muestra una cola de
etiquetado con muy poca información por item y un acto de etiquetado pobre
para el bucle de ML:

1. **Pocos datos por item.** El endpoint `GET /api/v1/feedback/queue`
   (`api/routes/feedback.py:149-205`) sólo devuelve por candidato
   `id_externo`, `titulo`, `confidence` (P(SAP) del binario) y
   `uncertainty`. La query subyacente
   `LicitacionRepository.get_unlabelled_candidates`
   (`db/repositories/licitaciones.py:380-391`) **sí lee `descripcion`** pero
   se descarta antes de responder. No hay CPV, importe, órgano, ni fecha de
   publicación — el etiquetador decide sobre el título solo, lo que produce
   etiquetas ruidosas.
2. **Etiquetado binario "relevante sí/no".** El modelo del producto ya no es
   sólo "es SAP / no es SAP": existe `TechnologyClassifier` multi-label
   (`scraper/tech_classifier.py`) con todas las tecnologías
   (`TECHNOLOGY_KEYWORDS`). Para cerrar el bucle de **ese** clasificador
   necesitamos que el humano diga **qué tecnología** es, no sólo "relevante".
   La tabla `ml_feedback` (`db/schema.py`) sólo guarda `relevante` 0/1
   + `nota`, así que la señal multi-clase se pierde.
3. **El modelo no enseña lo que cree.** Para cada item, el frontend muestra
   una sola probabilidad (la del binario SAP). El `TechnologyClassifier`
   ya devuelve un dict `{label: prob}` con todas las clases por item
   (`predict_one`/`predict_batch` en `scraper/tech_classifier.py:368-475`),
   pero no se expone en la cola. Sin ver "el modelo cree 72 % SAP, 18 %
   Microsoft, 6 % Oracle" el etiquetador no puede ni confirmar ni
   contradecir con criterio.

Marco aplicable:

- **§3.5 (Pydantic v2 DTOs)** y **§3.8 (frontend vía API)** — la solución
  es aditiva sobre `/api/v1/feedback/*` y el registry existente; el frontend
  no fabrica scores (los pide).
- ADR-014 / `docs/frontend-data-invariants.md`: ningún score viene del
  frontend; el desglose por tecnología lo calcula el backend con el
  `TechnologyClassifier` ya entrenado y cacheado en `ml_proba_max` /
  `ml_tecnologias`.

## Decisión

### A. Enriquecer el payload del queue (sin nuevos cálculos en el frontend)

`GET /api/v1/feedback/queue` añade por item, en orden:

- `descripcion` (truncada a 500 chars en el endpoint — el cliente decide
  expandir; reduce payload).
- `cpv`, `importe`, `organo`, `ccaa`, `fecha_publicacion`, `url_origen` —
  todos ya existen en `licitaciones`.
- `tech_scores: { [tech: string]: number }` — diccionario completo de
  probabilidades por tecnología devuelto por
  `TechnologyClassifier.predict_batch()`, redondeado a 3 decimales.
- `tech_predicted: string[]` — tecnologías que superan su threshold (mismo
  shape que `predict_one`).
- `tech_principal: string | null` y `tech_max_proba: number` — para
  resaltar la tecnología "estrella" del item.
- `tech_thresholds: { [tech: string]: number }` — para que el frontend
  pueda señalar visualmente cuándo el score se queda por debajo del corte.

`confidence` (binario SAP) se mantiene para no romper consumidores. Los
campos nuevos viven bajo un sub-objeto opcional `model` para no inflar el
top-level, p. ej.:

```json
{
  "id_externo": "PRO/2024/12345",
  "titulo": "...",
  "descripcion": "…(500 chars)…",
  "cpv": "72260000",
  "importe": 245000.0,
  "organo": "Ayuntamiento de ...",
  "ccaa": "Cataluña",
  "fecha_publicacion": "2026-06-12",
  "url_origen": "https://...",
  "confidence": 0.62,
  "uncertainty": 0.12,
  "model": {
    "tech_scores": {
      "SAP": 0.72, "MICROSOFT": 0.18, "ORACLE": 0.06, "SALESFORCE": 0.02, "...": 0.0
    },
    "tech_predicted": ["SAP"],
    "tech_principal": "SAP",
    "tech_max_proba": 0.72,
    "tech_thresholds": { "SAP": 0.50, "MICROSOFT": 0.60, "...": 0.50 }
  }
}
```

### B. Etiquetado multi-tecnología

El feedback humano deja de ser sólo "relevante sí/no" y pasa a capturar:

1. `relevante: boolean` (compat).
2. `tecnologia: string | null` — clave canónica de `TECH_LABELS`
   (`config/keywords.py`) cuando el humano dice "esto es SAP / Microsoft /
   etc.". `null` significa "ninguna" (ej. ruido / fuera de scope).
3. `tecnologias_secundarias: string[]` (opcional, vacío por defecto) —
   para items multi-tecnología (`SAP + INFOR`).
4. `nota: string` (sin cambios).

UI: en cada card de la cola se reemplazan los dos botones únicos por:

- Una **fila de chips por tecnología**, ordenados por score desc, con barra
  de probabilidad y el threshold marcado. Click sobre una chip = "esta es
  la tecnología principal".
- Botón "Confirmar etiqueta" que envía `relevante=true` + `tecnologia=<la
  marcada>` (+ `tecnologias_secundarias` si se marcaron varias con
  shift-click).
- Botón "Ninguna / no relevante" → `relevante=false`, `tecnologia=null`.
- "Saltar" se mantiene client-side.

### C. Persistencia

Migración Alembic **append-only** (§3.3) `v16_ml_feedback_tecnologia.py`:

```sql
ALTER TABLE ml_feedback ADD COLUMN tecnologia TEXT;
ALTER TABLE ml_feedback ADD COLUMN tecnologias_secundarias TEXT;  -- JSON array
ALTER TABLE ml_feedback ADD COLUMN model_version INTEGER;          -- registry FK suave
CREATE INDEX IF NOT EXISTS idx_ml_feedback_tecnologia ON ml_feedback(tecnologia);
```

`FeedbackRepository.insert` y el DTO `FeedbackRequest` aceptan los campos
nuevos. Validación: `tecnologia` (y cada secundaria) deben pertenecer a
`TECH_LABELS` o ser `null`. El frontend manda lo que recibe; nada de
listas hardcodeadas.

### D. Lo que NO se hace en este RFC

- **No** se cambia el algoritmo de uncertainty sampling. La cola sigue
  usando `SAPClassifier.predict_proba` para ordenar — sólo se **añade** el
  desglose por tecnología sobre los items ya seleccionados.
- **No** se entrena un nuevo modelo. Se reusa `TechnologyClassifier` (ya
  precomputado en `ml_tecnologias` / `ml_proba_max`).
- **No** se cambia el endpoint de `POST /api/v1/feedback` para que sea
  multi-row; sigue siendo un feedback por POST (compat).
- **No** se elimina el campo `tecnologia` actual de la cola — se mantiene
  como hint "lo que ya tenía la tabla" si existe, separado del bloque
  `model.*` (que es el score real del clasificador).

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo (sólo `relevante` + título) | Cero trabajo | Sigue produciendo etiquetas ruidosas y sin señal multi-clase | No resuelve el problema reportado |
| Sólo añadir descripción/CPV/importe al payload | Pequeño cambio | No nutre `TechnologyClassifier` ni explica el modelo | Resuelve sólo §1 |
| Endpoint nuevo `/api/v1/feedback/tech-queue` | Aísla del binario | Duplica auth/idempotency y fragmenta la cola | Mejor un payload aditivo en `/queue` |
| Devolver embeddings + features para "explainability" completa | Máxima transparencia | Payload grande, leak de internals | No es lo pedido; `explain()` ya existe vía otro endpoint si se necesita |
| Capturar la tecnología en `nota` libre | Cero migración | No es procesable; perdemos señal multi-clase | Antipatrón confirmado por el bucle Active Learning → ML |
| **Enriquecer payload + multi-clase + scores por tech (esta)** | Cierra el bucle de tech_classifier y mejora calidad de etiqueta | Una migración + cambios en DTO/UI | Coste bajo, payoff alto |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict (mypy/Pyright) | DTO `FeedbackRequest` gana 2 campos; respuesta del queue gana sub-objeto `model` | Tipar con `Literal[*TECH_LABELS]` / `list[str]` con validador, exportar tipo a `web/src/generated/api` |
| §3.2 Upsert idempotente | Ninguno (el feedback no es upsert; mantiene idempotency-key) | — |
| §3.3 Migraciones append-only | Nueva migración `v16_ml_feedback_tecnologia.py` (ADD COLUMN + INDEX) | Sólo `ADD COLUMN` y `CREATE INDEX IF NOT EXISTS`; nada destructivo |
| §3.4 Auto-marking tests | Nuevos tests bajo `tests/api/test_feedback_*.py` y `tests/web/...` | `conftest.py` auto-marca, sin cambios |
| §3.5 Pydantic v2 DTOs | `FeedbackRequest` y nuevo `QueueItem`/`QueueModelBlock` | Pydantic v2 + `field_validator` sobre `tecnologia` (whitelist) |
| §3.6 HMAC/argon2 auth | Ninguno (se reusa `require_any_auth`) | — |
| §3.8 Frontend vía API | Reforzado: scores vienen sólo del backend; frontend no calcula nada | Marcar el sub-objeto `model` como "estimado por modelo vN" |
| ADR-014 / `docs/frontend-data-invariants.md` | El frontend etiqueta visualmente "Predicción del modelo (vN)" para no confundir con dato observado | Badge en la card; tooltip con `model_version` y `trained_at` |

## Plan de implementación

1. **Backend — endpoint y repos**
   - `db/repositories/licitaciones.py:380-391`: incluir en
     `get_unlabelled_candidates` los campos `descripcion`, `cpv`, `importe`,
     `organo`, `ccaa`, `fecha_publicacion`, `url_origen`, `ml_tecnologias`,
     `ml_proba_max`, `ml_tech_principal` (ya cacheados por
     `precompute-tech`).
   - `api/routes/feedback.py:149-205`: cargar `TechnologyClassifier` (lazy,
     `run_ml`) si no está en cache; para cada item del top-`limit`, calcular
     `predict_batch` y armar el sub-objeto `model`. Si la carga del
     tech_classifier falla, devolver `model: null` por item y loguear
     warning (degradación elegante; nunca romper la cola).
   - `db/schema.py` y nueva migración Alembic `v16_ml_feedback_tecnologia.py`
     con los `ADD COLUMN` descritos.
   - `db/repositories/feedback.py`: `insert(..., tecnologia=None,
     tecnologias_secundarias=None, model_version=None)`.
   - `api/routes/feedback.py` `FeedbackRequest`: añadir `tecnologia` y
     `tecnologias_secundarias` con validador whitelist contra `TECH_LABELS`.

2. **Frontend** (`web/src/app/(dashboard)/active-learning/page.tsx`)
   - Ampliar `QueueItem` con los campos nuevos (`descripcion`, `cpv`,
     `importe`, `organo`, `ccaa`, `fecha_publicacion`, `url_origen`,
     `model?`).
   - Reescribir la card del item:
     - Bloque superior: título + link `url_origen`, badges (organo, ccaa,
       CPV, importe formateado, fecha) y descripción colapsable.
     - Bloque "Predicción del modelo": lista de `tech_scores` ordenada desc
       con barra de % y marca del threshold; chip resaltada para
       `tech_principal`. Indicar `model_version` y `trained_at` en tooltip.
     - Acciones: chips clicables (selección de tecnología principal) +
       shift-click para añadir secundarias; botones "Confirmar etiqueta",
       "Ninguna / no relevante", "Saltar".
   - `submitFeedback` envía `tecnologia` y `tecnologias_secundarias`.
   - Mantener `strategy` (`uncertainty | random`) ya existente.

3. **Regenerar `web/src/generated/api`** (DTO sync).

4. **Tests**
   - `tests/api/test_feedback_queue_model_block.py`: el queue devuelve
     `model.tech_scores` con suma > 0, contiene todas las labels y respeta
     `tech_thresholds`. Degradación cuando el modelo no está en disco.
   - `tests/api/test_feedback_post_multilabel.py`: persistencia de
     `tecnologia`/`tecnologias_secundarias`, validación whitelist
     (422 si label desconocida), backward compat (sin esos campos sigue
     funcionando).
   - `tests/db/test_migration_v16_ml_feedback.py`: migración up/down
     idempotente; índice creado; columnas presentes.
   - `tests/web/active-learning.spec.ts` (o equivalente): render de la
     fila de tech con barras, click → POST con `tecnologia`.

5. **Documentación**
   - `docs/IMPROVEMENT_BACKLOG.md`: tachar punto 2 ("etiquetado
     binario") del RFC `2026-06-16-rfc-ux-active-learning.md` al
     mergear.
   - Nota en `docs/frontend-data-invariants.md` sobre cómo se etiquetan
     los scores predichos en UI ("Predicción del modelo vN").

**Archivos de partida**:
- `web/src/app/(dashboard)/active-learning/page.tsx:29-90, 425-535`
- `api/routes/feedback.py:25-48, 149-205`
- `db/repositories/feedback.py:11-21`
- `db/repositories/licitaciones.py:380-391`
- `db/schema.py` (bloque `ml_feedback`)
- `scraper/tech_classifier.py:368-475` (uso de `predict_batch`)
- `config/keywords.py` (`TECH_LABELS`)
- RFC previo: `docs/rfc/2026-06-16-rfc-ux-active-learning.md`

**Riesgo estimado**: bajo-medio (sólo aditivo; punto crítico es el coste
de inferencia de `TechnologyClassifier` por cola — mitigado leyendo
`ml_tecnologias`/`ml_proba_max` pre-computados cuando existen).
**Tiempo estimado**: 1.5-2 días.

## Acceptance criteria

- [ ] `GET /api/v1/feedback/queue` devuelve, por cada item, los campos
      contextuales (descripcion, cpv, importe, organo, ccaa,
      fecha_publicacion, url_origen) y el sub-objeto `model` con
      `tech_scores`, `tech_predicted`, `tech_principal`, `tech_max_proba`,
      `tech_thresholds`.
- [ ] Si `TechnologyClassifier` no está en disco, el endpoint sigue
      respondiendo con `model: null` por item (degradación) y se loguea
      `tech_classifier_unavailable`.
- [ ] `POST /api/v1/feedback` acepta `tecnologia` y
      `tecnologias_secundarias`, valida contra `TECH_LABELS` (422 si
      label desconocida), y persiste ambos campos.
- [ ] La página `/active-learning` muestra por item: descripción
      colapsable, badges de contexto, lista de tecnologías con % y
      umbral, y permite elegir tecnología principal antes de confirmar.
- [ ] Tooltip/badge en la card identifica `model_version` y `trained_at`.
- [ ] `python scripts/check_frontend_invariants.py` no reporta nuevas
      fabricaciones (los scores vienen del backend).
- [ ] `make lint && make typecheck && make test-unit` en verde.
- [ ] diff-cover ≥ 80 % en líneas nuevas.

## Notas de review

<!-- 2026-06-28T00:00Z agent:architect — borrador inicial -->
