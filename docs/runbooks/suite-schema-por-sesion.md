# Suite de integración: schema por sesión (`TF_TEST_SCHEMA_STRATEGY=truncate`)

Estado a 2026-11-19: **el default es `truncate`** (un schema por sesión/worker
vaciado entre tests). `schema` (un schema Postgres nuevo por test,
`tests/conftest.py::_pg_schema_por_creacion`) queda como vuelta atrás con
`TF_TEST_SCHEMA_STRATEGY=schema`. El cambio sigue el procedimiento de más abajo
con las medidas del apartado siguiente; **falta medir el job `test` de CI**
(paso 3 con el runner de CI). La suite con pgvector real se ejecutó después en
local (ver «Límites de la medida»). Hasta 2026-11-06 el default era
`schema` porque la tirada completa con `truncate` (`-n 3`) agotó
`max_locks_per_transaction` y luego el disco en un cluster compartido, y esos
errores no se distinguían de los de aislamiento.

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
(también pasa aislado). Si el segundo reaparece en CI, marcar como
`schema_propio` los tres ficheros que usan `rol_mcp` (64 tests) cuesta,
estimado, unos 30 s de pared por tirada.

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
`OPENBLAS_NUM_THREADS` y `MKL_NUM_THREADS` a 1 antes de importar numpy; es la
causa de la varianza de la suite en CI (19 → 34 min según el runner).

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

- Datos vaciados: `DELETE` de todas las tablas con
  `session_replication_role = replica` (sin FKs ni triggers), cada uno en su
  transacción y todos en un pipeline; `TRUNCATE … CASCADE` si el rol no tiene
  ese permiso.
- Semillas de migración restauradas (sin columnas generadas, con
  `OVERRIDING SYSTEM VALUE`).
- **Secuencias devueltas al estado de recién migrado** (no a 1), incluidas las
  que no son de ninguna tabla.
- Vistas materializadas refrescadas.
- **Deriva de DDL detectada por huella de catálogo** (columnas, restricciones,
  índices, triggers, funciones, vistas, políticas RLS, RLS activado y
  permisos); el schema se reconstruye y el test culpable falla con nombre.
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

## Pasos para cambiar el default (hechos el 2026-11-19, salvo el runner de CI)

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

## Riesgos conocidos que no cubre

- Semillas con claves foráneas entre sí: se restauran por orden alfabético
  de tabla; una semilla que referencie a otra tabla sembrada que va después
  fallaría. No hay ningún caso hoy (sólo `api_key_tiers`), pero una migración
  futura podría crearlo.
- Datos escritos en `public` con nombre cualificado: el vaciado sólo
  alcanza al schema de la sesión.
- Re-materializar el DDL sobre una base ya usada: `_materialize_schema_ddl`
  migra `public` de la base de tests y luego borra sólo sus **tablas**; las
  funciones y tipos se quedan, y el siguiente `alembic upgrade head` desde
  cero falló (2026-11-06) con `constraint "adjudicaciones_licitacion_id_fkey"
  of relation "adjudicaciones" does not exist`, una tirada sí y otra no.
  Pasa con cualquier estrategia. La salida probable es migrar en una base de
  usar y tirar (`CREATE DATABASE`, que el Postgres de CI permite), con
  `DROP DATABASE` desacoplado porque espera a un checkpoint; no se ha medido
  cuánto WAL añade por sesión.
