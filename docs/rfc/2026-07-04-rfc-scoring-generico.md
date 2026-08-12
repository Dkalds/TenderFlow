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

## Addendum 2026-08-12 — la referencia de `importe` es el mercado abierto

La dimensión `importe` normalizaba contra P10/P90 de **toda** la tabla
`licitaciones`. Medido el 2026-08-11, de sus 1.640.915 filas el 91% son avisos
agregados de PSCP (`PUBLICACIÓ AGREGADA`) sin plazo propio, que nunca fueron
oportunidades individuales. El universo que el Radar puntúa, en cambio, son las
~1.643 vivas (estado abierto y plazo por vencer). Es decir: cada oportunidad se
comparaba contra la distribución de una población en la que no compite.

Desde este cambio la referencia la calcula
`AggregateRepository.importe_percentiles_universo`, que replica exactamente el
predicado de `scoring_candidates`, y la sirve `load_importe_percentiles()` con
`SignalAwareCache`. `importe_percentiles()` (tabla completa) sobrevive como
fallback para cuando el universo vivo tiene menos de 50 importes: ahí una
distribución estable, aunque contaminada, discrimina mejor que una calculada
sobre un puñado de filas. El desenlace (`universo_vivo` / `global` /
`sin_datos`) viaja en la respuesta del endpoint, porque un score calculado
contra el fallback no significa lo mismo que uno calculado contra el mercado
vivo.

**Los scores cambian de valor para todos los usuarios**, y con ellos la
distribución de bandas: es el objetivo del cambio, no un efecto colateral. El
mismo cálculo alimenta ahora `/analytics/pipeline`, así que el KPI "Calientes"
y el Radar dejan de poder discrepar por normalizar contra poblaciones
distintas.

De paso, la ventana histórica de las señales (`_cutoff_iso`) pasa a contar
meses de calendario: con `timedelta(days=months * 30)`, "24 meses" eran 720
días y se comían casi un mes de historia de adjudicaciones sin decirlo.

## Addendum 2026-08-12 — la señal técnica pasa a puntuar

Dimensión nueva `senal_tecnica` (peso por defecto 10). Hasta ahora la
tecnología solo **filtraba** el universo: una licitación con SAP confirmado en
el texto del pliego puntuaba exactamente igual que una sin ninguna evidencia,
en un producto cuya razón de ser es detectar oportunidades de una tecnología.

**Fuentes**, combinadas con `max`:

- `licitacion_tecnologia_pliego.score` — derivada del texto real de los
  pliegos, con términos citables, y sobrevive al clobber de `db/upsert.py`.
- `licitacion_tecnologia_score.probabilidad` — clasificador ML multilabel.

No se usa `licitaciones.ml_proba_max`: el re-scrape la sobreescribe (esa es la
razón de existir de la tabla de pliego). Con el filtro `tecnologia=X` activo la
fuerza es la de X —el ranking es "las mejores oportunidades SAP", no "las
mejores que además son SAP"—; sin filtro, la máxima sobre cualquiera.

La dimensión **es genérica**: no lleva keywords propias, lee tablas de datos y
funciona para cualquier vendor. El guard anti-vendor sigue pasando, y ahora
cubre todo `services/analytics/` que asigne `score`/`banda`, no solo
`scoring.py` — mirando un módulo, el `_simple_score` de `organo_detail.py`
había sobrevivido con sus keywords SAP y sus bandas A/B/C/D, puntuando el
drill-down de órgano con lo que este RFC eliminó. Ese ranking usa ya el motor
real.

**Cobertura y neutralidad**: sin señal, 50% del peso + flag
`sin_senal_tecnica`, como el resto de datos de cobertura propia. Como el
clasificador corre sobre toda la tabla, el flag será raro y una licitación no
técnica puntuará cerca de 0 en esta dimensión: eso es señal ("el clasificador
dice que no lo es"), no un hueco.

**Coste**: se consulta por ids del universo (~1,6 k) en cada request, sin caché
propia. `licitacion_tecnologia_score` tiene una fila por (licitación, label)
sobre la tabla entera, así que el patrón de carga completa de las otras
señales reventaría la memoria del proceso.

**Reparto nuevo**: `importe 20, plazo 15, competencia 20, margen 20, afinidad
15, senal_tecnica 10`. Los 10 puntos salen de importe y competencia, las dos
señales más ruidosas. Los perfiles guardados antes de la dimensión siguen
siendo válidos: sin la clave, `w.get("senal_tecnica", 0)` es 0 y la clave se
omite del desglose (mismo trato que afinidad; una barra a cero se leería como
"sin señal", que es lo contrario de "no la estás puntuando"). En `/mi-perfil`
el slider aparece a 0 para que se pueda activar.

## Addendum 2026-08-12 — la afinidad deja de ser decorativa

Tres cosas la tenían desactivada de facto:

1. **`cpvs` era inescribible**: la columna existía y `get_scoring` la leía,
   pero ningún cuerpo de la API la declaraba —y encima cada `PUT` la
   machacaba con NULL—, así que la similitud por CPV (1.0 exacto / 0.8 por
   división) nunca se activó en producción. Ahora se edita desde `/mi-perfil`.
2. **El matching era por substring**: "sap" daba positivo dentro de
   "pasaporte". Pasa a usar límites de palabra, con el mismo patrón que
   `scraper/filters.py` usa para decidir qué entra a la base.
3. **Solo miraba el título**: ahora también la descripción, que es donde el
   pliego español suele nombrar la tecnología. `descripcion` entra en
   `_SCORING_COLS` como insumo interno; no se expone en `ScoredOpportunity`.

Se elimina el campo `contracts` del perfil de scoring: `get_user_profile` nunca
lo devolvía (no hay tal columna), así que la rama de referencias contractuales
era inalcanzable. `build_portfolio` conserva el parámetro para cuando haya de
dónde sacarlas.

## Addendum 2026-08-12 — el ranking mira los descartes

`GET /analytics/scoring` acepta `exclude_dismissed` (opt-in; solo lo pide el
Radar). Con él, las señales que el usuario descartó salen del universo **antes**
de ordenar y cortar, así que el hueco lo ocupa la siguiente. Filtrándolas en el
cliente sobre el top-24 ya cortado, quien triaba las 24 se quedaba con la
bandeja vacía hasta que cambiara el ranking. El segmento "Descartadas" pasa a
hidratarse por el modo page-aligned (`ids=`), y su contador es el total real y
no la intersección con un top-24 del que ya salieron.

Como la respuesta se cachea 300 s por usuario, `POST`/`DELETE
/radar/dismissals` invalidan las entradas de ese usuario
(`shared.cache.invalidate_user_scoped`). Con backend en memoria y varias
instancias queda staleness residual hasta el TTL; lo cubre el filtro optimista
del cliente.

**Sigue fuera de alcance**: construir el portfolio de afinidad con los pursuits
ganados (el dato ya existe — `pursuits.outcome`, `awarded_amount_eur` — y es la
vía natural para revivir `contracts`), persistir embeddings por licitación, y
un modelo supervisado de "buena oportunidad" con esos mismos labels.

## Notas de review

2026-07-04T00:00Z agent:coder — Implementación directa sobre master según plan acordado con el usuario. Tests verificados localmente. La distribución de bandas cambiará respecto al scoring SAP-centrado — cambio de producto esperado y documentado.
