---
rfc: pendiente
title: Normalización canónica de fechas ISO-8601 en el boundary de ingesta CODICE
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: implemented
---

## Contexto

El 2026-06-15 se corrigió en producción un bug de fechas (commit `1166964`,
*"normalize CODICE dates to ISO — fixes DD/MM vs MM/DD swap in timeline"*): el
XML CODICE del PLACSP a veces entrega fechas como `DD/MM/YYYY` (ej. `14/06/2026`)
en vez de ISO. El fix añadió `_normalize_date()` en `scraper/codice_parser.py:74`
aplicado a `AwardDate`, `StartDate` y `EndDate`, más una red de seguridad en el
frontend (`web/src/lib/utils.ts::formatDate`) y un **script manual de corrección**
de la BD de producción (commit `6018bc5`).

**Por qué importa enforcement-wise**: la migración v22 (*"Bloque 3: FK enforcement
+ date CHECK constraints"*) añadió un `CHECK` a **todas** las columnas de fecha de
`licitaciones` y `adjudicaciones`:

```sql
fecha_publicacion TEXT CHECK(fecha_publicacion IS NULL OR fecha_publicacion GLOB '????-??-??*')
-- idem fecha_limite, fecha_inicio, fecha_fin, fecha_actualizacion_fuente (db/schema.py:30-47)
-- idem adjudicaciones.fecha_adjudicacion (db/schema.py:227)
```

Es decir, la BD **rechaza una fecha no-ISO en el momento de escribir** — no la
guarda mal, no la escribe. Una fecha CODICE no normalizada no "ordena mal":
**falla al persistir**. Y los dos caminos de escritura fallan de forma distinta:

- **`adjudicaciones`** — `replace_adjudicaciones[_batch]` usa `INSERT OR IGNORE`
  (`db/upsert.py:150,182`). Un `CHECK` violado se **ignora en silencio**: la
  adjudicación **se pierde** y, peor, `total += 1` la cuenta como persistida
  (miscount). El fix reciente (normalizar `AwardDate`) es justo lo que evita esta
  pérdida silenciosa.
- **`licitaciones`** — `upsert_licitaciones` usa
  `INSERT ... ON CONFLICT(id_externo) DO UPDATE` **sin** `OR IGNORE`, dentro de
  una transacción batch única (`db/upsert.py:124-132`). Un `CHECK` violado
  **lanza `IntegrityError` y aborta el batch entero**.

**El hueco**: el fix normalizó 3 de los 4 campos de fecha que vienen del CODICE.
**`fecha_publicacion` no se normaliza.** Se deriva de `_issue_date()`
(`scraper/codice_parser.py:182-191`), que devuelve `min(dates)` sobre los
`IssueDate` **crudos**, y alimenta `fecha_publicacion`
(`codice_parser.py:287`→`:299`, idéntico en `parse_entry_unfiltered`
`:396`→`:408`). El propio docstring del normalizador reconoce que *"la mayoría de
fechas son ISO (AwardDate, **IssueDate**, StartDate, EndDate) pero algunas llegan
como DD/MM/YYYY"* — o sea, `IssueDate` está expuesto igual que los otros tres.
Dos consecuencias verificables:

1. **Pérdida/abort de ingesta**: una licitación cuyo `IssueDate` llega como
   `DD/MM/YYYY` produce un `fecha_publicacion` no-ISO → viola el `CHECK` de
   `fecha_publicacion` → `IntegrityError` que **aborta el batch** de upsert (no es
   un drop silencioso como en adjudicaciones; es un fallo de transacción).
2. **`min()` lexicográfico**: `_issue_date` compara strings crudas, así que con
   formatos mezclados elige la "fecha de publicación más temprana" equivocada
   (ej. `min("2026-06-14", "15/01/2026") == "15/01/2026"` porque `'1' < '2'`).

Además: `_normalize_date` vive duplicado local en el parser en lugar de en
`shared/dates.py` (que ya existe), y `grep` confirma **cero** tests que lo
referencien — la función que está entre el CODICE y la pérdida de datos no tiene
cobertura. Las filas legacy anteriores a v22 (el `CHECK` no revalida lo ya
escrito) siguen con `DD/MM/YYYY`: de ahí el script de corrección manual y la red
del frontend. Relacionado: ítem cerrado *"Métrica NULL % por campo crítico en
parser CODICE"* (mismo espíritu de robustez ante el schema del PLACSP).

## Decisión

Convertir la **normalización completa de fechas en un invariante del boundary de
ingesta**: ningún campo de fecha del CODICE llega al upsert sin pasar por un único
normalizador compartido y testeado. Las `CHECK` de v22 son el backstop correcto;
este RFC garantiza que el parser **nunca produzca** un valor que las viole.

1. **Consolidar el normalizador en `shared/dates.py`** como
   `to_iso_date(raw: str | None) -> str | None` (strict-typed, **idempotente**:
   ISO entra → ISO sale). El parser lo importa; se elimina la copia local
   `_normalize_date`. Misma semántica: ISO → primeros 10 chars,
   `DD/MM/YYYY`/`DD-MM-YYYY` → `YYYY-MM-DD`, formato desconocido → passthrough +
   `log.debug` (el `CHECK` lo atrapará aguas abajo si no era ISO).

2. **Enrutar todos los campos de fecha del parser por `to_iso_date`**, en
   `parse_entry` **y** `parse_entry_unfiltered`. Crítico: `_issue_date()`
   normaliza cada candidato **antes** de `min()`
   (`min(d for d in (to_iso_date(x) for x in dates) if d)`), cerrando el hueco de
   `fecha_publicacion` y volviendo el mínimo cronológico, no lexicográfico. El
   fallback `fecha_upd` (`atom:updated`, RFC3339 completo) ya pasa el `CHECK`
   (empieza por `YYYY-MM-DD`); se documenta que `fecha_actualizacion_fuente`
   conserva su timestamp completo.

3. **Property tests** (`tests/test_property_dates.py`; auto-marcado `property`,
   §3.4): round-trip (ISO → misma ISO), `DD/MM/YYYY` → ISO, **idempotencia**,
   formato inválido → passthrough+log; test parser de `_issue_date` con formatos
   mezclados; **test de regresión** de que un `IssueDate` `DD/MM/YYYY` ahora
   produce un `fecha_publicacion` ISO que pasa el `CHECK` (sin abort de batch).

4. **(Secundario, defensa en profundidad)** Check pandera de formato en columnas
   de fecha de `shared/schemas.py`. Nota: el `CHECK` de la BD ya es el enforcement
   primario en escritura; el valor añadido del check pandera es el **camino de
   lectura analítico** (DataFrames desde Parquet/DuckDB, que no tienen `CHECK`).
   Prioridad baja; puede diferirse a un ítem aparte.

5. **(Gated, §6)** Backfill idempotente: consolidar el script ad-hoc (commit
   `6018bc5`) en una revisión Alembic *append-only* que normalice con
   `to_iso_date` las filas `fecha_*` legacy anteriores a v22. Aterriza después de
   los pasos 1-3.

**Qué NO se hace:**

- **No** tocar las `CHECK` de v22 ni los tipos de columna: son correctas y
  deseadas; este RFC las complementa garantizando que el parser no genere valores
  que las violen.
- **No** retirar el safety net `formatDate()` del frontend: defensa en
  profundidad para filas legacy hasta que corra el backfill (marcar como temporal).
- **No** arreglar aquí el **miscount de `INSERT OR IGNORE`** en
  `replace_adjudicaciones_batch` (`total += 1` cuenta filas que el `CHECK` ignora).
  Es un defecto real pero de scope distinto → se **flaggea** como ítem nuevo de
  backlog para no mezclar.
- **No** añadir un `CHECK` más estricto (validación de fecha real, no solo shape
  `GLOB`): fuera de scope; el shape actual basta para el orden lexicográfico.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo (solo el fix actual) | Cero trabajo | `fecha_publicacion` sigue sin normalizar → abort de batch ante `IssueDate` DD/MM/YYYY; `min()` lexicográfico; sin tests | No cierra la clase de bug; el campo más usado sigue expuesto |
| Solo normalizar `_issue_date` | Mínimo; cierra el campo clave | Deja lógica duplicada, sin tests ni consolidación; el próximo campo vuelve a exponerse | Trata el síntoma, no el boundary |
| Relajar/quitar las `CHECK` y ordenar en app | Sin abort de batch | Pierde el backstop de integridad; reintroduce el riesgo de orden lexicográfico que las `CHECK` previenen | Va en contra de v22 |
| Normalizar solo en frontend | Sin tocar backend | No evita el abort de ingesta ni el drop silencioso de adjudicaciones | El bug es de ingesta, no de presentación |
| Helper compartido + tests + cierre del hueco `_issue_date` (elegida) | Cierra la clase de bug en el boundary; reutilizable; con cobertura | Backfill legacy gated | — |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Nuevo helper en `shared/` (strict) | Tipar `to_iso_date` estricto; sin `Any` |
| §3.2 Upsert idempotente | **Reforzado** — `to_iso_date` es idempotente y evita que un `CHECK` violado aborte el batch (licitaciones) o descarte filas (adjudicaciones) | Tests de idempotencia + regresión del `CHECK` |
| §3.3 Migraciones append-only | Las `CHECK` ya existen (v22); el backfill es **nueva** revisión Alembic | Nunca editar revisiones; revisión nueva; OK humano §6 |
| §3.4 Auto-marking tests | `test_property_dates.py` → marker `property` por nombre | No marcar a mano |
| §3.5 Pydantic v2 DTOs | DTOs no cambian de campos; solo se garantiza formato de strings de fecha | Sin cambio de contrato API↔web |
| §3.6 HMAC/argon2 auth | Ninguno | — |

## Plan de implementación

1. `shared/dates.py` — añadir `to_iso_date` (mover la lógica de `_normalize_date`,
   mismo `_DATE_DMY_RE`). Strict.
2. `scraper/codice_parser.py` — importar `to_iso_date`; eliminar `_normalize_date`
   local; normalizar en `_issue_date` (antes de `min()`) y mantener `AwardDate`/
   `StartDate`/`EndDate`; idéntico en ambos `parse_entry*`.
3. `tests/test_property_dates.py` — property tests + test parser de `_issue_date`
   con formatos mezclados + regresión del `CHECK` de `fecha_publicacion`.
4. (Secundario) `shared/schemas.py` — check pandera de formato (camino analítico).
5. (Gated §6) Revisión Alembic de backfill que sustituye el script del commit
   `6018bc5`.
6. `docs/IMPROVEMENT_BACKLOG.md` — ítem nuevo: miscount de `INSERT OR IGNORE` en
   `replace_adjudicaciones_batch`.
7. Comentario "temporal — defensa en profundidad" en `web/src/lib/utils.ts::formatDate`.

**Archivos de partida**: `scraper/codice_parser.py` (`_normalize_date:74`,
`_issue_date:182`, `parse_entry:287/299`, `parse_entry_unfiltered:396/408`),
`shared/dates.py`, `db/upsert.py:124-188` (caminos de escritura — solo lectura),
`db/schema.py:30-47,227` (CHECK — solo lectura), `shared/schemas.py`,
`web/src/lib/utils.ts`.
**Riesgo estimado**: bajo-medio. Pasos 1-3 son aditivos y aislados; el riesgo
real está en el backfill (paso 5), gated por OK humano.
**Tiempo estimado**: 0.5-1 día (pasos 1-3); backfill aparte.

## Acceptance criteria

- [ ] `to_iso_date` vive en `shared/dates.py`, es idempotente y strict-typed; el
      `_normalize_date` local del parser queda eliminado.
- [ ] `fecha_publicacion` se normaliza en ambos parsers; `_issue_date` normaliza
      **antes** de `min()` (verificado por test con formatos mezclados).
- [ ] Test de regresión: un `IssueDate` `DD/MM/YYYY` produce un `fecha_publicacion`
      ISO que pasa el `CHECK` (sin `IntegrityError` ni abort de batch).
- [ ] `tests/test_property_dates.py` cubre round-trip, DMY→ISO, idempotencia y
      formato inválido; queda auto-marcado `property`.
- [ ] `make lint && make typecheck && make test-unit` pasan en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->

2026-06-22T00:00Z agent:claude — Implementado. Estado final:

- ✅ Paso 1: `to_iso_date` vive en `shared/dates.py` (strict-typed, idempotente).
- ✅ Paso 2: `scraper/codice_parser.py` importa `to_iso_date` y lo aplica a
  `AwardDate`, `StartDate`, `EndDate` y dentro de `_issue_date` antes de
  `min()`; la copia local `_normalize_date` quedó eliminada. Ambos
  `parse_entry` y `parse_entry_unfiltered` cubiertos.
- ✅ Paso 3: `tests/test_property_dates.py` cubre el contrato de
  `to_iso_date` (round-trip, DMY→ISO, idempotencia, passthrough); este RFC
  añade además `tests/test_codice_parser.py::TestDateNormalization` con
  el test de regresión end-to-end del CHECK (acceptance criterion 3).
- ✅ Paso 6: ítem nuevo en `docs/IMPROVEMENT_BACKLOG.md` (P2) sobre el
  miscount de `INSERT OR IGNORE` en `replace_adjudicaciones_batch`.
- ✅ Paso 7: comentario "temporal — defensa en profundidad" añadido a
  `web/src/lib/utils.ts::formatDate` con el plan de retirada.
- ⏸ Paso 4 (pandera): diferido por baja prioridad, según el propio RFC.
- ⏸ Paso 5 (revisión Alembic de backfill): gated por OK humano (§6).
