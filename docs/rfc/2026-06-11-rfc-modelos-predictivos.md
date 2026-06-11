---
rfc: 20260611-2
title: Fase 6 — Modelos predictivos: baja ganadora y probabilidad de adjudicación
issue: N/A (roadmap interno, Crítica 5 analítica predictiva)
author: agent:architect
date: 2026-06-11
status: draft
supersedes:
---

## Contexto

Las Fases 1–4 dejaron la analítica en estado **descriptivo accionable**:
maestro de empresas (v35), bajas históricas validadas
(`services/competitive/bajas.py`, par válido = importe>0 ∧ adjudicado>0 ∧
adjudicado ≤ 1.5×importe), cuota/HHI (`mercado.py`), renovaciones
(`renovaciones.py`) y eventos de contrato (v38). El salto pendiente es
**predictivo**: responder "¿con qué baja se va a adjudicar esto?" y "¿qué
probabilidad tengo/tiene X de ganarlo?" antes de que se resuelva.

Infraestructura ML ya existente y reutilizable:

- `db/model_registry.py` (tabla `model_versions`, v16): versionado, métrica
  por versión, activación/rollback.
- `scraper/ml_classifier.py` + `scraper/ml_pipeline.py`: patrón sklearn
  pickle + metadata + threshold sweep + split temporal.
- `scheduler/drift_monitor.py`, `concept_drift.py`, `drift_report.py`:
  monitorización de deriva ya operativa para el clasificador SAP.
- Columna precomputada (`ml_proba`) como patrón de serving barato.

Restricciones de datos relevantes:

- `adjudicaciones.n_ofertas_recibidas` existe (señal fuerte para la baja),
  pero **no hay columna de procedimiento** (abierto/negociado/menor) en
  `licitaciones` — gap a cerrar porque condiciona la distribución de bajas.
- **No observamos a los perdedores**: PLACSP da el nº de ofertas pero no la
  identidad de quienes pujaron y no ganaron. Esto hace imposible entrenar
  honestamente un clasificador empresa-gana-licitación con negativos reales,
  y obliga a acotar el alcance del modelo 2 (ver Decisión).

## Decisión

### 6.1 Modelo de baja ganadora (`services/ml/baja_model.py`) — regresión

- **Target**: `baja = (importe - importe_adjudicado) / importe` sobre los
  pares válidos de `bajas.py` (~misma definición `_VALID_PAIR`, target en
  [0, 1)). Una fila de entrenamiento por adjudicación válida.
- **Features** (sin nuevas dependencias, todo derivable con SQL + sklearn):
  - CPV a 2 y 4 dígitos (categórico), `tipo_contrato`, `ccaa`, `fuente`.
  - `log1p(importe)` y banda de importe (umbrales SARA como cortes).
  - `n_ofertas_recibidas` (cuando exista; missing = categoría propia).
  - Agregados históricos *a fecha de corte* (sin fuga temporal): baja media
    del órgano, del CPV-4 y del par órgano×CPV en los 24 meses previos
    (reutiliza las queries de `bajas_agregadas`/`baja_de_referencia`).
  - HHI del segmento CPV-4×CCAA (de `mercado.concentracion_hhi`) como proxy
    de presión competitiva.
  - Estacionalidad: mes y trimestre de publicación.
- **Estimador**: `HistGradientBoostingRegressor` de sklearn con **pérdida
  cuantílica**, tres modelos (p10/p50/p90) → se sirve un intervalo, no un
  punto. La predicción de negocio es "baja esperada 12–18%, mediana 15%".
- **Validación**: split temporal estricto (entrena hasta T, valida T..T+6m),
  métricas MAE (p50), pinball loss (p10/p90) y **cobertura empírica del
  intervalo** (objetivo: el 80% nominal cubre 75–85% real). Baseline a batir:
  `baja_de_referencia` (media histórica del segmento) — si el modelo no
  mejora el baseline en MAE ≥ 10% relativo, no se activa.
- **Registro y serving**: `register_version(name="baja_model_p50", ...)` etc.
  en `model_versions`; predicción batch nocturna → tabla
  `predicciones_baja (licitacion_id TEXT PK, p10 REAL, p50 REAL, p90 REAL,
  model_version INTEGER, computed_at TEXT)` para licitaciones abiertas (sin
  adjudicación). API: `GET /api/v1/licitaciones/{id}/prediccion-baja` y campo
  embebido en el detail del frontend.

### 6.2 Probabilidad de adjudicación — alcance honesto en dos versiones

**v1 (esta fase): probabilidad de retención de renovaciones.** El único
evento con positivo Y negativo observables es la renovación: el incumbente
de un contrato que vence vuelve a ganar el siguiente análogo (positivo) o lo
gana otro (negativo). Etiquetado: pares (contrato vencido → siguiente
adjudicación del mismo órgano con mismo CPV-4 en ventana ±18 meses, matching
vía maestro de empresas). Features: antigüedad de la relación
órgano-empresa, nº de contratos previos con ese órgano, cuota de la empresa
en el segmento, HHI, baja con la que ganó el contrato original, si hubo
modificaciones/prórrogas (de `contrato_eventos` — proxy de satisfacción).
Estimador: `HistGradientBoostingClassifier` + calibración isotónica (patrón
ya usado en `ml_classifier`). Métricas: PR-AUC, Brier score, ECE. Output de
negocio: en la vista Renovaciones, columna "riesgo de cambio de manos".

**v2 (explícitamente fuera de alcance):** probabilidad genérica
empresa×licitación. Requiere identidades de licitadores no adjudicatarios,
que solo aparecen en actas/resoluciones (TACRC, Fase 5) o en datasets
autonómicos más ricos. Se reevaluará cuando la Fase 5 lleve ≥6 meses
acumulando datos.

### 6.3 Operación

- **Re-entrenamiento**: job mensual en scheduler (`scheduler/jobs/`),
  registra versión nueva en `model_versions` SIN activar; activación manual
  (o auto si mejora todas las métricas vs activa — flag en settings).
- **Drift**: ambos modelos se suscriben a `drift_monitor` (distribución de
  features de scoring vs entrenamiento, PSI por feature); alerta por el canal
  de notificaciones existente.
- **Trazabilidad**: cada fila de `predicciones_*` lleva `model_version`; el
  frontend muestra la versión y fecha del cálculo (anti-"número mágico").

### Qué NO se hace

- Sin deep learning ni dependencias nuevas (sklearn ya está; suficiente para
  tabular con este volumen).
- Sin predicción online por request: serving = batch nocturno + lectura de
  tabla (consistente con el patrón `ml_proba` y el presupuesto SQLite/Turso).
- Sin modelo genérico de probabilidad de ganar (v2, ver arriba).
- Sin optimización de precio de puja (recomendación normativa) — solo
  descripción predictiva del mercado; la decisión de puja es del usuario.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Regresión puntual (solo p50) | Más simple | Un punto sin incertidumbre invita a sobreconfianza en pujas | El intervalo ES el producto; coste marginal bajo (3 fits) |
| Quantile regression forests / LightGBM | Métricas potencialmente mejores | Dependencia nueva; ganancia dudosa a este volumen | sklearn HGB cuantílico cubre el caso sin tocar requirements |
| Clasificador empresa×licitación con negativos sintéticos (empresas del segmento que "podrían haber pujado") | Cubre el caso de uso completo ya | Negativos inventados → probabilidades sin semántica, imposibles de calibrar honestamente | v1 renovaciones tiene etiquetas reales; v2 esperará a datos de licitadores |
| Servicio de inferencia online (FastAPI carga el pickle por request) | Predicciones siempre frescas | Latencia, memoria en el proceso API, complejidad de despliegue | Batch nocturno basta: las licitaciones abiertas cambian a ritmo diario |
| Features de texto (TF-IDF del título/descripción) en el modelo de baja | Posible señal extra | Dimensionalidad alta para pocos datos tabulares; explotación difícil de explicar | Se deja como experimento posterior con ablation; v1 solo features estructuradas |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Nuevos `services/ml/baja_model.py`, `retencion_model.py`, `features.py` | Tipados desde el inicio (numpy/pandas bajo TYPE_CHECKING, patrón ml_classifier) |
| §3.2 Upsert idempotente | `predicciones_baja`/`predicciones_retencion` con PK natural + INSERT OR REPLACE | Test de doble ejecución del batch |
| §3.3 Migraciones append-only | Nuevas v41 (`predicciones_baja`), v42 (`predicciones_retencion`) | Patrón triple-DDL (SCHEMA + Alembic idempotente) |
| §3.4 Auto-marking tests | Tests de entrenamiento marcados slow/integration si tocan dataset real | Fixtures sintéticas pequeñas para unit |
| §3.5 Pydantic v2 DTOs | DTOs para los endpoints de predicción | Mismo patrón rutas existentes |
| §3.6 HMAC/argon2 auth | Ninguno (tras `require_any_auth`) | — |

## Plan de implementación

1. **`services/ml/features.py`** — extracción SQL de features con fecha de
   corte parametrizada (la pieza crítica anti-fuga); tests unitarios con
   `tmp_db`.
2. **Análisis exploratorio reproducible** (script en `scripts/`): distribución
   real del target, volumen de pares válidos por segmento, % de
   `n_ofertas_recibidas` poblado. Decide si hace falta truncar outliers.
3. **`services/ml/baja_model.py`** — entrenamiento p10/p50/p90, validación
   temporal, comparación contra baseline, registro en `model_versions`.
4. **Migración v41 + batch de scoring** (`scripts/score_predicciones.py` +
   job scheduler) + endpoint + intervalo visible en detail panel y en la
   página Renovaciones.
5. **Etiquetado de renovaciones** (`services/ml/retencion_labels.py`):
   construcción de pares vencimiento→sucesor, auditoría manual de una muestra
   de 50 pares antes de entrenar nada.
6. **`services/ml/retencion_model.py`** + migración v42 + columna "riesgo de
   cambio de manos" en Renovaciones.
7. **Drift + re-entrenamiento mensual** enganchados a la infraestructura
   existente.

**Archivos de partida**: `services/competitive/bajas.py`, `mercado.py`,
`renovaciones.py`, `db/model_registry.py`, `scraper/ml_classifier.py`
(patrón), `scheduler/drift_monitor.py`, `db/schema.py`.
**Riesgo estimado**: medio-alto (el riesgo no es de ingeniería sino de señal:
si el MAE no bate al baseline, el entregable de la fase es el baseline servido
por API con honestidad — que ya es útil).
**Tiempo estimado**: 6–8 días (features+EDA 2, baja 2, etiquetas+retención 2–3, ops 1).

## Acceptance criteria

- [ ] `features.py` no tiene fuga temporal: test que verifica que los agregados históricos a fecha T no incluyen filas posteriores a T.
- [ ] Modelo de baja: MAE(p50) mejora `baja_de_referencia` ≥10% relativo en validación temporal out-of-sample; cobertura del intervalo 80% nominal ∈ [75%, 85%]. Si no se alcanza, se documenta y se sirve el baseline (criterio de honestidad).
- [ ] Etiquetas de retención auditadas: precisión del emparejamiento vencimiento→sucesor ≥90% sobre muestra manual de 50.
- [ ] Modelo de retención: PR-AUC > prevalencia +0.15 absoluto y ECE < 0.08 tras calibración.
- [ ] Doble ejecución del batch de scoring = mismas filas (idempotencia).
- [ ] Toda predicción servida expone `model_version` y `computed_at`.
- [ ] Re-entrenamiento registra versión inactiva en `model_versions`; rollback probado con `get_active`.
- [ ] `make lint && make typecheck && make test-unit` pasan en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<pendiente>
