---
id: ADR-021
title: "Retirada de SQLite como backend soportado — mono-dialecto Postgres"
status: accepted
date: 2026-07-27
deciders: "Daniel Kalitovics"
supersedes: ADR-018
related:
  - "[[ADR-004-sqlite-turso-vs-postgres]]"
  - "[[ADR-016-destino-persistencia-supabase]]"
  - "[[ADR-018-paridad-motor-tests-produccion]]"
  - "[[ADR-020-retirada-turso]]"
tags: [adr, persistence, sqlite, postgres]
---

# ADR-021 — Retirada de SQLite como backend soportado

* **Estado:** Aceptado
* **Fecha:** 2026-07-27
* **Sustituye a:** [[ADR-018-paridad-motor-tests-produccion|ADR-018]] (en su
  parte de "SQLite local sigue siendo conveniencia de dev intencional")

## Contexto

Producción corre sobre Supabase Postgres desde el cutover F3c
([[ADR-016-destino-persistencia-supabase|ADR-016]]). Turso/libSQL se retiró en
[[ADR-020-retirada-turso|ADR-020]]. Lo que quedaba era **SQLite como backend de
desarrollo local**, que ADR-018 declaró explícitamente conveniencia intencional
y no legado a eliminar sin más.

Esa decisión era razonable cuando se tomó. Lo que la invalida no es una
preferencia estética, sino una **restricción de rendimiento medida**.

### Lo que destapó el trabajo de ingesta batcheada (2026-07-27)

`db/upsert.py` enviaba una sentencia por fila contra la BD remota. El motivo
estaba escrito en los comentarios del propio código: se chunkeaba *"para
liberar el write lock entre chunks"* y había un `SAVEPOINT` por fila porque
*"libsql/SQLite invalidan la transacción al primer fallo de constraint"*. El
camino de escritura estaba optimizado para el motor que ya no es el de
producción: en SQLite local lo que importa es la contención del lock; contra
Supabase lo que importa es el round trip, y el código pagaba uno por fila.

Medido sobre 800 filas contra Postgres real: **2201 round trips**, es decir
2.751 por fila. Con un RTT de 80 ms (el orden de magnitud del enlace GitHub
Actions US ↔ Supabase EU) eso son 222 ms por fila — cifra que **coincide con
los ~240 ms/registro observados en producción**, confirmando que el coste
dominante era la latencia de red y no el trabajo de la base de datos. Con el
atraso de ~1.86M filas de PSCP, son ~124 h de viajes puros contra un
presupuesto de `timeout-minutes: 30` cada 4 horas: el conector no se ponía al
día nunca.

El punto arquitectónico: **mientras el código deba servir a dos motores, todo
el SQL se escribe en el mínimo común denominador de ambos**, y ese mínimo común
denominador es precisamente el idioma fila-a-fila. Las primitivas que resuelven
el problema de verdad en el límite —`COPY` a tabla de staging, modo pipeline de
psycopg3— son Postgres-only. El doble motor es, literalmente, el techo de
rendimiento de la ingesta.

### Lo que ya no sostiene el argumento de ADR-018

ADR-018 mantuvo SQLite porque era el camino de dev de bajo roce. Pero la
infraestructura de test sobre Postgres que la propia ADR-018 construyó ya es
completa y **bloqueante en CI**: `tests/conftest.py` levanta un schema aislado
por test, replica el DDL con `pg_dump` tras `alembic upgrade head`, y el job
`test-postgres` pasa en verde. Retirar SQLite es **borrar un camino que CI ya
no necesita**, no construir uno nuevo.

## Decisión

**SQLite deja de ser un backend soportado.** Postgres es el único motor, en
producción, en CI y en desarrollo local.

### Precondición (bloqueante)

`docker-compose.yml` gana un servicio `postgres`, hoy ausente. Sin un Postgres
de dev trivial de levantar, retirar SQLite traslada el coste al desarrollador
y la decisión no se sostiene.

### Alcance

1. Servicio `postgres` en `docker-compose.yml`; `make doctor` lo verifica.
2. Borrado de `db/migrations.py` (1156 líneas, el fichero más grande del repo,
   ya deprecated en su propio docstring y cubierto por Alembic
   `baseline001`..`v32`). Su único llamador de producción era
   `db/schema.py::init_db()`, dentro de la rama que ya se saltaba con Postgres.
3. Borrado del bootstrap SQLite de `db/schema.py`: la constante `SCHEMA` y los
   `_ensure_*_columns()`, que son reconciliación de columnas al estilo SQLite.
   Con Postgres el schema lo crea Alembic y punto.
4. Colapso de las 64 ramas `is_postgres_backend()` a la rama Postgres, y
   borrado de la función.
5. `tests/conftest.py`: `TEST_DATABASE_URL` pasa de opcional a requerida;
   `tmp_db` delega siempre en `_pg_schema`; desaparecen `_SQLITE_ONLY_TOKENS`,
   `_is_sqlite_only` y el skip asociado, junto con los tests que sólo
   describían el comportamiento del otro motor.

### Fuera de alcance, deliberadamente: el codemod de paramstyle

El shim `?`→`%s` (`_translate_qmarks` / `_PgConnAdapter` en `db/connection.py`)
**se conserva por ahora**, aunque el backlog lo listaba junto al resto.

El motivo es de riesgo, no de pereza: son **1123 ocurrencias de `?` en 57
archivos**, y `?` aparece también dentro de regex, docstrings y texto en
español (`¿…?`), así que no admite un reemplazo textual. Bundlear 1123 ediciones
mecánicas en el mismo cambio que la retirada del motor produce un diff
irrevisable y un `git bisect` inútil si algo se rompe.

Cambia además su naturaleza: hasta hoy el shim era **un hack de compatibilidad
entre dos motores**; a partir de esta ADR es **una convención de estilo de SQL
del proyecto** (escribimos qmark, el adaptador traduce). Sigue siendo deuda —
traduce cada sentencia en runtime y ya causó un bug real (el escape de `%`
literal, ver ADR-018) — pero es deuda acotada, cubierta por tests, y su coste se
amortiza ahora sobre lotes en vez de sobre filas gracias al batcheo.

Queda como ítem de backlog separado, ejecutable archivo a archivo con la suite
verde entre cada uno.

## Consecuencias

**A favor**

- Desaparece el techo de rendimiento de la ingesta: `COPY` y el modo pipeline
  quedan disponibles cuando el batcheo por `executemany` no baste.
- ~1500 líneas menos (migraciones caseras + schema SQLite + ramas de dialecto).
- Un solo dialecto que razonar: se acaba la clase de bug "esto funciona en la
  suite y no en producción" que ADR-018 documentó con diez casos reales.
- El desarrollador local ejercita el motor de producción por defecto.

**En contra**

- Levantar el entorno de dev pasa a requerir Docker (o un Postgres accesible).
  Es el coste real de la decisión y se acepta a cambio de la paridad.
- La suite es más lenta contra Postgres (11 min vs 4 min en SQLite), porque
  cada test crea y destruye su schema.
- No hay vuelta atrás barata: el schema SQLite deja de mantenerse desde el
  momento en que se borra.
