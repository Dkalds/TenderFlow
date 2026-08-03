# Runbook: Tripwires de persistencia ([[ADR-004-sqlite-turso-vs-postgres|ADR-004]])

**Propósito**: Qué hacer cuando dispara una alerta de los tripwires de
persistencia. Estos tripwires nacieron señalando que el supuesto
"single writer" de [[ADR-004-sqlite-turso-vs-postgres|ADR-004]] ya no se
sostenía y había que decidir si migrar a PostgreSQL — esa migración **ya
ocurrió** ([[ADR-016|ADR-016]], cutover 2026-07-11, ver
`docs/runbooks/migracion-persistencia.md`). El mismo invariante (¿cuántos
escritores concurrentes tolera la arquitectura antes de necesitar revisión?)
se sigue vigilando, ahora sobre el pool `psycopg_pool` de Postgres en vez de
sobre el lock de fichero de SQLite.

**Responsable**: Equipo de Operaciones
**Origen de las alertas**: `observability/alert_rules.yml` (grupo
`postgres_pool_alerts`).

---

## Alertas y umbrales

| Alerta | Métrica | Umbral | Significado |
|---|---|---|---|
| `PgWriteLatencyHigh` | `db_write_duration_seconds` p99 | >1s (10m) | Escrituras lentas en Postgres; posible query lenta o contención |
| `PgConcurrentWritersHigh` | `db_concurrent_writers` | >3 (15m) | Más escritores simultáneos de lo que asumía el diseño de ADR-004 |

`SQLiteBusyErrorsHigh` (`sqlite_busy_errors_total`, >10/h) se retiró en
2026-08: ese contador ya no existe (ADR-021, Postgres-only). Su equivalente
Postgres-nativo es `PgPoolAcquireTimeoutHigh` (mismo grupo): mide timeouts al
adquirir una conexión del pool en vez de reintentos de lock de fichero.

## Diagnóstico

1. **Confirmar el alcance** en Grafana: ¿es un pico puntual (backfill, migración
   manual) o sostenido? Los tripwires usan `for: 15m` para filtrar ruido, pero
   un backfill largo puede dispararlos legítimamente.
2. **Identificar los writers activos** ([[ADR-004-sqlite-turso-vs-postgres|ADR-004]] §Tripwires): scraper pipeline,
   scheduler (KPI/aggregates/drift), API (webhooks, exports, API keys,
   watchlist, auth), dashboard (sesiones/auth).
3. **Correlacionar** con `scheduler_job_duration_seconds` y la ventana de
   scraping: si la contención coincide con jobs concurrentes del scheduler, es
   un problema de *scheduling*, no de motor.

## Mitigaciones por orden de coste

1. **Serializar writers (barato)**: mover jobs del scheduler que escriben fuera
   de la ventana de scraping/ingesta para que no compitan por conexiones del
   pool. Es la primera palanca: a escala personal suele bastar.
2. **Reducir transacciones largas (barato)**: revisar que las escrituras usen
   batch (`executemany`, `replace_adjudicaciones_batch`) y no N+1 — ya es el
   patrón, verificar que un cambio nuevo no lo rompió.
3. **Revisar el pool (barato)**: `DB_POOL_SIZE` y el timeout de adquisición
   (ver también `PgPoolAcquireTimeoutHigh`, mismo grupo de alertas); un pool
   subdimensionado para la concurrencia real produce exactamente este patrón.
4. **Escalar Postgres o el diseño de acceso a datos (caro)**: si lo anterior no
   baja el tripwire de forma sostenida, considerar más recursos en Supabase
   (plan/tamaño de instancia) o revisar si alguna ruta de escritura necesita
   rediseño (p.ej. mover una escritura síncrona a background job). Un cambio
   de infraestructura o de arquitectura de acceso a datos se documenta en un
   ADR — no es una decisión de incidente.

## Cuándo escalar

Escalar a un ADR o a una revisión de arquitectura **solo** si, tras aplicar las
mitigaciones baratas (1–3), el tripwire `PgWriteLatencyHigh` o
`PgConcurrentWritersHigh` sigue disparando de forma sostenida durante **≥2
semanas**. A escala de pocos usuarios esto es improbable; el tripwire existe
para que la decisión sea proactiva y con datos, no reactiva ante un incidente.
