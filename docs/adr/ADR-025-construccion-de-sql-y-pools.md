---
id: ADR-025
title: "Cómo se construye el SQL y cómo se abren las conexiones"
status: accepted
date: 2026-08-10
deciders: "Daniel Kalitovics"
related:
  - "[[ADR-016-postgres-supabase]]"
  - "[[ADR-021-retirada-sqlite]]"
  - "[[ADR-022-frontera-de-persistencia]]"
tags: [adr, architecture, persistence, performance]
---

# ADR-025 — Cómo se construye el SQL y cómo se abren las conexiones

## Contexto

ADR-022 fijó **dónde** vive el SQL (`db/`) y ADR-024 **quién** puede llamar a
`db/`. Quedaban sin decidir dos cosas que la revisión de arquitectura del
2026-08-10 encontró resueltas de dos formas distintas a la vez:

1. **Cómo se construye una query.** `db/repositories/licitaciones.py` usa
   SQLAlchemy Core (`select()`, `func.count()`, compilado con
   `db/models.py::compile_query`), mientras `db/repositories/aggregates.py` y el
   resto construyen SQL concatenando strings (`_build_where`). Solo 3 ficheros
   importan sqlalchemy. Son dos idiomas con garantías distintas frente a
   inyección y a la composición de filtros dinámicos.

2. **Cómo se abre una conexión de lectura.** Había un único pool y cada bloque
   `connect_read()` emitía `SET TRANSACTION READ ONLY` + `ROLLBACK` alrededor de
   la query: tres round-trips por lectura, sobre 209 bloques, contra una base de
   datos a ~80 ms de RTT.

## Decisión

**SQL dinámico → SQLAlchemy Core. SQL fijo → string literal parametrizado.**

- Si la query tiene **filtros, columnas o ordenaciones variables**, se construye
  con SQLAlchemy Core. La composición condicional de strings es donde aparecen
  los `S608` y donde un `noqa` acaba tapando una interpolación real.
- Si la query es **fija** (un INSERT conocido, un SELECT por id), se escribe como
  string con placeholders `%s`. Envolverla en Core no aporta seguridad y sí
  indirección.
- La migración es **oportunista**: un módulo pasa a Core cuando se toca por otro
  motivo, no en una pasada dedicada. `aggregates.py` (1.327 líneas) es el
  candidato principal, y se hace por dominio.

**Dos pools: uno de escritura y otro de lectura.**

- El de lectura abre sus conexiones con `default_transaction_read_only=on` a
  nivel de **sesión** y en autocommit. La garantía es la misma que daba el `SET`
  por bloque —una escritura por esa vía lanza `ReadOnlySqlTransaction`— pero sin
  gastar viajes: en autocommit un SELECT no abre transacción, así que tampoco
  hay ROLLBACK que emitir al devolver la conexión al pool.
- Son pools separados porque el modo solo-lectura es propiedad de la sesión:
  mezclarlos haría que un writer heredase el modo de la conexión que le tocara.
- Ambos declaran `timeout`, `max_idle` y `max_lifetime`. Sin `timeout`, el
  agotamiento del pool se manifiesta como cuelgue en vez de como error medible;
  sin reciclado, una conexión que el pooler de Supabase cortó por inactividad se
  entrega rota al siguiente que la pida.

## Consecuencias

- El suelo de latencia de una lectura pasa de ~3 RTT a ~1.
- `db_read_duration_seconds` y las métricas de pool (`db_pool_size`,
  `db_pool_connections`, `db_pool_requests_waiting`,
  `db_pool_acquire_timeout_total`) pasan a tener valores reales; antes estaban
  declaradas y valían siempre 0.
- El número de conexiones abiertas contra Supabase puede duplicarse en el peor
  caso. `DB_READ_POOL_SIZE` permite dimensionar el pool de lectura por separado;
  si el plan de la base de datos queda corto, se reparte `DB_POOL_SIZE` entre los
  dos en vez de subir el total.
- Los tests siguen viendo un solo `close_pool()`, que cierra ambos.

## Alternativas descartadas

- **Un solo pool con `SET TRANSACTION READ ONLY`.** Es lo que había: correcto y
  caro. La sesión no puede marcarse read-only sin contaminar a los escritores.
- **Un solo pool en autocommit sin marca de solo-lectura.** Ahorraría los mismos
  viajes perdiendo el guard, que es el que convirtió en error visible las
  escrituras mal dirigidas por la vía de lectura.
- **Migrar todo el SQL a Core de una vez.** Un cambio masivo sobre caminos de
  datos sin tests de caracterización suficientes, a cambio de consistencia
  estética. La regla oportunista converge sin ese riesgo.
