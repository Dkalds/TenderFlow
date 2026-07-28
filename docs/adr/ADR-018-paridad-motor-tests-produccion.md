---
id: ADR-018
title: "Paridad de motor entre la suite de tests y producción"
status: superseded
superseded_by: ADR-021
date: 2026-07-26
deciders: "Daniel Kalitovics"
related:
  - "[[ADR-016-destino-persistencia-supabase]]"
  - "[[ADR-003-migraciones-caseras-plus-alembic]]"
  - "[[ADR-021-retirada-sqlite]]"
tags: [adr, testing, postgres, persistence]
---

# ADR-018 — Paridad de motor entre la suite de tests y producción

> **Superseded por [[ADR-021-retirada-sqlite|ADR-021]] (2026-07-28)** en su
> parte de "el SQLite local sigue siendo una conveniencia de dev intencional".
> La infraestructura de tests sobre Postgres que esta ADR construyó **sigue
> vigente y es la única**: `TEST_DATABASE_URL` pasó de opcional a obligatoria y
> el camino SQLite se borró. El diagnóstico de esta ADR (diez bugs que la suite
> sobre SQLite no podía ver) es lo que justificó el retiro completo.

* **Estado:** Aceptado
* **Fecha:** 2026-07-26

## Contexto

Tras el cutover a Supabase Postgres ([[ADR-016-destino-persistencia-supabase|ADR-016]]),
la suite siguió corriendo sobre ficheros SQLite temporales: `tests/conftest.py`
montaba `tmp_db` y `api_db` sobre `tmp_path / "test.db"` y blanqueaba
`DATABASE_URL`. Más aún, `db/connection.py::is_postgres_backend()` incluía una
regla explícita —"si hay `_DB_PATH_OVERRIDE`, devolver False: los tests siempre
usan SQLite"— de modo que las 32 ramas `is_postgres_backend()` repartidas por
15 archivos **solo se ejercitaban por su lado SQLite**.

El efecto: 2600 tests y ~80 % de cobertura medían un motor que no es el de
producción. Toda diferencia de dialecto quedaba fuera del alcance de CI.

No era una preocupación teórica. Los casos encontrados:

1. **`round()` devolviendo `Decimal`.** Documentado en
   `services/sql_fragments.py::round_sql`: Postgres devuelve `Decimal` donde
   SQLite devuelve float, Pydantic lo serializa como *string*, y el frontend
   rompía con `value.toFixed is not a function`. Llegó a producción.

2. **Seis CHECK de formato de fecha ausentes en producción.** `db/schema.py`
   protege `licitaciones.fecha_publicacion`, `fecha_limite`, `fecha_inicio`,
   `fecha_fin`, `fecha_actualizacion_fuente` y `adjudicaciones.fecha_adjudicacion`
   con `CHECK(... GLOB '????-??-??*')`. `GLOB` es exclusivo de SQLite: al portar
   el schema, ninguna de las seis viajó. Postgres aceptaba `'14/06/2026'` en una
   columna indexada que el código ordena y compara como ISO-8601, mientras
   `test_replace_adjudicaciones_drops_constraint_violation` "demostraba" que la
   fila se rechazaba. Corregido en la migración `v59_pg_date_format_checks`.

3. **`options` de la URL descartados.** `_pg_connect_kwargs()` pasaba su propio
   `options` a `psycopg_pool`, que tiene precedencia sobre la cadena de
   conexión: cualquier `options=` puesto en `DATABASE_URL` se perdía en
   silencio. Corregido fusionando ambos.

## Decisión

**La suite corre contra el mismo motor que producción.**

- `TEST_DATABASE_URL` apuntando a un Postgres activa el camino real: `tmp_db` y
  `api_db` crean un **schema aislado por test** sobre esa instancia.
- El DDL se materializa **una vez por sesión** (`alembic upgrade head` +
  `pg_dump --schema-only`) y cada test lo reproyecta sobre su schema. Aplicar
  las migraciones por test (≈50 tablas) sería inviable en tiempo.
- Sin `TEST_DATABASE_URL` se mantiene el camino SQLite, para no exigir un
  Postgres local a quien solo quiere iterar rápido. **CI usa siempre Postgres**:
  el camino SQLite es una comodidad de desarrollo, no la referencia.
- `is_postgres_backend()` deja de forzar `False` en tests: con
  `set_pg_test_url()` activa devuelve `True`, y las ramas Postgres se ejercitan.

### Regla derivada

Una diferencia de dialecto solo es aceptable si está **detrás de
`is_postgres_backend()` y cubierta por un test en ambos lados**. DDL escrita
para un motor que no viaja al otro (el caso `GLOB`) es un bug, no una
diferencia aceptable.

## Consecuencias

**Positivas:**
- Las diferencias de dialecto pasan a ser detectables en CI en vez de en
  producción.
- El shim `_translate_qmarks` (`db/connection.py`) se vuelve retirable: era lo
  único que sostenía una suite en dialecto SQLite contra una producción
  Postgres. Su eliminación depende de esta ADR, no al revés.

**Negativas:**
- CI necesita un servicio Postgres con pgvector (`pgvector/pgvector:pg16`, ya
  usado por el job `schema-migrations-postgres`).
- La suite es más lenta: crear un schema por test cuesta del orden de medio
  segundo. Si se vuelve un problema, la vía es agrupar por módulo y truncar
  entre tests en vez de recrear el schema.
- El job `test-postgres` es **bloqueante** desde el 2026-07-26: la migración
  se completó (218 fallos + 25 errores → 0). Los ficheros cuyo objeto de prueba
  *es* la capa SQLite/libSQL (`test_documentos_schema_sqlite.py`,
  `test_turso_*.py`) se saltan por convención de nombre — no son deuda de
  migración, son tests de otro motor.

## Bugs de producción que destapó la migración

Ninguno era visible con la suite sobre SQLite. Todos estaban activos en
producción:

| Bug | Efecto en producción |
|---|---|
| `_PgConnAdapter` sin `rowcount` | 24 call-sites (`webhooks`, `api_keys`, `watchlist_rules`, `job_locks`, DLQ, notificaciones…) lanzaban `AttributeError` |
| `_PgConnAdapter.lastrowid` devolvía `rownumber` | `create_user`, alta de webhooks y de reglas de watchlist devolvían un id inventado |
| Shim de paramstyle sin escapar `%` literal | Toda query con `LIKE '...%'` **y** parámetros fallaba. Caso real: la alerta de fallos consecutivos del feed diario, silenciada por un `except: return []` |
| `scheduler/retention.py` sin savepoints | Un fallo en la primera tabla abortaba la transacción y dejaba **todas** las demás sin purgar |
| `db/upsert.py` no capturaba `psycopg.IntegrityError` | Una fila inválida abortaba el lote entero de la licitación en vez de irse a la DLQ |
| `_classify_integrity_error` sin `not-null` | Postgres escribe `not-null` con guion: sus violaciones se clasificaban como `other` |
| `healthcheck` detectaba tabla ausente por `no such table` | Mensaje de SQLite; en Postgres el check nunca se activaba |
| `db/events.py` insertaba `str(actor_id)` en columna `INTEGER` | `InvalidTextRepresentation` con cualquier actor no numérico |
| `users.deactivated_at`, `api_keys.scopes`, `api_keys.user_id` ausentes en Postgres | Listar/desactivar usuarios y el borrado GDPR de claves rotos (migración `v60`) |
| Seis `CHECK` de formato de fecha ausentes | Fechas malformadas aceptadas en columnas indexadas (migración `v59`) |

Además, una diferencia de **calidad** medida, no un bug: el backend de búsqueda
de producción (`tsvector` + `ts_rank_cd`) recupera igual de bien que FTS5
(`hit_rate@5 = 1.000` en ambos) pero ordena peor (MRR 0.689 vs ≈0.78). El eval
RAG ratchea ahora por motor en vez de asumir FTS5.
