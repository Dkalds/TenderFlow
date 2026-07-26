---
id: ADR-018
title: "Paridad de motor entre la suite de tests y producción"
status: accepted
date: 2026-07-26
deciders: "Daniel Kalitovics"
related:
  - "[[ADR-016-destino-persistencia-supabase]]"
  - "[[ADR-003-migraciones-caseras-plus-alembic]]"
tags: [adr, testing, postgres, persistence]
---

# ADR-018 — Paridad de motor entre la suite de tests y producción

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
- **La migración no está completa.** Al activar el motor real afloran fallos
  preexistentes que hasta ahora nadie veía. El job de CI que corre la suite
  contra Postgres arranca como **no bloqueante** y se promueve a bloqueante
  cuando el conteo llegue a cero; cada fallo debe diagnosticarse
  individualmente, porque la corrección casi siempre va en el código de
  producción, no en el test.
