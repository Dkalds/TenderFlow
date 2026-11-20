# Suite de integración: schema por sesión (`TF_TEST_SCHEMA_STRATEGY=truncate`)

Estado a 2026-11-19: **el default es `truncate`** —un schema por
sesión/worker vaciado entre tests—. `TF_TEST_SCHEMA_STRATEGY=schema` (un
schema Postgres nuevo por test, `tests/conftest.py::_pg_schema_por_creacion`)
queda como vuelta atrás. Los pasos de abajo se recorrieron el 2026-11-18/19;
lo que se midió está en «Cómo se cambió el default».

### Medido el 2026-11-19 (4 CPU, Postgres 16 local sin otras suites en el cluster, `-n 4`)

Suite no unitaria (3 682 tests; `not (unit and not slow)`), con `truncate`:

| Tirada | Resultado | Tiempo |
| --- | --- | --- |
| Orden de colección | 3 641 verdes, 38 fallos + 2 errores (todos pgvector) | 4 min 59 s |
| Orden aleatorio (semilla 7) | 3 639 verdes, 39 fallos + 3 errores | 5 min 00 s |

Cero errores «el test alteró el DDL» en ambas. Los fallos extra de la tirada
aleatoria son dos y ninguno es una fuga de la estrategia: `test_con_correo_verificado_no_se_vincula_a_una_cuenta_de_google`
falla cuando `tests/test_users.py` corre antes en el mismo worker, porque hace
`importlib.reload(db.users)` y `api/routes/auth/oauth.py` conserva la clase
`CuentaDeOtroProveedorError` anterior en su `except` (pasa aislado con las dos
estrategias); y `test_select_estrella_de_users_denegado` cayó una vez en un
deadlock al crear la política RLS del fixture `rol_mcp` sobre `webhooks`
(también pasa aislado). Los dos quedaron resueltos en #763: `test_users.py` ya
no recarga `db.users`, y el deadlock lo provocaba el autovacuum del schema de
sesión (ver «Cómo se cambió el default», paso 2).

### Límites de la medida

El Postgres del entorno no tenía pgvector y no se pudo instalar. Las
migraciones v56 y v179 se parchearon **solo en un worktree desechable**
(`vector(384)` → `real[]`, índice HNSW omitido) para poder crear el esquema; los
40 tests que dependen de `::vector` o `<=>` fallan ahí por eso y no se
ejecutaron de verdad (`test_search_semantic_hybrid`, `test_documentos_repository`,
`test_documentos_embeddings_job`, `test_rag_context`, `test_rls_tenant_scope_integration`
y alguno más). Con pgvector 0.6 ya instalado, la suite no unitaria completa,
sin parches y con `truncate` por defecto, dio 3 671 verdes, 1 saltado y
ningún fallo en 5 min 39 s (2026-11-19).

### Qué no era la estrategia: sobresuscripción de hilos

Una tirada con `truncate` tardó 15 min 08 s y otra 7 min 29 s con el mismo código:
la diferencia eran cinco tests de `test_ml_baja_model.py` que tardaban entre 142 y
667 s en vez de 3-6 s. Con `-n 4`, cada worker abría pools de BLAS/OpenMP de 4
hilos y los hilos giraban unos contra otros en 4 CPUs (carga media de 16-20).
`tests/conftest.py::pytest_configure` fija ahora `OMP_NUM_THREADS`,
`OPENBLAS_NUM_THREADS` y `MKL_NUM_THREADS` a 1 antes de importar numpy. Es
probablemente lo que hacía variar el job de CI entre 19 y 34 min según el
runner: no se ha medido en CI.

### Coste fijo por test (2026-11-19/20)

Instrumentado sobre la suite no unitaria con `truncate` (4 CPU, `-n 4`): del
tiempo de CPU, el cuerpo de los tests era el 26 %; la limpieza entre tests,
el 34 % (125 ms por test), y la huella de DDL, el 19 % (71 ms por test).
Cambios, cada uno medido o reproducido:

- Las 86 secuencias se restauran en una sola sentencia (27,8 → 1,2 ms), solo
  se vacían las tablas con filas y solo se refrescan las vistas materializadas
  con filas: la limpieza baja de ~41 a ~12 ms por test en un banco con el DDL
  real.
- Las tablas con índice HNSW o IVFFlat se vacían con `TRUNCATE`: con `DELETE`,
  repetir los ficheros de vectores en un mismo worker daba 5 fallos en
  `test_search_semantic_hybrid.py` (las filas muertas llenaban los candidatos
  del índice); con el arreglo, 0. Con el autovacuum apagado en el schema de
  sesión (#763) nada limpia esas filas muertas durante la sesión: sin el
  `TRUNCATE` el fallo iría a más.
- La huella solo se calcula si los event triggers de `tf_ddl` vieron DDL del
  schema o DDL sin schema, y además cada 50 tests. Validado provocando cada
  tipo de deriva sin `schema_propio` (ver el comentario de
  `_SQL_VIGILANCIA_DDL` en `tests/conftest.py`).

Suite completa (`python -m pytest tests -n 4`, sin cobertura, pgvector real),
en la misma máquina y una tirada detrás de otra:

| Código | Resultado | Tiempo |
| --- | --- | --- |
| `master` en c2270b6 (ya con `truncate`) | 14 636 verdes, 1 fallo, 1 error | 8 min 08 s |
| Esta rama | 14 633 verdes, 0 fallos | 3 min 59 s |
| Esta rama partida como en CI (`TF_PARTE`) | 7 708 + 6 925 verdes | 2 min 06 s y 2 min 09 s |

El fallo de `master` es de fecha (la tirada cruzó la medianoche). El error es un
deadlock en el fixture `rol_runtime` de `test_rls_tenant_scope_integration.py`,
que hace `GRANT` y `CREATE POLICY` sobre el schema compartido: la misma causa que
#763 resolvió después apagando el autovacuum del schema de sesión (c2270b6 es
anterior).

### Medido el 2026-11-06 (4 CPU, cluster cargado por otras suites)

Coste por test de dejar la base limpia, en una base con el DDL de head
(107 tablas), media de 10-15 iteraciones:

| Mecanismo | ms/test |
| --- | --- |
| Schema nuevo + DDL + `DROP SCHEMA` (default `schema`) | 1200-1500 |
| `CREATE DATABASE … TEMPLATE` + `DROP DATABASE` | 970-4200 |
| `TRUNCATE` de todas las tablas | 970-1150 |
| `DELETE` de todas las tablas sin triggers | ≈90 |
| Huella de catálogo (comprobación de deriva) | ≈110 |

`CREATE DATABASE … TEMPLATE` por test no gana: copia la base entera y
`DROP DATABASE` espera a un checkpoint inmediato de todo el cluster (más de
diez minutos con el disco ocupado por otras sesiones). `TRUNCATE` tampoco:
crea ficheros nuevos para cada tabla e índice. Por eso `truncate` vacía con
`DELETE` (y con `TRUNCATE` sólo si el rol no puede fijar
`session_replication_role`). La suite tiene unos 3.300 tests de integración:
a ≈1,2 s de DDL cada uno frente a ≈0,2 s de vaciado más huella, la estrategia
`truncate` ahorra del orden de 3.000 s de trabajo de BD en serie.

## Qué garantiza hoy `truncate`

Detalle en el comentario de `ESTRATEGIA_SCHEMA` en `tests/conftest.py`:

- Datos vaciados: solo las tablas que tienen filas (lo dice una consulta de
  ~1 ms), con `DELETE` y `session_replication_role = replica` (sin FKs ni
  triggers), cada uno en su transacción y todos en un pipeline. Las que tienen
  un índice HNSW o IVFFlat de pgvector se vacían con `TRUNCATE`: un `DELETE`
  deja sus filas muertas en el grafo del índice y una búsqueda vectorial
  filtrada devolvía vacío. `TRUNCATE … CASCADE` para todas si el rol no puede
  fijar `session_replication_role`.
- Semillas de migración restauradas (sin columnas generadas, con
  `OVERRIDING SYSTEM VALUE`).
- **Secuencias devueltas al estado de recién migrado** (no a 1), incluidas las
  que no son de ninguna tabla.
- Vistas materializadas refrescadas cuando tienen filas: vacías sobre tablas
  vacías ya están como recién refrescadas.
- **Deriva de DDL detectada por huella de catálogo** (columnas, restricciones,
  índices, triggers, funciones, vistas, políticas RLS, RLS activado y
  permisos); el schema se reconstruye y el test culpable falla con nombre.
  La huella solo se calcula cuando los event triggers del schema `tf_ddl` han
  visto DDL de ese schema, o DDL sin schema (`GRANT`, `REVOKE` y
  `CREATE POLICY` llegan así); sin superusuario, tras cada test.
- **Un schema a medio construir se rehace** en el siguiente test: se construye
  perezosamente y, si el vaciado falla, se reconstruye. Antes un fallo al
  reconstruir (p. ej. sin locks libres) dejaba en error al resto del worker.
- `@pytest.mark.schema_propio` para los tests que alteran el DDL a propósito;
  los que ya lo llevan salen de `grep -rn schema_propio tests/` (una lista a
  mano aquí se quedaba atrás). Puede faltar alguno que altere el DDL por una
  vía indirecta (un repositorio que cree tablas): la huella lo detectará en
  la primera tirada.
- Un valor desconocido de `TF_TEST_SCHEMA_STRATEGY` es un error de uso, no un
  retorno silencioso a `schema`.

## Pasos para cambiar el default (hechos el 2026-11-18/19)

1. Tirada completa con la estrategia nueva, en CI o en local con Postgres:

   ```bash
   TF_TEST_SCHEMA_STRATEGY=truncate make test-integration
   ```

   Criterio: verde, incluido `tests/test_aislamiento_entre_tests.py`, y **cero**
   errores «el test alteró el DDL del schema compartido». Cada uno de esos es
   un test que hay que marcar `schema_propio` (o reescribir para no tocar DDL).
2. Repetir con orden aleatorio y con xdist (`make test-parallel` con la
   variable puesta): las fugas por orden sólo aparecen así.
3. Medir: duración de `make test-integration` con `schema` y con `truncate`
   en el mismo runner. Si la mejora no compensa, no se cambia.
4. Sólo entonces cambiar el default en `ESTRATEGIA_SCHEMA` y dejar `schema`
   como vuelta atrás por variable.

## Cómo se cambió el default (2026-11-18/19)

Local, 4 CPU, Postgres 16, `-n auto`, `(unit or integration) and not slow`:

- Paso 1: la primera tirada con `truncate` dio 7 errores de DDL compartido y
  un test que necesitaba la tabla recién creada (`reltuples = -1`); los ocho
  llevan ahora `schema_propio`. La siguiente tirada, en verde.
- Paso 2: con xdist y orden barajado (semilla fija, un plugin desechable que
  baraja en `pytest_collection_modifyitems`) fallan unos 40 tests **con las dos
  estrategias**: 44 con `schema` y 38 con `truncate` en la misma semilla, de los
  mismos ficheros. Es estado de módulo que se filtra entre tests (p. ej. un test
  que sustituye `config.settings` y otro que parchea el objeto viejo), no datos
  de la BD. Arreglado el 2026-11-20 en el test que contaminaba (sin `reload` de
  módulos, sin sacar `config` de `sys.modules`, sin autovacuum en el schema de
  sesión, que además chocaba con el DDL de `rol_mcp`): 14.552 pasados en orden
  normal y con las semillas 4242 y 1119 (`truncate`) y 4242 (`schema`). La
  semilla 1337 sacó una fuga más: `test_escenario_adjuntos.py` (CU-37) deja
  ligada la organización del presupuesto LLM y `test_c2_cuentas.py` fallaba si
  corría después en el mismo worker; desde entonces un fixture de `conftest.py`
  la limpia antes de cada test.
- Paso 3: 1.618 s con `schema` frente a 508 s con `truncate`. En CI, el job `Tests (Postgres)` pasó de 26 min 15 s (#758, `schema`) a 14 min 46 s (#761, `truncate`).

## Riesgos conocidos que no cubre

- Semillas con claves foráneas entre sí: se restauran por orden alfabético
  de tabla; una semilla que referencie a otra tabla sembrada que va después
  fallaría. No hay ningún caso hoy (sólo `api_key_tiers`), pero una migración
  futura podría crearlo.
- Datos escritos en `public` con nombre cualificado: el vaciado sólo
  alcanza al schema de la sesión.

Resuelto el 2026-11-18 (#758): re-materializar el DDL sobre una base ya usada
fallaba porque se migraba la propia base de tests. `_materialize_schema_ddl`
migra ahora en una base hermana `<base>_ddl` que no se borra (`DROP DATABASE`
espera a un checkpoint), con un advisory lock entre sesiones; el rol de
`TEST_DATABASE_URL` necesita `CREATEDB` la primera vez.
