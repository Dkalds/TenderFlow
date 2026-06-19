---
rfc: pendiente
title: Enrutar violaciones de integridad del upsert a la DLQ (recuperabilidad)
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: draft
depends-on: RFC observabilidad de pérdida de filas en upsert (2026-06-16)
---

## Contexto

La DLQ existe **precisamente para no perder fallos de persistencia**. Su propio
docstring lo dice (`db/dlq.py:1-5`):

> *"Cada fallo de scraping (descarga, parseo, **persistencia**) se registra en
> `failed_extractions` en vez de perderse en los logs. Así se pueden reintentar
> manualmente o investigar patrones de fallo."*

`record_failure(run_id, fuente, error, *, scope, payload_ref)` (`db/dlq.py:26`)
deduplica por `(fuente, scope, payload_ref)`, lleva `retry_count` y alimenta el
motor de replay `dlq_retry.py`. El pipeline y los conectores ya la usan para
fallos de **parseo** (`scraper/connectors/base.py:142`: *"una entry que falla al
parsear va a la DLQ y no interrumpe el resto"*).

**Pero los fallos de persistencia de adjudicaciones nunca llegan a la DLQ.** El
write path usa `INSERT OR IGNORE` (`db/upsert.py:150,182`), que **se traga**
cualquier violación de constraint (`CHECK` de fecha v22, FK, NOT NULL) sin lanzar
excepción. Como no hay excepción, nadie llama a `record_failure`: la fila
descartada **no es replayable** por `dlq_retry.py` — se pierde para siempre, justo
lo que la DLQ promete evitar. Y como ambas funciones hacen `DELETE`-then-insert,
un descarte aquí es casi siempre una violación real, no un dedup.

Relación con el *RFC de observabilidad de pérdida de filas en upsert*: aquel hace
los descartes **visibles** (métrica + log + conteo honesto); **este los hace
recuperables** (DLQ + replay). Aquel RFC lo dejó explícitamente flaggeado como
follow-up. Son capas complementarias: *observar → recuperar*. Este RFC **depende**
del de observabilidad (reusa su conteo por `cur.rowcount`).

## Decisión

Sustituir el `INSERT OR IGNORE` ciego del path de adjudicaciones por
**insert explícito + `except sqlite3.IntegrityError` con clasificación**, de modo
que un dedup legítimo se ignore y una violación real vaya a la DLQ.

1. **Clasificar la `IntegrityError`** por el mensaje de SQLite (comportamiento
   documentado y estable):
   - `"UNIQUE constraint failed"` → **dedup benigno** (duplicado intra-XML sobre
     `UNIQUE(licitacion_id, nif, importe_adjudicado)`): ignorar, contar como
     `deduped`. Es el caso que `OR IGNORE` cubría legítimamente.
   - `"CHECK constraint failed"` / `"FOREIGN KEY constraint failed"` /
     `"NOT NULL constraint failed"` → **violación de integridad**: `record_failure(
     run_id, fuente, exc, scope="adjudicacion",
     payload_ref=f"{licitacion_id}:{nif}:{importe_adjudicado}")` → replayable.

2. **Per-fila, sin abortar el batch.** El `try/except` envuelve cada `INSERT` (no
   el batch entero), preservando *"un fallo no interrumpe el resto"* como ya hace
   el path de parseo en los conectores.

3. **Replay idempotente.** `dlq_retry.py` reintenta vía el mismo upsert: una vez
   corregida la causa raíz (p.ej. tras aterrizar el RFC de normalización de
   fechas), la adjudicación se reinserta sin duplicar (DELETE-then-insert +
   `UNIQUE`). El `payload_ref` permite localizar exactamente qué reintentar.

4. **Mantener el `DELETE`-then-insert**: garantiza que dentro de un run el único
   `UNIQUE` posible es el duplicado intra-XML (dedup), no una colisión con datos
   viejos — lo que hace fiable la clasificación.

**Qué NO se hace:**

- **No** se aborta el batch ante una violación (catch per-fila, continuar).
- **No** se envían a la DLQ los dedups `UNIQUE` legítimos (ruido inútil).
- **No** se toca el path de `licitaciones` (`upsert_licitaciones`,
  `ON CONFLICT DO UPDATE`): no descarta en silencio; su fallo de `CHECK` ya lanza
  y aborta (cubierto conceptualmente por el RFC de fechas). Un follow-up podría
  envolverlo también en DLQ per-licitación, pero queda fuera de scope.
- **No** se cambian schema ni constraints.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo (`OR IGNORE`) | Simple | Viola la promesa de la DLQ; pérdida no recuperable | El fallo de persistencia que la DLQ debía capturar se evapora |
| Solo observabilidad (RFC previo) | Visibilidad | No permite replay; hay que re-scrapear todo para recuperar | Insuficiente para recuperación dirigida |
| `OR IGNORE` + revalidar con SELECT post-insert | Sin except | Otra query por fila; no distingue causa; frágil | Caro y poco fiable |
| `except IntegrityError` con clasificación + DLQ (elegida) | Distingue dedup de violación; replayable; per-fila | Acopla a parsing de mensajes de SQLite | Mensajes de SQLite son estables y testeables |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | `db/upsert.py` tipado; `except sqlite3.IntegrityError` explícito | Tipar el helper de clasificación |
| §3.2 Upsert idempotente | **Preservado** — dedup `UNIQUE` se sigue ignorando; el replay reinserta sin duplicar | Test de replay idempotente |
| §3.3 Migraciones append-only | Ninguno (la DLQ y sus columnas ya existen, v31) | — |
| §3.4 Auto-marking tests | Tests nuevos por nombre | — |
| §3.5 Pydantic v2 DTOs | Ninguno | — |
| §3.6 HMAC/argon2 auth | Ninguno | — |

## Plan de implementación

1. Aterrizar primero el *RFC de observabilidad* (conteo por `cur.rowcount`).
2. `db/upsert.py` — en `replace_adjudicaciones[_batch]`: insert explícito por fila
   con `except sqlite3.IntegrityError`; helper `_classify_integrity_error(exc) ->
   "unique" | "check" | "fk" | "notnull" | "other"`; dedup → ignorar; violación →
   `record_failure(scope="adjudicacion", payload_ref=...)`. Propagar `run_id`/
   `fuente` (parámetros nuevos o contexto del pipeline).
3. `scraper/pipeline.py:347,553`, `scraper/connectors/base.py:161` — pasar
   `run_id`/`fuente` al upsert para el `record_failure`.
4. `tests/test_db_upsert.py` + `tests/test_dlq*.py` — adjudicación con fecha no-ISO
   → entra en `failed_extractions` con `scope="adjudicacion"`; duplicado intra-XML
   → NO entra en DLQ (solo dedup); replay tras corregir la causa → reinserta
   idempotente.
5. `docs/runbooks/dlq-replay.md` — añadir el caso `scope="adjudicacion"`.

**Archivos de partida**: `db/upsert.py:139-188`, `db/dlq.py:26-76`,
`scraper/pipeline.py:347,553`, `scraper/connectors/base.py:161`,
`docs/runbooks/dlq-replay.md`.
**Riesgo estimado**: medio — cambia el manejo de errores del hot path de
ingesta. Mitigado por el catch per-fila (no aborta) y por depender del RFC de
observabilidad que ya reestructura el conteo.
**Tiempo estimado**: 1 día (tras el RFC de observabilidad).

## Acceptance criteria

- [ ] Una adjudicación que viola `CHECK`/FK/NOT NULL entra en `failed_extractions`
      con `scope="adjudicacion"` y `payload_ref` localizador.
- [ ] Un duplicado intra-XML (`UNIQUE`) NO entra en la DLQ (solo se deduplica).
- [ ] Una violación no aborta el resto del batch.
- [ ] `dlq_retry.py` reintenta y, corregida la causa, reinserta sin duplicar.
- [ ] `make lint && make typecheck && make test-unit` pasan en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->
