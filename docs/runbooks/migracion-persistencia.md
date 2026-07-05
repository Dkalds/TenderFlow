# Runbook: Migración de Persistencia SQLite/Turso → Postgres/Supabase

**ADR:** ADR-016 | **Fase:** F3c | **Fecha estimada:** Semana 3-4 del plan

## Pre-requisitos

- F3b completado: `scripts/migrate_sqlite_to_pg.py` ejecutado y `verify_pg_parity.py` verde.
- Supabase Pro configurado: región EU, Data API/PostgREST desactivado, `pg_trgm` habilitado.
- `DATABASE_URL` (Supavisor session pooler, puerto 5432) disponible como secret de GH.
- Alembic `v50_pg_search_infra` aplicado en Supabase (`alembic upgrade head`).
- `scripts/verify_pg_parity.py` ejecutado contra la BD de Supabase con datos reales → OK.

## Ventana de mantenimiento

Duración estimada: **15-30 minutos** (sin dual-write).  
Periodo de rollback garantizado: **≥14 días** (Turso intacto hasta limpieza F3d).

Racional de no usar dual-write: un solo mantenedor + escrituras dominadas por batch
idempotente re-derivable = la complejidad del dual-write no tiene retorno.

---

## Paso 0 — Comunicación

- Avisar usuarios si hay SLA comprometida (slack/email).
- Documentar en el canal de incidencias: `iniciando cutover persistencia YYYY-MM-DD HH:MM UTC`.

## Paso 1 — Congelar workers (GATE: workflows)

Detener los jobs que escriben en la BD:

```bash
# En GH Actions: deshabilitar temporalmente los workflows de escritura
gh workflow disable scrape.yml
gh workflow disable scrape-daily.yml
gh workflow disable ml-scoring.yml
gh workflow disable backup.yml
```

Detener el scheduler Docker si está corriendo:
```bash
docker compose stop scheduler
```

Verificar que no hay conexiones activas escribiendo:
```bash
# En Supabase Dashboard → Database → Connections
# O via psql:
psql "$DATABASE_URL" -c "SELECT count(*), state FROM pg_stat_activity GROUP BY state"
```

## Paso 2 — Backup final Turso

```bash
python scripts/backup_db.py --output backups/pre_cutover_$(date +%Y%m%d_%H%M%S).db
```

Verificar que el backup es legible:
```bash
sqlite3 backups/pre_cutover_*.db "SELECT COUNT(*) FROM licitaciones"
```

## Paso 3 — ETL incremental final

Solo nuevas filas desde el último ensayo de F3b:

```bash
python scripts/migrate_sqlite_to_pg.py
```

Debe completarse rápido (solo delta desde el ensayo).

## Paso 4 — Verificación de paridad (GATE BINARIO)

```bash
python scripts/verify_pg_parity.py --json-out parity_final.json
echo "Exit code: $?"
```

**Si el exit code es 0 → continuar.**  
**Si el exit code es 1 → ABORTAR. Revisar `parity_final.json`. El cutover no ha ocurrido.**

## Paso 5 — Flip DATABASE_URL

En `.env` local (si aplica):
```bash
# Comentar las líneas Turso:
# TURSO_DATABASE_URL=...
# TURSO_AUTH_TOKEN=...
# Añadir:
DATABASE_URL=postgresql://[user]:[pass]@[host]:5432/[db]?sslmode=require
```

En GH Secrets (repositorio):
1. Ir a Settings → Secrets and variables → Actions.
2. Añadir `DATABASE_URL` con la URL de Supavisor session pooler (puerto 5432).
3. Los secretos Turso se pueden dejar (no se usan si DATABASE_URL está definida).

Levantar la API con la nueva configuración:
```bash
docker compose up -d api
```

## Paso 6 — Smoke tests (GATE: todos deben pasar)

```bash
# 1. Health check
curl -s http://localhost:8080/api/v1/health/ready | python -m json.tool
# Esperado: {"status":"ok","db":"ok",...}

# 2. Búsqueda
curl -s -H "X-API-Key: $API_KEY" \
  "http://localhost:8080/api/v1/search?q=SAP&limit=5" | python -m json.tool
# Esperado: lista de licitaciones

# 3. Endpoint ask (si LLM configurado)
curl -s -H "X-API-Key: $API_KEY" \
  "http://localhost:8080/api/v1/ask?q=contratos+tecnologia" | head -c 200

# 4. Login y export
# Verificar en UI que /dashboard carga y /export funciona

# 5. Run diario manual (idempotencia sobre PG)
python -m scheduler.run_update --daily
# Esperado: status ok, nuevas=0 o pocas (ya migradas)
```

## Paso 7 — Re-habilitar workers

```bash
gh workflow enable scrape.yml
gh workflow enable scrape-daily.yml
gh workflow enable ml-scoring.yml
gh workflow enable backup.yml
docker compose start scheduler
```

## Paso 8 — Monitorización post-cutover

Durante las primeras 2 horas:
- `make doctor` — verificar DATABASE_URL alcanzable, alembic head, predicciones_baja.
- Prometheus: `db_write_duration_seconds` (latencias), `db_concurrent_writers`.
- Supabase Dashboard: Connection graph, Query performance.

## Rollback

Si algo falla en el Paso 5 o posterior:

```bash
# 1. Revertir DATABASE_URL en .env y GH Secrets a los valores Turso
# 2. Reiniciar API
docker compose restart api
# 3. Re-deshabilitar workflows si ya habían sido re-habilitados
gh workflow disable scrape.yml  # etc.
# 4. Re-scrape del gap (bulk de los últimos días)
python -m scheduler.run_update --months 1
```

Turso permanece intacto ≥14 días desde el cutover (ver F3d para limpieza).

---

## Decisiones de diseño

| Alternativa | Motivo de rechazo |
|---|---|
| Dual-write | Complejidad sin retorno (single mantenedor, batch idempotente) |
| Ventana más larga con réplica | No hay réplica Turso→PG nativa; overhead > beneficio |
| Migración en caliente | Riesgo de inconsistencia durante el flip |

El enfoque elegido (ventana read-only corta) es posible porque los writes
son dominados por el batch del scraper, que es idempotente y re-ejecutable
en < 30 minutos para los meses recientes.
