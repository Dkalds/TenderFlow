---
rfc: 2026-06-30
title: Plan de migración de persistencia pre-cocido con disparador binario (SQLite/Turso → Postgres)
issue: pendiente — generado en sesión de arquitectura (revisión integral 2026-06-30); sin issue asociado aún
author: agent:architect
date: 2026-06-30
status: draft
---

## Contexto

[[ADR-004-sqlite-turso-vs-postgres|ADR-004]] eligió SQLite/Turso sobre Postgres bajo una premisa explícita: **un solo
writer** (el pipeline del scraper, un run a la vez). Esa premisa **ya no se
cumple**, y el propio ADR lo reconoce en el bloque "Migration Tripwires (added
2026-06-10)":

> *"The original 'single writer' assumption from [[ADR-004-sqlite-turso-vs-postgres|ADR-004]] no longer holds; these
> tripwires provide a proactive migration signal instead of reacting to incidents."*

Writers concurrentes hoy: scraper pipeline, scheduler (KPI/aggregates/drift),
API (webhooks, exports, API keys, watchlist, auth) y dashboard (sessions/auth).
La respuesta fue **instrumentar** el riesgo —tres tripwires Prometheus en
`observability/runtime_metrics.py`, reglas en `observability/alert_rules.yml`
(grupo `persistence_tripwires`), runbook en
`docs/runbooks/persistence-tripwires.md`:

| Métrica | Umbral | Acción declarada |
|--------|--------|------------------|
| `sqlite_busy_errors_total` | >10/h sostenido | Evaluar migración a Postgres |
| `db_write_duration_seconds` p99 | >500ms | Investigar contención |
| `db_concurrent_writers` | >3 sostenido | Architecture review |

El problema: **la detección está, pero la decisión sigue diferida**. Cuando salte
el tripwire, alguien (el mantenedor, solo) tendrá que *diseñar* la migración bajo
presión de incidente — porting de FTS5→`pg_trgm`, recableado del pool, estrategia
de doble escritura/corte, validación de paridad — que es precisamente cuando peor
se diseña. Y el vector de presión va a crecer: [[ADR-009-framework-conectores-multifuente|ADR-009]] ya metió 3 conectores
nuevos (`ted`, `pscp`, `tacrc`) que escriben vía `run_connector`, y las fases
autonómicas siguientes suman más writers concurrentes.

Este RFC **no propone migrar**. Propone **tener el plan de migración listo en frío**
para que el tripwire dispare una ejecución pre-diseñada, no un proyecto de diseño.

## Decisión

Producir, **ahora y sin migrar nada en producción**, un plan de migración
ejecutable y validado en un spike, materializado en tres entregables:

1. **ADR de destino de persistencia** (`docs/adr/ADR-015-destino-migracion-persistencia.md`):
   decide *de antemano* el destino y lo justifica, para que no se decida bajo
   incidente. Opciones a evaluar y cerrar en el ADR:
   - **(a) Postgres managed** (Supabase/Neon) como OLTP único.
   - **(b) Separación de planos**: mantener SQLite/Turso como caché OLTP de lectura
     y mover *solo el plano de escritura analítico/concurrente* a Postgres, o
     descargar lo analítico a Parquet/DuckDB read-only (coherente con [[ADR-013-jerarquia-materializaciones-analiticas|ADR-013]], que
     ya define SQLite=caché OLTP / Parquet=snapshot / DuckDB=motor opcional).
   - El ADR fija **un** destino con su rationale, no deja la disyuntiva abierta.

2. **Spike validado en branch** (no merge a producción): levantar el destino
   elegido, portar el schema vía Alembic (el `target_metadata` ya está conectado,
   backlog 2026-05-23 "DevOps"), y **medir el porting de FTS5**: reemplazo por
   `pg_trgm` o motor de búsqueda dedicado, con un test de paridad de resultados de
   búsqueda sobre un dataset fijo. Es el ítem de mayor incertidumbre técnica y el
   que hay que despejar en frío.

3. **Runbook de ejecución** (`docs/runbooks/migracion-persistencia.md`): pasos
   reproducibles de corte —backup, doble escritura o ventana de read-only,
   validación de paridad de filas/agregados, rollback— de modo que el disparo del
   tripwire sea *"ejecutar el runbook"*, no *"diseñar la migración"*.

**Disparador binario**: el RFC formaliza que cuando `sqlite_busy_errors_total`
supere >10/h sostenido (o `db_concurrent_writers` >3 sostenido), la **ejecución**
del runbook pasa a **P0**. Hasta entonces, este trabajo de *preparación* es P1.
La detección ya existe; lo que falta es que el disparo encuentre el plan hecho.

**Qué NO se hace:**

- **No** se migra producción. Ningún cambio en el camino de datos vivo.
- **No** se toca `db/alembic/**` con migraciones nuevas de producción (el spike
  vive en branch; requiere OK humano de todas formas, AGENTS.md §6).
- **No** se retiran los tripwires ni se relajan umbrales — siguen siendo el gatillo.
- **No** se cambia [[ADR-004-sqlite-turso-vs-postgres|ADR-004]] (sigue Accepted); ADR-015 lo *extiende* con el plan de
  salida, no lo revierte.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo (solo tripwires) | Cero trabajo ahora | El diseño de la migración ocurre bajo incidente, que es cuando peor sale | Es la situación actual; el RFC existe para superarla |
| Migrar a Postgres ya, preventivo | Elimina el riesgo de raíz | Coste/ops innecesario hoy; los tripwires no han disparado; contradice "medir antes de actuar" | Sobredimensionado sin señal real |
| Solo el ADR de destino, sin spike | Barato | El porting de FTS5 es la incógnita real; un ADR sin validarlo es papel | Deja el riesgo técnico sin despejar |
| Separar writers para forzar single-writer otra vez | Salva [[ADR-004-sqlite-turso-vs-postgres|ADR-004]] sin cambiar motor | Reintroduce acoplamiento; serializa la API tras el scraper; frágil | Trata el síntoma, no escala con multi-fuente |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Ninguno en este RFC (docs + spike en branch) | El eventual código de migración mantiene strict |
| §3.2 Upsert idempotente | Ninguno ahora; **crítico** en la ejecución | El runbook valida idempotencia post-corte como gate |
| §3.3 Migraciones append-only | El spike usa Alembic en branch, no toca historial | OK humano antes de cualquier migración real (§6) |
| §3.4 Auto-marking tests | Ninguno | Tests de paridad siguen naming convention |
| §3.5 Pydantic v2 DTOs | Ninguno — el contrato API no cambia con el motor | Objetivo explícito: migración transparente a `web/` |
| §3.6 HMAC/argon2 auth | Ninguno | — |
| §3.9 Plano único orquestación | Relevante: writers concurrentes son el detonante | El ADR-015 considera la interacción con SCHEDULER_PLANE |

## Plan de implementación

1. `docs/adr/ADR-015-destino-migracion-persistencia.md` — decidir y justificar
   destino (a/b). Referencia cruzada a [[ADR-004-sqlite-turso-vs-postgres|ADR-004]] y [[ADR-013-jerarquia-materializaciones-analiticas|ADR-013]].
2. Branch `spike/persistence-postgres` — levantar destino, `alembic upgrade head`
   contra Postgres, port FTS5→`pg_trgm`, test de paridad de búsqueda sobre dataset
   fijo. **Sin merge.**
3. `docs/runbooks/migracion-persistencia.md` — runbook de corte + rollback +
   gates de paridad (conteos, agregados clave, idempotencia de upsert).
4. `docs/adr/[[ADR-004-sqlite-turso-vs-postgres|ADR-004]]-sqlite-turso-vs-postgres.md` — añadir nota "Plan de salida:
   ver ADR-015 + runbook" (sin cambiar el status Accepted).
5. `observability/alert_rules.yml` — al disparar el tripwire, la alerta enlaza
   directamente al runbook (annotation `runbook_url`).

**Archivos de partida**: `docs/adr/[[ADR-004-sqlite-turso-vs-postgres|ADR-004]]-sqlite-turso-vs-postgres.md`,
`docs/adr/[[ADR-013-jerarquia-materializaciones-analiticas|ADR-013]]-jerarquia-materializaciones-analiticas.md`,
`docs/runbooks/persistence-tripwires.md`, `observability/runtime_metrics.py`,
`observability/alert_rules.yml`, `db/connection.py`, `db/database.py`.
**Riesgo estimado**: bajo en preparación (docs + spike aislado); el riesgo real
es de la *ejecución* futura, que este RFC busca de-riesgar.
**Tiempo estimado**: 2–3 días (mayoría en el spike de FTS5→pg_trgm).

## Acceptance criteria

- [ ] Existe ADR-015 con **un** destino decidido y justificado (no una disyuntiva abierta).
- [ ] El spike en branch levanta el destino, corre `alembic upgrade head` y pasa un
      test de paridad de búsqueda FTS5↔reemplazo sobre un dataset fijo.
- [ ] Existe `docs/runbooks/migracion-persistencia.md` con pasos de corte, gates de
      paridad y rollback.
- [ ] La alerta del tripwire enlaza al runbook (`runbook_url`).
- [ ] El RFC declara explícitamente el umbral que escala la *ejecución* a P0.
- [ ] `make lint && make typecheck && make test-unit` pasan en verde (el spike no
      regresiona la suite de master).

## Notas de review

<Comentarios del reviewer y security_triage durante la etapa agent:rfc-review.
Formato: `YYYY-MM-DDTHH:MMZ agent:reviewer — <comentario>`>
