# Runbook: Tripwires de persistencia ([[ADR-004-sqlite-turso-vs-postgres|ADR-004]])

**Propósito**: Qué hacer cuando dispara una alerta de los tripwires de
persistencia SQLite/Turso. Estos tripwires señalan que el supuesto
"single writer" de [[ADR-004-sqlite-turso-vs-postgres|ADR-004]] ya no
se sostiene y hay que decidir si migrar a PostgreSQL.

**Responsable**: Equipo de Operaciones
**Origen de las alertas**: `observability/alert_rules.yml` (grupo
`persistence_tripwires`).

---

## Alertas y umbrales

| Alerta | Métrica | Umbral | Significado |
|---|---|---|---|
| `SQLiteBusyErrorsHigh` | `sqlite_busy_errors_total` | >10/h (15m) | Contención de escritura: un writer espera el lock de otro |
| `DBWriteLatencyHigh` | `db_write_duration_seconds` p99 | >500ms (15m) | Escrituras lentas; posible lock contention o I/O |
| `DBConcurrentWritersHigh` | `db_concurrent_writers` | >3 (15m) | Más escritores simultáneos de lo que SQLite tolera bien |

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
   de la ventana de scraping/ingesta para que no compitan por el lock. Es la
   primera palanca: a escala personal suele bastar.
2. **Reducir transacciones largas (barato)**: revisar que las escrituras usen
   batch (`executemany`, `replace_adjudicaciones_batch`) y no N+1 — ya es el
   patrón, verificar que un cambio nuevo no lo rompió.
3. **Confirmar WAL + busy_timeout (barato)**: `PRAGMA journal_mode=WAL` y un
   `busy_timeout` razonable absorben contención breve sin error.
4. **Evaluar migración a PostgreSQL (caro)**: solo si lo anterior no baja el
   tripwire de forma sostenida. [[ADR-004-sqlite-turso-vs-postgres|ADR-004]] documenta el camino: el SQL es
   estándar; FTS5 → `pg_trgm` o motor de búsqueda dedicado. **Abrir un ADR de
   superación de [[ADR-004-sqlite-turso-vs-postgres|ADR-004]] antes de migrar** — no es una decisión de incidente.

## Criterio de decisión (cuándo migrar)

Migrar a Postgres **solo** si, tras aplicar las mitigaciones baratas (1–3), el
tripwire `SQLiteBusyErrorsHigh` o `DBConcurrentWritersHigh` sigue disparando de
forma sostenida durante **≥2 semanas**. A escala de pocos usuarios esto es
improbable; el tripwire existe para que la decisión sea proactiva y con datos,
no reactiva ante un incidente.
