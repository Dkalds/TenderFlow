---
rfc: pendiente
title: Observabilidad de pérdida de filas en el upsert de adjudicaciones (INSERT OR IGNORE)
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: implemented
---

## Contexto

El upsert de adjudicaciones incrementa su contador de "persistidas" **sin
comprobar si la fila se insertó de verdad**:

```python
# db/upsert.py — replace_adjudicaciones_batch (157-188), idéntico en replace_adjudicaciones (139-154)
c.execute("DELETE FROM adjudicaciones WHERE licitacion_id = ?", [lic_id])
for adj in adjs:
    c.execute("INSERT OR IGNORE INTO adjudicaciones (...) VALUES (...)", vals)
    total += 1          # ← incrementa aunque OR IGNORE haya insertado 0 filas
except Exception:
    failed += 1         # ← OR IGNORE NO lanza: las violaciones de CHECK/FK nunca llegan aquí
```

`INSERT OR IGNORE` convierte **cualquier** violación de constraint (CHECK de
fecha de v22, FK, NOT NULL) en un descarte **silencioso** de la fila. Y como
ambas funciones hacen `DELETE` de las adjudicaciones de la licitación **antes**
de reinsertar, dentro de un mismo run no hay conflicto `UNIQUE` legítimo salvo
filas duplicadas dentro del propio XML: **un `rowcount == 0` aquí es, casi
siempre, una fila perdida por violación de integridad, no un dedup.**

Consecuencias verificables:

1. **Conteos mentirosos.** El retorno `(total, failed)` —que el docstring vende
   como *"items persisted, licitaciones that failed"*— se consume y se reporta
   como éxito de ingesta en `scraper/pipeline.py:347` y `:553` y en
   `scraper/connectors/base.py:161` (`n_adj, n_adj_failed = ...`). `total`
   sobrecuenta filas que el `CHECK`/FK descartó, y `failed` **no las ve** (no hay
   excepción). Una adjudicación con fecha `DD/MM/YYYY` (caso del RFC de
   normalización de fechas) o un campo requerido ausente se reporta como
   **persistida con éxito**.
2. **Pérdida de datos invisible.** El stack de observabilidad
   (`observability/runtime_metrics.py`) instrumenta el parser
   (`parser_entries_total`, `parser_field_null_total`) y la conexión
   (`sqlite_busy_errors_total`, `db_write_duration_seconds`), pero **no hay nada
   en el boundary de escritura**. Una fila descartada por `OR IGNORE` no produce
   métrica, ni log, ni alerta. El trabajo ya cerrado *"Métrica NULL % por campo
   crítico"* cubre el parseo, no el descarte en el `INSERT`.
3. **Incoherente con el propio patrón del repo.** `scraper/ml_training.py:243`
   (`if cur.rowcount:`) y `services/dedupe.py:228` (`return bool(cur.rowcount)`)
   ya leen `cur.rowcount` tras `INSERT OR IGNORE`. El hot path de adjudicaciones
   es el que no lo hace.

Relación con otros RFCs: el *RFC de normalización canónica de fechas* evita
**producir** un valor que viole el `CHECK`; **este** RFC hace **observable** el
descarte cuando ocurra por cualquier causa (fecha, FK, NOT NULL, schema drift del
PLACSP). Son complementarios, no solapados.

## Decisión

Hacer **honestos los conteos** y **observable la pérdida de filas** en el boundary
de escritura, **sin** quitar el `INSERT OR IGNORE` (la idempotencia de re-ingesta,
§3.2, es correcta y se conserva).

1. **Contar inserciones reales con `cur.rowcount`.** Tras cada `INSERT OR IGNORE`,
   `inserted = cur.rowcount`; acumular `persisted += inserted` y
   `dropped += (1 - inserted)`. Cambiar el retorno a `(persisted, dropped)` con
   semántica documentada (y `failed` sigue contando excepciones reales aparte, o
   se pliega en `dropped` con motivo).

2. **Métrica Prometheus** `upsert_rows_dropped_total{table}` en
   `observability/runtime_metrics.py` (con su `_NoopMetric` fallback en el bloque
   `except ImportError`, como el resto), incrementada por fila descartada.

3. **Log estructurado** por descarte: `log.warning("upsert_row_dropped",
   table="adjudicaciones", licitacion_id=..., nif=...)` para forense — quién se
   cayó y de qué licitación.

4. **Surface en el pipeline.** Los callers (`scraper/pipeline.py:347,553`,
   `scraper/connectors/base.py:161`) loguean `dropped` y, si `dropped > 0`, lo
   elevan a warning visible en Grafana junto a las métricas de parser existentes.
   Tras un `DELETE`-then-insert, `dropped > 0` es señal accionable.

**Qué NO se hace:**

- **No** se quita `INSERT OR IGNORE` ni se cambia a `raise`/DLQ en este RFC. La
  clasificación precisa *dedup `UNIQUE` intra-XML* vs *violación `CHECK`/FK* exige
  `except IntegrityError` inspeccionando el error y enrutado a DLQ — cambio mayor
  → **se flaggea como follow-up**, no se mezcla.
- **No** se tocan schema ni constraints (las `CHECK` de v22 son correctas).
- **No** se toca el path de `licitaciones` (`upsert_licitaciones` usa
  `ON CONFLICT DO UPDATE`, sin descarte silencioso).

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo | Cero trabajo | Conteos mentirosos; pérdida de datos invisible; reporta drops como éxito | No detectable en producción |
| Quitar `OR IGNORE`, dejar que lance | Falla ruidosa | Rompe idempotencia de re-ingesta (§3.2); un dup intra-XML aborta el batch | Va contra el invariante de upsert |
| `OR IGNORE` + `except IntegrityError` con clasificación + DLQ | Distingue dedup de violación; recuperable | Cambio grande; reescribe el manejo de errores del hot path | Scope mayor → follow-up |
| `cur.rowcount` + métrica + log (elegida) | Bajo riesgo; conteos honestos; pérdida observable; usa patrón ya existente del repo | No clasifica la causa (solo cuenta el drop) | La causa se investiga vía log; clasificación queda como follow-up |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | `observability/runtime_metrics.py` y `db/upsert.py` tipados; nueva métrica sigue el patrón | Añadir `_NoopMetric` fallback; tipar el retorno |
| §3.2 Upsert idempotente | **Reforzado** — `OR IGNORE` se mantiene; conteos honestos hacen *testable* la idempotencia (re-run → `persisted=0, dropped=0`) | Test de doble ejecución |
| §3.3 Migraciones append-only | Ninguno (sin cambios de schema) | — |
| §3.4 Auto-marking tests | Tests nuevos en `tests/test_db_upsert.py` por nombre | Sin marcado manual |
| §3.5 Pydantic v2 DTOs | Ninguno | — |
| §3.6 HMAC/argon2 auth | Ninguno | — |

## Plan de implementación

1. `observability/runtime_metrics.py` — `upsert_rows_dropped_total = Counter(...,
   ["table"])` + entrada `_NoopMetric()` en el `except`.
2. `db/upsert.py` — en `replace_adjudicaciones` y `replace_adjudicaciones_batch`:
   leer `cur.rowcount`, acumular `persisted`/`dropped`, emitir métrica + log por
   descarte, ajustar el retorno y los docstrings.
3. `scraper/pipeline.py:347,553` y `scraper/connectors/base.py:161` — consumir y
   loguear `dropped`; warning si `> 0`.
4. `tests/test_db_upsert.py` — adjudicación que viola el `CHECK` (fecha no-ISO) →
   `persisted=0, dropped=1` y `upsert_rows_dropped_total` incrementado; caso feliz
   → `dropped=0`; re-ingesta idéntica → `dropped=0`.
5. (Opcional) `docs/sli-slo.md` / dashboard Grafana — alerta si
   `rate(upsert_rows_dropped_total) > 0`.
6. `docs/IMPROVEMENT_BACKLOG.md` — follow-up: clasificación `IntegrityError`
   (dedup vs violación) + DLQ.

**Archivos de partida**: `db/upsert.py:139-188`, `observability/runtime_metrics.py:106-145`,
`scraper/pipeline.py:347,553`, `scraper/connectors/base.py:161`,
`tests/test_db_upsert.py`.
**Riesgo estimado**: bajo — aditivo (métrica + log + conteo). El único cambio de
comportamiento es la semántica del valor de retorno; los callers se actualizan en
el mismo cambio.
**Tiempo estimado**: medio día.

## Acceptance criteria

- [ ] `replace_adjudicaciones[_batch]` cuentan inserciones reales vía `cur.rowcount`;
      el retorno distingue `persisted` de `dropped`.
- [ ] Una adjudicación que viola un `CHECK`/FK incrementa
      `upsert_rows_dropped_total` y emite `log.warning("upsert_row_dropped", ...)`.
- [ ] Los callers del pipeline loguean `dropped` y avisan si `> 0`.
- [ ] Re-ingesta idéntica → `dropped == 0` (idempotencia, test).
- [ ] `make lint && make typecheck && make test-unit` pasan en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->

2026-06-22T00:00Z agent:claude — Implementado. Estado final:

- ✅ Paso 1: `upsert_rows_dropped_total{table}` (Counter) añadido a
  `observability/runtime_metrics.py` con el `_NoopMetric` fallback del
  `except ImportError`.
- ✅ Paso 2: `replace_adjudicaciones` (`db/upsert.py:143-172`) y
  `replace_adjudicaciones_batch` (`:175-218`) leen `cur.rowcount`,
  acumulan `persisted`/`dropped` y emiten métrica + `log.warning(
  "upsert_row_dropped", ...)` por descarte. Retornos
  `(persisted, dropped)` / `(persisted, dropped, failed)` documentados.
- ✅ Paso 3: Callers actualizados — `scraper/pipeline.py:344-350,554-558`
  y `scraper/connectors/base.py:159-165` desempaquetan `n_dropped`
  y loguean `adj_rows_dropped` si `> 0`.
- ✅ Paso 4: Tests añadidos a `tests/test_db_upsert.py`:
  `test_replace_adjudicaciones_drops_constraint_violation` (acceptance
  criterion central: CHECK violation → `dropped=1` + métrica
  incrementada), `test_replace_adjudicaciones_idempotent_no_drops_on_reingest`,
  `test_replace_adjudicaciones_batch_separates_persisted_from_dropped`.
- ✅ Paso 6: Follow-up de clasificación `IntegrityError` + DLQ
  registrado en `docs/IMPROVEMENT_BACKLOG.md` (P2) apuntando al RFC
  `2026-06-16-rfc-dlq-violaciones-integridad-upsert.md`, que es el RFC
  que escala este trabajo.
- ⏸ Paso 5 (alerta Grafana `rate(upsert_rows_dropped_total) > 0`):
  diferido — opcional según el propio RFC; la métrica ya queda expuesta
  y la regla de alerta puede añadirse cuando se revisen los dashboards.
