---
rfc: 2026-07-04
title: Scoring de oportunidades genérico (sin tecnología hardcodeada)
issue: N/A
author: agent:coder
date: 2026-07-04
status: implemented
---

## Contexto

El score comercial 0-100 de `services/analytics/scoring.py` tenía **45 de 100 puntos atados a SAP**: módulos SAP en el título (20 pts), keywords de portfolio SAP (15 pts) y boost S/4HANA (10 pts). Además la dimensión "competencia" era un placeholder que siempre devolvía 0. Esto hacía que el scoring solo fuera útil para licitaciones de tecnología SAP, y que licitaciones de cualquier otro dominio (obras, suministros, servicios generales) quedaran sistemáticamente infravaloradas.

El objetivo es que la puntuación sea **genérica** — válida para cualquier tipo de pliego — y que las nuevas dimensiones usen **datos históricos reales** disponibles en la base de datos.

## Decisión

### Dimensiones nuevas (pesos en `settings.SCORING_WEIGHTS`, suman 100)

| Key desglose | Peso default | Cálculo |
|---|---|---|
| `importe` | 25 | Ratio P10-P90 global. Sin importe → 50% neutral + flag `sin_importe`. |
| `plazo` | 15 | Escalones por días hasta vencimiento. Sin `fecha_limite` → 50% neutral + flag `sin_plazo`. |
| `competencia` | 25 | Media de `n_ofertas_recibidas` por segmento CPV-4 en 24 meses (n≥3). Fallback: media global → neutral + flag. Fracción: `1 - clamp((media-1)/9, 0, 1)`. |
| `margen` | 20 | `predicciones_baja.p50` → fallback baja media histórica CPV-4 → media global → neutral + flag. Fracción: `1 - min(baja/0.40, 1)`. |
| `afinidad` | 15 | Solo si `SCORING_AFINIDAD_KEYWORDS` no está vacío: `min(hits/3, 1)` casefold-substring sobre título. Si vacío, la key se omite y su peso se redistribuye. |
| `riesgo` | 0 a -10 | Penalización pura: `sin_importe` -5, `sin_titulo` -3, `sin_plazo` -2. |

Total = suma dimensiones + riesgo, clamp [0, 100].

### Política dato-faltante = neutral

Los datos de cobertura propia (`sin_prediccion`, `sin_historico_competencia`) producen valor neutral (50% del peso) pero **no penalizan** en riesgo. Solo los datos del pliego en sí (falta de importe, título o plazo) penalizan, porque son señales de calidad del contratante.

### Redistribución de afinidad

Si `SCORING_AFINIDAD_KEYWORDS` está vacío (default), la dimensión `afinidad` se omite del desglose y su peso (15 pts) se redistribuye proporcionalmente entre las demás dimensiones, garantizando que la suma siempre sea 100.

### Constantes SAP eliminadas

`_SAP_MODULES`, `_SAP_SERVICES_PORTFOLIO` y `_S4HANA_KEYWORDS` han sido eliminadas del módulo de scoring. Un test de guardia verifica que no reaparez.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Mantener scoring SAP + añadir scoring genérico como alternativa | Retrocompat inmediata | Dos sistemas divergentes, duplicación de lógica | Aumenta deuda técnica |
| HHI como medida de concentración de mercado | Más sofisticado | Requiere datos de empresas por segmento, no disponibles al arranque | Diferido como extensión futura |
| Modelo ML para score | Alta precisión | Requiere labeled data de "buenas oportunidades" no disponibles | Fuera del alcance de esta fase |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Afecta `services/analytics/scoring.py` y nuevo `scoring_signals.py` | Tipado completo con dataclasses frozen, sin `Any` sin justificar |
| §3.2 Upsert idempotente | Ninguno — solo lectura | — |
| §3.3 Migraciones append-only | Ninguno — sin tablas nuevas | — |
| §3.4 Auto-marking tests | Ninguno — naming convención respetado | — |
| §3.5 Pydantic v2 DTOs | Shape de `desglose` cambia (keys internas); el contrato `{score, band, desglose, risk_flags}` es estable | `desglose` es `Record<string, number>` en TS — el front renderiza dinámicamente |
| §3.6 HMAC/argon2 auth | Ninguno | — |
| §3.8 Frontend no fabrica analítica | Ninguno — `DESGLOSE_LABELS` es solo un map presentacional de keys a strings | — |

## Plan de implementación

1. `config/settings.py` — `SCORING_WEIGHTS` y `SCORING_AFINIDAD_KEYWORDS` + `@model_validator`.
2. `services/analytics/scoring_signals.py` (nuevo) — `CompetenciaStats`, `MargenStats`, loaders con `SignalAwareCache`, `clear_scoring_signals_cache()`.
3. `services/analytics/scoring.py` — eliminar constantes SAP; añadir `_ScoringContext`, `_effective_weights`, `_build_context`, reescribir `_score_row`.
4. `tests/conftest.py` — registrar `clear_scoring_signals_cache()` en la fixture autouse.
5. `tests/test_analytics_scoring.py` — mantener tests existentes con parches de loaders; añadir tests de competencia, margen, afinidad, redistribución de pesos, riesgo máximo y guardia SAP.
6. `web/src/components/detail-panel.tsx` — `DESGLOSE_LABELS` presentacional con fallback a key raw.
7. `api/routes/analytics.py` — corregir descripción del parámetro `band`.
8. `docs/rfc/2026-07-04-rfc-scoring-generico.md` — este documento.
9. `docs/IMPROVEMENT_BACKLOG.md` — marcar ítem resuelto si corresponde.

**Archivos de partida**: `services/analytics/scoring.py`, `config/settings.py`, `tests/test_analytics_scoring.py`
**Riesgo estimado**: medio (cambio en lógica de scoring que afecta la distribución de bandas)
**Tiempo estimado**: 1 día

## Acceptance criteria

- [x] Las constantes `_SAP_MODULES`, `_SAP_SERVICES_PORTFOLIO`, `_S4HANA_KEYWORDS` no existen en `scoring.py`.
- [x] Las dimensiones del desglose son `{importe, plazo, competencia, margen, riesgo}` (+ `afinidad` si hay keywords).
- [x] `_effective_weights` garantiza suma == 100 con y sin afinidad.
- [x] BD local sin adjudicaciones/predicciones → scores neutrales comparables, sin crash.
- [x] `settings.SCORING_WEIGHTS` con claves incorrectas o suma ≠ 100 falla al arrancar.
- [x] `SCORING_AFINIDAD_KEYWORDS` vacío → `"afinidad"` no aparece en el desglose.
- [x] `make lint && make typecheck && pytest tests/test_analytics_scoring.py -q` pasan.

## Extensión futura (diferida)

- **HHI (Herfindahl-Hirschman Index)** por segmento CPV como medida de concentración de mercado, más preciso que la media de ofertas pero requiere datos de importe por licitador.
- **Retroalimentación de resultado**: ponderar positivamente contratos que la empresa ha ganado en el pasado (requiere matching empresa↔usuario).

## Notas de review

2026-07-04T00:00Z agent:coder — Implementación directa sobre master según plan acordado con el usuario. Tests verificados localmente. La distribución de bandas cambiará respecto al scoring SAP-centrado — cambio de producto esperado y documentado.
