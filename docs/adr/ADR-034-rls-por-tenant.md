# ADR-034 — Aislamiento por organización en dos capas: filtro de aplicación + RLS por tenant

- **Estado:** aceptado
- **Fecha:** 2026-09-14
- **Relacionado:** [ADR-016](ADR-016-destino-persistencia-supabase.md),
  [ADR-022](ADR-022-frontera-de-persistencia.md),
  [ADR-025](ADR-025-construccion-de-sql-y-pools.md),
  [ADR-030](ADR-030-identidad-user-id-y-oidc.md)
- **Implementa:** «Ola 1 · RLS por tenant» de la revisión de salida al
  mercado; migración `v128_rls_tenant_policies`.

---

## Contexto

La tenencia se aplicaba en **una sola capa**: `api/tenancy.py` resuelve la
organización activa de la petición y cada repositorio de `db/` filtra por
`organization_id`. Es un control correcto y verificado
(`tests/test_organization_sql_isolation.py`, `tests/test_user_key_sql_isolation.py`),
pero es un control por omisión: un repositorio nuevo que olvide el `WHERE`
devuelve las filas de otro cliente y ningún mecanismo lo detecta hasta que
alguien lo ve en pantalla.

La base de datos no ayudaba. `v52_rls_lockdown` habilitó RLS en todas las
tablas **sin `FORCE` y sin políticas**: el rol dueño la bypassa, y el rol
runtime de producción (`tenderflow_app`, `scripts/setup_pg_roles.sql`) tiene
`tenderflow_app_full_access USING (true)` en cada tabla. Esa RLS cierra la
Data API de Supabase (`anon`/`authenticated` en deny-all); no separa
tenants. El runbook `docs/runbooks/persistence-tripwires.md` (control 2) lo
dejó escrito: el criterio «cero filas de otra organización para el rol de la
app» exigía políticas por tenant sobre una variable de sesión, y era una
decisión de arquitectura, no un paso del cutover.

Dos hechos condicionan cómo puede hacerse:

- **Postgres exime de RLS a superusuarios y roles `BYPASSRLS`** aunque la
  tabla lleve `FORCE`. El rol de la suite y el del `docker compose` local son
  superusuarios: cualquier política es invisible para ellos.
- **Las políticas permisivas se combinan con OR.** Sobre `tenderflow_app`,
  una política permisiva más sería `true OR predicado`: no acotaría nada.

## Decisión

### A. La aplicación sigue siendo el control primario

Los repositorios siguen filtrando por `organization_id` y `api/tenancy.py`
sigue siendo el único punto que resuelve la organización de una petición. La
RLS de esta decisión es un **respaldo** (defensa en profundidad): hace que un
`WHERE` olvidado devuelva cero filas ajenas en vez de todas, y que un
`INSERT`/`UPDATE` que produzca una fila de otra organización falle en la
base. No sustituye al filtro, y no autoriza a quitarlo.

### B. El ámbito viaja en un `ContextVar` y se aplica con `SET LOCAL`

`shared/tenant_context.py` guarda la organización activa en un
`contextvars.ContextVar`. Lo abren dos piezas, siempre **con final**:
`api/tenancy.py::resolve_organization_ctx` para las rutas que pasan por ahí, y
`services/organizations.py::alcance_resuelto` —un context manager que resuelve
y acota el bloque— para las verticales que resuelven desde `services/`. `anyio`
copia el contexto al hilo del pool (`api.concurrency.run_db`), y
`db/connection.py` lo lee al abrir cada transacción:

- `connect()` emite `SET LOCAL app.organization_id = '<id>'` como primera
  sentencia; psycopg ya abre la transacción implícita, y el `SET LOCAL` muere
  con su `COMMIT`/`ROLLBACK`.
- `connect_read()` está en autocommit (ADR-025), donde `SET LOCAL` es un
  no-op. Con ámbito, abre una transacción explícita (`BEGIN; SET LOCAL …`, un
  viaje) y la cierra con `ROLLBACK` (otro). Una lectura acotada cuesta tres
  round-trips; una sin ámbito sigue costando uno.

`SET LOCAL` y no `SET` de sesión: la variable es de la transacción y Postgres
la deshace solo; nada puede quedar en una conexión del pool al devolverla.
Sin ámbito (scheduler, scripts, migraciones, tests) no se emite nada.

### C. Dos políticas por tabla, con paso franco sin ámbito

`v128` aplica a cada tabla corporativa con `organization_id`
`FORCE ROW LEVEL SECURITY` y dos políticas con el mismo predicado:

```sql
NULLIF(current_setting('app.organization_id', true), '') IS NULL
OR organization_id IS NULL
OR organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer
```

- `tenant_scope_<tabla>`, **permisiva**: concede acceso acotado al rol dueño
  (sujeto por el `FORCE`) y a cualquier rol sin otra política.
- `tenant_guard_<tabla>`, **restrictiva**: se combina con AND y es la que
  acota a `tenderflow_app` por encima de su `USING (true)`. No puede ir sola:
  una restrictiva nunca concede acceso.

El primer término del predicado es el paso franco: sin variable, o con la
variable a `''` (a lo que vuelve un GUC placeholder al cerrar la transacción
en la que se fijó), se ve todo. El `NULLIF` va dentro del cast porque el orden
de evaluación de `OR` no está garantizado y `''::integer` revienta. El segundo
término conserva visibles las filas legadas sin organización que
`db/tenancy_backfill.py` inventaría.

Quedan fuera `organizations`, `organization_memberships` y
`organization_invitations` (resolver una membresía exige verlas todas),
`domain_events` y `jobs` (outbox y cola los consume el worker sin ámbito) y
las tablas de auditoría. Una tabla nueva con `organization_id` no entra sin
decisión: `tests/test_rls_tenant_scope_integration.py` enumera
`information_schema` y falla si la tabla no está en el conjunto protegido ni
en la lista de exclusiones con motivo.

### D. Las operaciones legítimamente transversales lo declaran

Una petición acotada puede tener que escribir en **otra** organización. El
caso conocido es `services/organizations.py::claim_legacy_scope`, que
adjudica al espacio personal las filas sin organización del usuario mientras
la activa es una compartida. Se ejecuta bajo `tenant_scope(None)`, que suelta
el ámbito para ese bloque y lo restaura al salir. La regla: quien cruce
organizaciones a propósito lo declara con `tenant_scope(None)` en el servicio
y explica por qué; no se relaja la política.

### E. Las políticas se prueban con un rol que emula a producción

Como el rol de la suite es superusuario, los tests crean un rol sonda sin
`BYPASSRLS`, le dan la misma política `USING (true)` que tiene
`tenderflow_app` y hacen que el pool conecte con `SET ROLE`. Es la
configuración de producción tal cual; si la política fuera solo permisiva,
esos tests lo dirían.

## Consecuencias

- **Producción hoy.** El runtime aún conecta como dueño del schema (cutover
  pendiente, `docs/SECURITY.md`). Si ese rol tiene `BYPASSRLS` —lo habitual
  en el `postgres` de Supabase—, el respaldo está instalado pero inerte hasta
  el cutover a `tenderflow_app`, que es cuando se ejerce. El `FORCE` cubre el
  caso de un dueño sin `BYPASSRLS`.
- **Coste.** Una lectura con ámbito pasa de 1 a 3 round-trips; una escritura
  añade uno. Sin ámbito no cambia nada. Se acepta: es el precio de que el
  respaldo exista, y las lecturas calientes sin organización (públicas,
  analítica) no lo pagan.
- **Cobertura.** Toda petición que resuelva una organización queda acotada,
  venga de `api/tenancy.py` o de un servicio.

  No fue así al principio, y conviene recordar por qué: hasta 2026-09 el
  ámbito lo fijaba únicamente `api/tenancy.py`, y la vertical de pursuits
  —que resuelve desde `services/pursuits.py`— corría **sin** respaldo. Como el
  predicado de `v128` deja pasar todo cuando el GUC está vacío, aquello no
  rompía nada: apagaba la RLS en silencio, en las tablas de oportunidades,
  comentarios, tareas y adjuntos.

  El primer arreglo fue fijar el ámbito dentro de `resolve_organization`, para
  que fuera imposible resolver sin quedar acotado. Estaba mal y la suite lo
  dijo: un `set_organization` **no tiene final**. Dentro de `run_db` muere con
  la copia del contexto del hilo, pero llamado desde código síncrono —un
  script, un job, la propia suite— deja el ámbito clavado para todo lo que
  venga después en ese hilo, incluido trabajo de otra organización o de
  ninguna. Un ámbito sin final no es un ámbito; es una fuga con otro nombre.

  Lo que hay ahora es `alcance_resuelto`, un context manager que resuelve,
  acota el bloque y lo suelta al salir, también si el cuerpo lanza. El ámbito
  se abre **después** de validar la membresía: si se abriera antes, un 403
  dejaría el bloque mirando datos de otro equipo.

  Lo usan las 44 entradas de servicio que resuelven una organización:
  oportunidades, comentarios, tareas, adjuntos, go/no-go, cuentas objetivo,
  cartera, socios, batallas, mi-baja, exportaciones y Dirección. Las únicas
  llamadas a `resolve_organization` que quedan sin ámbito viven en
  `services/organizations.py` y operan sobre `organizations`,
  `organization_memberships` y `organization_invitations`, que están
  **excluidas** de las políticas a propósito: resolver una membresía exige
  poder mirar a través de organizaciones, y ese es el `TABLAS_EXCLUIDAS` del
  test estructural.

  La primera versión de este párrafo decía «toda petición que resuelva una
  organización queda acotada» cuando siete módulos todavía no lo hacían —entre
  ellos `direccion.py`, que es la entrada de `organization_report_schedules`,
  una tabla creada **con** RLS en v132—. Se anota porque un ADR que promete
  más cobertura de la que hay es peor que uno que admite el hueco: el
  siguiente lector deja de comprobar.

  Queda un límite conocido: un `conn.commit()` a mitad de bloque cierra la
  transacción y con ella el ámbito (hoy solo lo hace
  `db/repositories/predicciones.py`, camino del scheduler).
- **Modo de fallo nuevo.** Una escritura transversal no declarada dentro de
  una petición acotada falla con `InsufficientPrivilege: new row violates
  row-level security policy`. Es el comportamiento deseado; la corrección es
  declararla (§D), no quitar la política.
- **Migraciones futuras.** Cada tabla nueva con `organization_id` añade
  `FORCE` y las dos políticas en su propia revisión (patrón de `v128`), o se
  excluye con motivo en el test estructural.
- **Reversible.** `downgrade` de `v128` borra las políticas y quita el
  `FORCE`; el `ENABLE` de `v52` se conserva. El código de aplicación sin las
  políticas sigue funcionando: el `SET LOCAL` de un GUC que nadie lee es
  inocuo.
