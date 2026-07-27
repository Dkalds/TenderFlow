---
id: ADR-020
title: "Retirada de Turso/libSQL como backend cloud"
status: accepted
date: 2026-07-26
deciders: "Daniel Kalitovics"
related:
  - "[[ADR-004-sqlite-turso-vs-postgres]]"
  - "[[ADR-016-destino-persistencia-supabase]]"
  - "[[ADR-018-paridad-motor-tests-produccion]]"
tags: [adr, persistence, cutover]
---

# ADR-020 — Retirada de Turso/libSQL como backend cloud

* **Estado:** Aceptado
* **Fecha:** 2026-07-26

## Contexto

ADR-016 movió producción a Supabase Postgres. Desde entonces, Turso/libSQL
(el backend cloud descrito en ADR-004) seguía presente en el código y en la
infraestructura como reliquia del backend anterior: `TURSO_DATABASE_URL` y
`TURSO_AUTH_TOKEN` pasaban por los 8 workflows de GitHub Actions y por
`render.yaml`, `db/connection.py` mantenía `is_turso_backend()` y un pool
`Queue`-based completo para el driver `libsql`, y `scripts/backup_db.py`
sabía hacer backup contra Turso.

`is_turso_backend()` devolvía siempre `False` en cuanto `DATABASE_URL`
apuntaba a Postgres ("Postgres tiene precedencia" era el comentario en el
código). Eso ocultó un bug real: `scraper/tech_classifier.py::train_from_db()`
condicionaba el origen de lectura en `is_turso_backend()`, así que con
Postgres en producción la condición era siempre falsa y la función caía al
`sqlite3.connect()` de más abajo — entrenando el clasificador de tecnología
contra un fichero SQLite local vacío en vez de los datos reales de
producción. Nadie lo detectó porque los tests mockeaban la condición sin
ejercitar nunca un backend real (el hueco que ADR-018 vino a cerrar para el
resto de la suite).

La ventana de rollback del cutover (≥14 días, ver
`docs/runbooks/migracion-persistencia.md`) ya está superada, y la suite corre
contra Postgres real con `test-postgres` bloqueante (ADR-018), así que ya no
hace falta conservar Turso como red de seguridad.

### Por qué este ADR no retira SQLite

El plan original de esta fase incluía además borrar `db/migrations.py`, el
shim regex `?`→`%s` (`_translate_qmarks` en `db/connection.py`) y colapsar el
branching `is_postgres_backend()` a mono-dialecto. Al ejecutar se descubrió
que esas tres piezas **no son legado de Turso** — son lo que sostiene el
backend SQLite local de desarrollo que ADR-018 declaró explícitamente una
conveniencia intencional, no algo a eliminar sin más:

- `db/migrations.py::apply_pending()` sigue siendo el camino de esquema real
  para el fichero SQLite de dev (`db/schema.py::init_db()` lo invoca).
- El shim `?`→`%s` es lo único que permite que el mismo SQL sirva a SQLite
  (que requiere `?`) y a Postgres (que requiere `%s`) sin una segunda copia
  de cada query.
- Retirar cualquiera de las dos rompe el flujo de desarrollo local, que hoy
  no tiene alternativa: `docker-compose.yml` no declara un servicio Postgres.

Borrarlas habría equivalido a retirar SQLite como backend soportado — una
decisión de alcance mayor que "retirar Turso", que requiere autorización
explícita del usuario y, como prerrequisito práctico, un servicio Postgres en
`docker-compose.yml` para que el desarrollo local siga siendo posible. Esa
decisión queda diferida como ítem de backlog separado (P1, "Borrar
`db/migrations.py`, matar el shim de paramstyle y colapsar el branching de
dialecto") en `docs/IMPROVEMENT_BACKLOG.md`.

## Decisión

**Se retira Turso/libSQL cloud por completo**, y solo eso:

- `db/connection.py`: eliminados `is_turso_backend()`, la rama libsql de
  `connect_read()` (`TURSO_REPLICA_URL`), el pool `Queue`-based de
  `_get_conn()`/`_return_conn()`/`close_pool()` y `_health_check()` (solo
  tenían sentido para el pool de Turso).
- `config/settings.py`: eliminados `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`,
  `TURSO_LOCAL_DB`, `TURSO_REPLICA_URL` y sus validators
  (`_validate_turso_pair`, `_validate_turso_url_scheme`).
- Los 8 workflows de GitHub Actions, `render.yaml` y `.env.example`: sin
  ninguna referencia a `TURSO_*`.
- `scripts/backup_db.py::backup_turso()` eliminada, junto al flag `--turso`.
- `observability/logging.py`: `TURSO_AUTH_TOKEN` fuera de
  `_SENSITIVE_ENV_VARS` (ya no existe el secreto que redactar).
- Bug corregido: `scraper/tech_classifier.py::train_from_db()` ahora
  condiciona en `is_postgres_backend()`.

**Se conserva intacto**, explícitamente:

- El backend SQLite local de desarrollo (ADR-018).
- `db/migrations.py` y el shim `?`→`%s` (`_translate_qmarks`,
  `_PgConnAdapter`).
- Los ~32 branches `is_postgres_backend()` repartidos en 15 archivos.

## Consecuencias

**Positivas:**
- Un solo backend cloud (Postgres/Supabase) en vez de dos, con una superficie
  de configuración y de credenciales más pequeña.
- El bug de `train_from_db()` deja de leer datos vacíos silenciosamente.
- El mecanismo de skip por dialecto de la suite (`_SQLITE_ONLY_TOKENS` en
  `tests/conftest.py`) queda más simple: ya no necesita distinguir
  "SQLite-only" de "Turso-only", solo "SQLite-only".

**Negativas / pendiente:**
- Acción manual pendiente del mantenedor: revocar el token en el dashboard de
  Turso y borrar los GitHub Secrets `TURSO_DATABASE_URL`/`TURSO_AUTH_TOKEN`
  (el código y los workflows ya no los leen, pero el secreto en sí sigue
  vivo en la plataforma hasta que se revoque a mano).
- El shim de paramstyle y `db/migrations.py` siguen siendo dos piezas de
  complejidad activa, documentadas ahora como deliberadamente conservadas en
  vez de accidentalmente no retiradas. Su eliminación queda en el backlog,
  bloqueada por una decisión de producto (retirar SQLite) que este ADR no
  toma.
- Hallazgo aparte detectado durante el barrido (no corregido en este cambio,
  por no ser de Turso): `db/analytics.py::get_connection()` asume
  incondicionalmente que la BD operacional es un fichero SQLite para el
  `ATTACH` de DuckDB, sin comprobar `is_postgres_backend()`. Documentado como
  ítem de backlog P2 separado.
