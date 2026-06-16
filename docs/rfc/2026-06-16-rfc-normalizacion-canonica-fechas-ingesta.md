---
rfc: pendiente
title: Normalización canónica de fechas ISO-8601 en el boundary de ingesta CODICE
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: draft
---

## Contexto

El 2026-06-15 se corrigió en producción un bug de fechas (commit `1166964`,
*"normalize CODICE dates to ISO — fixes DD/MM vs MM/DD swap in timeline"*): el
XML CODICE del PLACSP a veces entrega `AwardDate` como `DD/MM/YYYY` (ej.
`14/06/2026`), y `new Date("14/06/2026")` en el frontend interpreta `mes=14` →
fecha inválida/incorrecta en el timeline. El fix añadió `_normalize_date()` en
`scraper/codice_parser.py:74` aplicado a `AwardDate`, `StartDate` y `EndDate`,
más una red de seguridad en el frontend (`web/src/lib/utils.ts::formatDate`) y un
**script manual de corrección** de la BD de producción (commit `6018bc5`).

El fix es correcto pero **incompleto y sin enforcement sistémico**. Quedan cuatro
huecos verificables:

1. **`fecha_publicacion` no se normaliza.** `_issue_date()`
   (`scraper/codice_parser.py:182-191`) devuelve `min(dates)` sobre los
   `IssueDate` **crudos** (sin pasar por `_normalize_date`), y ese valor alimenta
   `fecha_publicacion` (`codice_parser.py:287` → `:299`, idéntico en
   `parse_entry_unfiltered` `:396` → `:408`). Dos defectos encadenados:
   - (a) un `IssueDate` en `DD/MM/YYYY` se persiste crudo en la BD;
   - (b) `min()` sobre strings mezcladas ISO + `DD/MM/YYYY` es una comparación
     **lexicográfica**, así que puede elegir una "fecha de publicación más
     temprana" equivocada **incluso cuando todos los candidatos son válidos**
     (ej. `min("2026-06-14", "15/01/2026") == "15/01/2026"` porque `'1' < '2'`).

2. **`fecha_publicacion` es la fecha más load-bearing del sistema**, y todo su
   uso asume que *orden lexicográfico == orden cronológico* — cierto solo para
   ISO-8601, falso para `DD/MM/YYYY`:
   - `_DEFAULT_SORT = "fecha_publicacion DESC"` — orden por defecto de **todos**
     los listados (`db/repositories/licitaciones.py:73`).
   - **Keyset / cursor pagination**: `fecha_publicacion < cursor_fecha`
     (`licitaciones.py:308`) sobre el índice compuesto
     `(fecha_publicacion DESC, id_externo)` (migración 24 / `v21_missing_indexes`).
   - **Filtros de rango**: `fecha_publicacion >= fecha_desde` /
     `<= fecha_hasta` (`licitaciones.py:149-151, 248-251, 469-471, 569`),
     watchlist (`db/repositories/watchlist.py:28-29`), analytics
     (`db/analytics.py:25`).

   SQLite compara TEXT lexicográficamente. **Una sola fila en `DD/MM/YYYY`**
   corrompe en silencio: el orden por defecto, la paginación por cursor (puede
   **saltar o duplicar filas** entre páginas) y los filtros de rango (la fila cae
   del lado equivocado de la comparación).

3. **Lógica duplicada y sin tests.** `_normalize_date` vive local en el parser
   en lugar de en `shared/dates.py` (que ya existe y es el hogar natural de
   helpers de fecha). `grep` confirma **cero** tests que la referencien: el fix
   recién añadido no tiene cobertura y puede regresionar sin que nada lo detecte.

4. **El schema no valida el formato.** `shared/schemas.py:42,57` tipa las
   columnas de fecha como `Series[Any]` con solo `nullable=True`. No hay check de
   formato, así que una fuga `DD/MM/YYYY` pasa `validate_licitaciones` /
   `validate_adjudicaciones` en silencio.

La red del frontend (`formatDate`) **tapa el síntoma de display** pero no hace
nada por el orden/filtrado/paginación del backend, y el script de corrección
manual es limpieza reactiva que volverá a hacer falta en el próximo campo no
normalizado. Relacionado: el ítem ya cerrado *"Métrica NULL % por campo crítico
en parser CODICE"* (mismo espíritu: robustez del parser ante cambios de schema
del PLACSP).

## Decisión

Establecer **ISO-8601 (`YYYY-MM-DD`) como invariante normalizado del boundary de
ingesta**, garantizado por un único helper compartido + validación de schema +
property tests. La regla: *ninguna fecha cruda del PLACSP entra a la BD sin pasar
por el normalizador, y el schema rechaza cualquier fecha no-ISO.*

Cambios concretos:

1. **Consolidar el normalizador en `shared/dates.py`** como
   `to_iso_date(raw: str | None) -> str | None` (strict-typed, **idempotente**:
   ISO entra → ISO sale). El parser lo importa; se elimina la copia local
   `_normalize_date`. Misma semántica actual: ISO → primeros 10 chars,
   `DD/MM/YYYY`/`DD-MM-YYYY` → `YYYY-MM-DD`, formato desconocido → passthrough +
   `log.debug`.

2. **Enrutar todos los campos de fecha del parser por `to_iso_date`**, en
   `parse_entry` **y** `parse_entry_unfiltered`. Crítico:
   - `_issue_date()`: normalizar cada candidato **antes** de `min()`, para que el
     mínimo sea cronológico, no lexicográfico
     (`min(to_iso_date(d) for d in dates if to_iso_date(d))`).
   - El fallback `fecha_upd` de `fecha_publicacion`: `atom:updated` es un
     timestamp RFC3339 completo; `to_iso_date` lo trunca a `YYYY-MM-DD` para que
     `fecha_publicacion` sea siempre granularidad-día y comparable. Se decide
     explícitamente y se documenta que `fecha_actualizacion_fuente` conserva su
     semántica de timestamp completo (campo distinto, uso distinto).

3. **Enforcement en el schema (`shared/schemas.py`)**: añadir a las columnas de
   fecha un check pandera "valor es null **o** matchea `^\d{4}-\d{2}-\d{2}`". Una
   regresión falla `validate_licitaciones`/`validate_adjudicaciones` **ruidosa**
   en vez de corromper el orden en silencio. El check es string-based y barato;
   se conserva el comportamiento `lazy=True` de producción.

4. **Property tests** (`tests/test_property_dates.py`; auto-marcado `property`
   por nombre vía `conftest.py`, §3.4): round-trip (ISO → misma ISO), `DD/MM/YYYY`
   → ISO equivalente, **idempotencia** (`to_iso_date(to_iso_date(x)) ==
   to_iso_date(x)`), formato inválido → passthrough + log, y un test a nivel
   parser que afirma que `_issue_date` devuelve la fecha cronológicamente más
   temprana sobre candidatos en formatos mezclados.

5. **Backfill idempotente único** (paso separado, **gated por OK humano** §6):
   consolidar el script ad-hoc de corrección en una revisión Alembic
   *append-only* que reescriba con `to_iso_date` cualquier `fecha_*` no-ISO ya
   presente en la BD. El fix de parser+schema (pasos 1-4) aterriza primero y es
   valioso de forma independiente; el backfill limpia el legacy.

**Qué NO se hace:**

- **No** cambiar el tipo de columna a `DATE`. SQLite es dinámicamente tipado; el
  patrón canónico del repo es TEXT-ISO con orden lexicográfico, y los índices
  existentes (`fecha_publicacion DESC`) y la cursor pagination lo asumen.
  Cambiarlo los rompería sin beneficio.
- **No** retirar el safety net `formatDate()` del frontend: queda como
  defensa-en-profundidad para filas legacy hasta que corra el backfill. Se marca
  como temporal en un comentario.
- **No** tocar la semántica de `atom:updated`/`fecha_actualizacion_fuente` más
  allá de lo descrito.
- **No** añadir un `CHECK` constraint de formato en esta fase: requeriría migrar
  y limpiar las filas legacy *antes* (orden de operaciones frágil). Se evalúa
  como tripwire **después** del backfill.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo (solo el fix actual) | Cero trabajo extra | `fecha_publicacion` sigue sin normalizar; `min()` lexicográfico; sin tests ni schema check | No cierra la clase de bug; corrupción silenciosa de orden/paginación persiste |
| Solo añadir `to_iso_date` a `_issue_date` | Mínimo, arregla el campo clave | Deja la lógica duplicada, sin schema check ni property tests; el próximo campo vuelve a fugarse | Trata el síntoma, no el boundary |
| Columna tipo `DATE` + `CHECK` | Tipado fuerte en BD | SQLite no tipa estricto; rompe índices TEXT y cursor pagination; migración pesada con legacy | Invierte costo/beneficio a esta escala |
| Normalizar solo en el frontend (extender `formatDate`) | Sin tocar backend | No arregla orden/filtros/paginación del backend; la BD sigue con formatos mezclados | El bug es de datos, no de presentación |
| Helper compartido + schema check + property tests (elegida) | Cierra la clase de bug en el boundary; enforcement ruidoso; reutilizable | Requiere backfill gated para legacy | — |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Nuevo helper en `shared/` (módulo strict) | Tipar `to_iso_date` estricto desde el inicio; sin `Any` |
| §3.2 Upsert idempotente | **Reforzado** — `to_iso_date` es idempotente; re-ingesta produce el mismo valor ISO | Tests de idempotencia; el upsert sigue re-ejecutable sin duplicar |
| §3.3 Migraciones append-only | El backfill (paso 5) es **nueva** revisión Alembic | Nunca editar revisiones existentes; revisión nueva; OK humano §6 |
| §3.4 Auto-marking tests | `test_property_dates.py` → marker `property` por nombre | No marcar a mano; nombre del archivo dirige el marker |
| §3.5 Pydantic v2 DTOs | `Licitacion`/`Adjudicacion` no cambian de campos; solo se garantiza el formato de los strings de fecha; el check pandera es aditivo (tightening) | Documentar; sin cambio de contrato API↔web |
| §3.6 HMAC/argon2 auth | Ninguno | — |

## Plan de implementación

1. `shared/dates.py` — añadir `to_iso_date(raw: str | None) -> str | None`
   (mover la lógica de `_normalize_date`, mismo regex `_DATE_DMY_RE`). Strict.
2. `scraper/codice_parser.py` — importar `to_iso_date`; eliminar
   `_normalize_date` local; aplicar en `_issue_date` (antes de `min()`), en el
   fallback `fecha_upd` de `fecha_publicacion`, y mantener `AwardDate`/`StartDate`/
   `EndDate`. Idéntico en `parse_entry` y `parse_entry_unfiltered`.
3. `shared/schemas.py` — check pandera `^\d{4}-\d{2}-\d{2}` (o null) en columnas
   de fecha de `LicitacionSchema` y `AdjudicacionSchema`.
4. `tests/test_property_dates.py` — property tests del helper + test parser de
   `_issue_date` con formatos mezclados.
5. (Gated, §6) Revisión Alembic de backfill idempotente que normalice `fecha_*`
   legacy; sustituye el script manual ad-hoc del commit `6018bc5`.
6. Comentario "temporal — defensa en profundidad" en `web/src/lib/utils.ts::formatDate`.

**Archivos de partida**: `scraper/codice_parser.py` (`_normalize_date:74`,
`_issue_date:182`, `parse_entry:287/299`, `parse_entry_unfiltered:396/408`),
`shared/dates.py`, `shared/schemas.py`, `db/repositories/licitaciones.py`
(consumidor de orden/cursor — solo lectura), `web/src/lib/utils.ts`.
**Riesgo estimado**: bajo-medio. Pasos 1-4 son aditivos y aislados; el riesgo
real está en el backfill (paso 5), gated por OK humano y revisión Alembic.
**Tiempo estimado**: 0.5-1 día (pasos 1-4); backfill aparte.

## Acceptance criteria

- [ ] `to_iso_date` vive en `shared/dates.py`, es idempotente y strict-typed; el
      `_normalize_date` local del parser queda eliminado.
- [ ] `fecha_publicacion` se normaliza en ambos parsers; `_issue_date` normaliza
      **antes** de `min()` (verificado por test con formatos mezclados).
- [ ] `validate_licitaciones`/`validate_adjudicaciones` **rechazan** una fila con
      fecha `DD/MM/YYYY` (test de regresión).
- [ ] `tests/test_property_dates.py` cubre round-trip, DMY→ISO, idempotencia y
      formato inválido; queda auto-marcado `property`.
- [ ] `make lint && make typecheck && make test-unit` pasan en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->
