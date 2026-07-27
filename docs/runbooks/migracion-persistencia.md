# Runbook: Migración de Persistencia SQLite/Turso → Postgres/Supabase

**ADR:** ADR-016 | **Fase:** F3c | **Fecha estimada:** Semana 3-4 del plan

> **ESTADO (2026-07-11): CUTOVER EJECUTADO.** Producción corre sobre Supabase
> Postgres vía `DATABASE_URL` (Supavisor session pooler). Este runbook se
> conserva como registro del procedimiento y como referencia para el
> hardening pendiente: **el Paso 9 y la sección F3d+ siguen abiertos** — ver
> el ítem P1 "Verificar checklist F3d post-cutover" en
> [docs/IMPROVEMENT_BACKLOG.md](../IMPROVEMENT_BACKLOG.md).
>
> **Inventario verificado 2026-07-12** (`gh secret list` / `gh variable list`
> — solo nombres, sin ver valores): `DATABASE_URL` y `DATABASE_SSL_ROOT_CERT`
> existen como GH Secrets (añadidos 2026-07-09, consistente con la fecha del
> cutover) → el paso "TLS verify-full" del Paso 9 tiene su credencial
> disponible, pero **no se pudo verificar desde aquí** que el `DATABASE_URL`
> vivo use efectivamente `sslmode=verify-full`. **`BACKUP_ENCRYPTION_KEY` NO
> existe** en los secrets del repo → los backups de `backup.yml` se están
> subiendo **sin cifrar** a S3 privado ahora mismo (el propio workflow emite
> `::warning::BACKUP_ENCRYPTION_KEY no definido` en cada corrida). No hay
> secret `DATABASE_ADMIN_URL` ni evidencia de un rol `tenderflow_app`
> separado → el rol de privilegios mínimos sigue sin crear. La migración
> `v52_rls_lockdown` **existe** en `db/alembic/versions/` (creada
> 2026-07-06) pero si está *aplicada* contra la Supabase viva no es
> verificable sin credenciales — requiere `alembic current` contra prod.
>
> **Actualización 2026-07-13** (plan Pliegos+RAG, fase D2): el gap
> `ENV=dev` está **cerrado en código** — `_validate_prod_database_ssl` en
> `config/settings.py` ahora exige `sslmode` seguro para cualquier
> `DATABASE_URL` con host remoto, **sea cual sea `ENV`** (antes solo
> aplicaba en prod/staging; `scrape-daily.yml` corre con `ENV=dev` contra
> Supabase real y antes se colaba). `scripts/setup_pg_roles.sql` ya existe
> (rol `tenderflow_app` + políticas RLS compatibles con v52). El Paso 9 de
> abajo es ahora un checklist ejecutable — **las acciones siguen pendientes
> de ejecución manual** (rotar password, crear `DATABASE_ADMIN_URL`, correr
> el script contra Supabase): eso requiere credenciales del usuario y queda
> fuera del alcance de lo que un agente puede hacer sin acceso al panel.

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

## Paso 9 — Hardening post-cutover (seguridad) — checklist ejecutable

Una vez estable el nuevo backend, cerrar la superficie de seguridad. Cada ítem
es una acción manual del usuario (gate secrets+ops, AGENTS.md §6) — el repo
prepara el script/validator, la ejecución contra Supabase la hace el mantenedor.

- [ ] **1. Rotar la password del rol dueño** — la credencial viajó por `.env`,
      laptops, ETL y secrets durante la migración. Supabase Dashboard → Database
      → *Reset database password*.
- [ ] **2. `DATABASE_URL` con TLS verificado** — reconstruir con
      `?sslmode=verify-full` y `DATABASE_SSL_ROOT_CERT` apuntando a la CA de
      Supabase (Dashboard → Database → SSL). Actualizar en Render + GitHub
      Secrets + `.env`. El validator en `config/settings.py`
      (`_validate_prod_database_ssl`) ya lo exige para **cualquier host
      remoto, independientemente de `ENV`** (cierra el gap donde
      `scrape-daily.yml` corría con `ENV=dev` sin TLS verificado) — si el
      secret no cumple, el proceso falla al arrancar en vez de conectar sin
      TLS.
- [ ] **3. `DATABASE_ADMIN_URL` separada** — antes de crear `tenderflow_app`
      (paso 5), guardar la `DATABASE_URL` actual (rol dueño) como
      `DATABASE_ADMIN_URL` (GitHub Secret, **solo** para `alembic upgrade
      head` — nunca en el runtime de la app/scheduler/scraper).
- [ ] **4. Desactivar la Data API/PostgREST** — Supabase Dashboard → Settings
      → API.
- [ ] **5. Verificar RLS (v52_rls_lockdown) aplicada**:
      ```bash
      psql "$DATABASE_ADMIN_URL" -c "SELECT relname FROM pg_class WHERE relrowsecurity AND relkind='r' LIMIT 5"
      psql "$DATABASE_ADMIN_URL" -c "SELECT has_table_privilege('anon','users','SELECT')"  # debe ser false
      psql "$DATABASE_ADMIN_URL" -c "SELECT alembic_version_num FROM alembic_version"  # o: alembic current
      ```
- [ ] **6. Ejecutar `scripts/setup_pg_roles.sql`** (rol `tenderflow_app` de
      solo-DML + políticas RLS compatibles — ver cabecera del script para el
      procedimiento completo):
      ```bash
      psql "$DATABASE_ADMIN_URL" -f scripts/setup_pg_roles.sql
      ```
      Verificar que el rol puede DML pero **no** DDL:
      ```bash
      psql "$DATABASE_URL" -c "SELECT current_user"                    # tenderflow_app
      psql "$DATABASE_URL" -c "CREATE TABLE probe_ddl(x int)"           # debe FALLAR (permission denied)
      psql "$DATABASE_URL" -c "SELECT count(*) FROM licitaciones"       # debe funcionar
      ```
      Flip `DATABASE_URL` (app/scheduler/scraper) a la URL con `tenderflow_app`;
      `DATABASE_ADMIN_URL` queda solo para alembic.
- [ ] **7. Backups cifrados** — `BACKUP_ENCRYPTION_KEY` (GitHub Secret). Ver
      `docs/runbooks/backup-restore.md` § "Backups Postgres cifrados" para el
      procedimiento completo (generación, verificación, descifrado).
- [x] **8. Retirar Turso** — **completado 2026-07-26 (ADR-020)**, pasada la
      ventana de rollback (**≥14 días** desde el cutover) y confirmada la
      estabilidad en Postgres. Se retiró tanto la configuración
      (`TURSO_DATABASE_URL`/`TURSO_AUTH_TOKEN` de workflows, `render.yaml`,
      `.env.example`) como el código (`is_turso_backend()`, el pool Queue y
      la réplica de lectura Turso en `db/connection.py`). El backend SQLite
      local (fichero, vía `libsql`) se conserva como comodidad de desarrollo
      (ADR-018) — no tiene relación con Turso cloud.
      Acción manual pendiente del maintainer: revocar el token en el panel de
      Turso y borrar los secrets `TURSO_DATABASE_URL`/`TURSO_AUTH_TOKEN` de
      GitHub Secrets (el código ya no los lee, pero conviene no dejarlos
      colgando).

## Roadmap F3d+ — Rol de privilegios mínimos

Hoy la app, el scheduler, el scraper, alembic y el backup comparten una única
`DATABASE_URL` con un rol de altos privilegios (dueño del schema). El paso 6
del checklist de arriba separa responsabilidades: `tenderflow_app` (solo DML,
sin DDL/ownership) para runtime; `DATABASE_ADMIN_URL` (rol dueño) solo para
`alembic upgrade head`.

⚠️ **Dependencia con RLS (v52):** `tenderflow_app` NO es dueño de las tablas,
así que la RLS activa (sin políticas) lo dejaría **deny-all** — por eso
`scripts/setup_pg_roles.sql` añade una política permisiva explícita
(`tenderflow_app_full_access`, `FOR ALL … USING (true)`) por cada tabla. El
control de acceso real sigue viviendo en la capa de aplicación (scopes,
`auth_core`); RLS aquí solo cierra la Data API pública de Supabase para
`anon`/`authenticated`, no filtra filas para `tenderflow_app`.

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
