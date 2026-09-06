# Runbook: persistencia — mínimo privilegio y tripwires

**Propósito**: dos cosas que comparten la misma base de datos. (1) El cutover a
mínimo privilegio: separar la credencial que usa la app de la que puede tocar el
schema, con sus controles de aceptación. (2) Qué hacer cuando dispara un
tripwire de persistencia.

**Responsable**: el mantenedor. (Este runbook decía «Equipo de Operaciones»; no
existe tal equipo.)

**Fecha de esta revisión**: 2026-09-06 (O0.4 del plan de arquitectura v2).

---

# Parte 1 — Cutover a mínimo privilegio

## Qué separa y por qué

Hoy **una sola** `DATABASE_URL` con el rol dueño del schema la comparten la API,
el scheduler, el scraper, `alembic` y el backup. Ese rol puede hacer DDL y, por
ser el dueño de las tablas, **bypassa la RLS** de `v52_rls_lockdown` — que es
justo por lo que aquella migración no rompió nada al aplicarse, y también por lo
que la RLS es hoy inerte para el runtime.

El cutover parte esa credencial en dos:

| Variable | Rol | Quién la lleva | Puede |
|---|---|---|---|
| `DATABASE_URL` | `tenderflow_app` | API (Render), scheduler, scraper, jobs de Actions | `SELECT/INSERT/UPDATE/DELETE` y secuencias. **Nada de DDL** |
| `DATABASE_ADMIN_URL` | dueño del schema | **solo** `.github/workflows/migrate.yml` | todo, incluido `alembic upgrade` |

Si la credencial de runtime se filtra, el daño se limita a los datos, no al
schema.

## Estado a 2026-09-06

**No ejecutado.** El SQL está escrito (`scripts/setup_pg_roles.sql`) y el repo
ya tiene puestas las barreras que el cutover necesita, pero el rol no se ha
creado ni se ha rotado ninguna credencial. Desde el repositorio esto no se puede
verificar; se comprueba así:

```bash
# ¿Con qué rol conecta la app hoy?
psql "$DATABASE_URL" -c "SELECT current_user"
# tenderflow_app  → cutover hecho
# postgres (u otro dueño) → cutover pendiente
```

y, en GitHub Actions, por el banner que `migrate.yml` deja en el resumen del run
(«Fallback de credencial») cuando `DATABASE_ADMIN_URL` no existe como secret.

### Barreras que ya están en el repositorio

Son las que hacen que el cutover no se pueda deshacer por descuido:

- `config/settings.py::database_admin_url()` — única vía de acceso a la
  credencial de administración. **No es campo de `Settings`** a propósito: con
  `extra="ignore"`, pydantic descarta la variable al construir el objeto, así
  que la API ni siquiera tiene un atributo que leer. Y la función solo la sirve
  con `APP_PROFILE=scraper`, el perfil con el que corre `migrate.yml`:
  **allowlist, no lista de prohibidos**, para que un perfil futuro (el `worker`
  de S5) o un valor mal escrito fallen cerrados en vez de heredar el DSN con
  DDL por omisión.
- `tests/test_settings_admin_url.py` — fija esas tres propiedades como test.
- `scripts/check_env_parity.py` — prohíbe `DATABASE_ADMIN_URL` en `render.yaml`.
  Declararla en un servicio web volvería a ponerla en el entorno de un proceso
  que atiende internet.
- `.github/workflows/migrate.yml` — usa `DATABASE_ADMIN_URL` y avisa a gritos
  cuando cae al fallback de `DATABASE_URL`.

## Procedimiento (acción humana, en ventana)

Requiere el rol dueño de la base y acceso a Supabase, Render y GitHub Secrets.
Gate `secrets+ops` de AGENTS.md §6: lo ejecuta el mantenedor, no un agente.

```
[ ] 1. Ventana. Elegir un hueco fuera de la ventana de ingesta (scrape-daily) y
       con `migrate.yml` sin runs en curso.

[ ] 2. Password del rol nuevo:
           openssl rand -base64 32
       Sustituir <GENERAR_PASSWORD_FUERTE> en scripts/setup_pg_roles.sql (no
       commitear el fichero con la password dentro).

[ ] 3. Crear el rol y sus políticas, conectado como el rol DUEÑO:
           psql "$DATABASE_ADMIN_URL" -f scripts/setup_pg_roles.sql
       El script es idempotente. Conectar con el rol dueño no es opcional: el
       ALTER DEFAULT PRIVILEGES solo alcanza a los objetos que cree el rol que
       lo ejecuta.

[ ] 4. Construir la URL del rol de runtime (Supavisor session pooler, 5432):
           postgresql://tenderflow_app:<password>@<host>:5432/postgres?sslmode=verify-full

[ ] 5. Correr los DOS controles de aceptación de la Parte 2 contra esa URL,
       ANTES de rotar nada. Si el control 1 no falla como debe, parar aquí.

[ ] 6. Comprobar que la app funciona con el rol nuevo antes de hacerlo
       permanente: con esa URL en el `.env` local,
           ENV=dev python scripts/doctor.py
       y una lectura y una escritura reales (p. ej. `python -m scheduler.run_update`
       contra una base de pruebas, o el smoke local).

[ ] 7. Rotar los secretos, en este orden:
       [ ] a. GitHub → Settings → Secrets → Actions → **crear**
              `DATABASE_ADMIN_URL` con la URL del rol dueño (la de hoy).
       [ ] b. GitHub → `DATABASE_URL` ← la URL de tenderflow_app.
       [ ] c. Render → tenderflow-api → Environment → `DATABASE_URL` ← la URL de
              tenderflow_app. **NUNCA** añadir `DATABASE_ADMIN_URL` a un
              servicio de Render: `scripts/check_env_parity.py` falla si aparece
              en `render.yaml`, pero el dashboard no lo comprueba.
       [ ] d. `.env` local de cada mantenedor.

[ ] 8. Redesplegar la API y comprobar:
           curl -s "$SMOKE_BASE_URL/api/v1/health/ready" | python -m json.tool
       `schema` en `ok`, y la superficie pública sirviendo datos.

[ ] 9. Lanzar `migrate.yml` con `mode=plan`: el resumen del run ya NO debe
       mostrar el banner «Fallback de credencial».

[ ] 10. Cerrar la puerta del fallback: en el paso «Credencial de migración» de
        .github/workflows/migrate.yml, cambiar el `exit 0` final por `exit 1`.
        Mientras siga en `exit 0`, un `DATABASE_ADMIN_URL` borrado por error
        hace que la migración vuelva a correr con la credencial de la app y solo
        deje un warning.

[ ] 11. Anotar aquí la fecha del cutover y actualizar el párrafo «Cutover
        pendiente» de docs/SECURITY.md.

[ ] 12. Rotación posterior: `DATABASE_URL` cada 90 días (docs/SECURITY.md).
```

**Rollback.** Volver a poner en `DATABASE_URL` (Render + Actions) la URL del rol
dueño. El rol `tenderflow_app` puede quedarse creado sin efecto; el script es
idempotente y no hay que deshacer nada más.

---

# Parte 2 — Los dos controles de aceptación

Son los criterios de O0.4. Se ejecutan **con la credencial del rol de la app**,
en el paso 5 del procedimiento, y se repiten después del cutover.

Convención de las órdenes de abajo: `$DATABASE_URL_APP` es la URL de
`tenderflow_app` y `$DATABASE_ADMIN_URL` la del rol dueño.

## Control 1 — con el rol de la API, el schema es intocable

Se espera que **las tres órdenes fallen**.

```bash
# 1a. Confirmar con qué rol se está conectando.
psql "$DATABASE_URL_APP" -c "SELECT current_user, session_user"
#     esperado: tenderflow_app | tenderflow_app

# 1b. CREATE TABLE → permission denied for schema public
psql "$DATABASE_URL_APP" -c "CREATE TABLE tripwire_ddl (x int)"

# 1c. ALTER de una tabla que no es suya → must be owner of table licitaciones
psql "$DATABASE_URL_APP" -c "ALTER TABLE licitaciones ADD COLUMN tripwire_x int"
```

```bash
# 1d. alembic upgrade head con la credencial de la app → falla.
ENV=prod APP_PROFILE=scraper DATABASE_URL="$DATABASE_URL_APP" alembic upgrade head
```

> **Cuidado con el falso verde de 1d.** Si el schema ya está en `head`, alembic
> no ejecuta DDL y sale con 0 sin demostrar nada. Este control solo vale
> lanzado cuando hay **al menos una revisión pendiente** (justo después de
> mergear una, o comprobando antes con `alembic current` y `alembic heads` que
> no coinciden). Si están al día, el control que sí es determinista es 1b/1c.

```bash
# 1e. La API no puede ni leer la credencial: RuntimeError, no None.
#     Con `worker` o sin perfil declarado pasa lo mismo: solo `scraper` la recibe.
APP_PROFILE=api python -c "
from config.settings import database_admin_url
try:
    database_admin_url()
except RuntimeError as exc:
    print('OK, se negó:', exc)
else:
    raise SystemExit('FALLO: la API obtuvo la credencial de administración')
"
```

Esto último está fijado por `tests/test_settings_admin_url.py`, que corre en la
suite unitaria y no necesita base de datos.

## Control 2 — RLS: qué cierra de verdad y qué no

El criterio del plan dice: «con el rol de la API y sin fijar tenant, una
consulta sobre una tabla con RLS devuelve cero filas de otra organización».
Ejecutarlo es esto:

```bash
# 2a. El rol de la app NO puede saltarse la RLS.
psql "$DATABASE_URL_APP" -c \
  "SELECT rolname, rolbypassrls, rolsuper FROM pg_roles WHERE rolname = current_user"
#     esperado: tenderflow_app | f | f

# 2b. No queda ninguna tabla de public sin RLS habilitada.
psql "$DATABASE_URL_APP" -c "
SELECT count(*) AS tablas_sin_rls
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r'
  AND c.relname <> 'alembic_version' AND NOT c.relrowsecurity"
#     esperado: 0

# 2c. Lectura de una tabla multi-tenant sin fijar ningún tenant.
psql "$DATABASE_URL_APP" -c "SELECT organization_id, count(*) FROM pursuits GROUP BY 1"
```

**Lo que 2c devuelve hoy, y por qué.** Devuelve filas de **todas** las
organizaciones. No es un fallo del cutover: `scripts/setup_pg_roles.sql` crea
para `tenderflow_app` una política `tenderflow_app_full_access ... USING (true)`
en cada tabla, y `v62` hace lo mismo para las tablas que añade. Es deliberado —
`tenderflow_app` es la aplicación entera, no un rol por usuario, y el
aislamiento por organización vive en la capa de aplicación (los repositorios
filtran por `organization_id`, y los tests de aislamiento de `#271` lo
verifican). Lo que la RLS de `v52` cierra es **la Data API de Supabase**, o sea
los roles `anon`/`authenticated`:

```bash
# 2d. El control que sí demuestra el aislamiento que la RLS aporta hoy.
psql "$DATABASE_ADMIN_URL" -c "SET ROLE anon; SELECT count(*) FROM pursuits;"
#     esperado: ERROR: permission denied for table pursuits
#     (el REVOKE de v52; y aunque se re-concediera el GRANT, sin políticas para
#     anon la RLS deja la tabla en deny-all)
```

**Consecuencia, escrita para que no se pierda.** El criterio de O0.4 tal como
está redactado —cero filas de otra organización *para el rol de la app*— **no lo
cumple el diseño actual y no basta con ejecutar el cutover**: exigiría políticas
RLS por tenant sobre una variable de sesión (`current_setting('app.current_organization')`
o equivalente) fijada por el pool en cada conexión, y una migración que las
cree. Eso es un cambio de arquitectura de acceso a datos, no un paso de este
runbook: se decide en un ADR, se implementa en `scripts/setup_pg_roles.sql` más
una revisión de alembic, y se paga en cada `SET` del pool. Hasta entonces, lo
honesto es decir que el cutover cierra el DDL (control 1) y la Data API (2d), y
que el aislamiento entre organizaciones sigue siendo responsabilidad de la capa
de aplicación.

---

# Parte 3 — Tripwires de persistencia ([[ADR-004-sqlite-turso-vs-postgres|ADR-004]])

Estos tripwires nacieron señalando que el supuesto "single writer" de
[[ADR-004-sqlite-turso-vs-postgres|ADR-004]] ya no se sostenía y había que
decidir si migrar a PostgreSQL — esa migración **ya ocurrió** ([[ADR-016|ADR-016]],
cutover 2026-07-11, ver `docs/runbooks/migracion-persistencia.md`). El mismo
invariante (¿cuántos escritores concurrentes tolera la arquitectura antes de
necesitar revisión?) se sigue vigilando, ahora sobre el pool `psycopg_pool` de
Postgres en vez de sobre el lock de fichero de SQLite.

**Origen de las alertas**: `observability/alert_rules.yml` (grupo
`postgres_pool_alerts`). Por dónde salen y cómo se comprueba que llegan:
`docs/runbooks/observability-alerts.md`.

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
   El techo de conexiones de la API y su relación con el `Pool Size` del pooler
   de Supabase están calculados en los comentarios de `render.yaml`.
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
